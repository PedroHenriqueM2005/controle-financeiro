"""Livro-razão: lançamentos, categorias, ciclos mensais e resumos.

Um **lançamento** (transaction) tem sempre:

* ``type``: ``entrada`` (dinheiro que chega) ou ``saida`` (dinheiro que sai);
* ``status``: ``previsto`` (ainda vai acontecer — o salário que você *pretende*
  receber, a conta que ainda vence) ou ``realizado`` (já aconteceu);
* ``period``: mês de competência (``YYYY-MM``), derivado da data.

Essa separação previsto/realizado é o que permite responder "quanto eu ainda
vou receber este mês?" e "quanto já gastei do que recebi?".
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any, Iterable, Sequence

from .. import config
from ..money import format_brl, format_percent, parse_amount, percent
from ..utils import (
    current_period,
    days_in_month,
    format_date,
    normalize,
    parse_date,
    period_label,
    period_of,
    previous_period,
    shift_period,
    today,
    truncate,
)
from . import catalog, settings

VALID_TYPES = ("entrada", "saida")
VALID_STATUS = ("previsto", "realizado")

# marca os lançamentos criados pela geração automática dos fixos do mês,
# para que possam ser desfeitos em bloco sem tocar nos demais
SOURCE_AUTO_RECORRENTE = "recorrente-auto"

TX_SELECT = """
SELECT t.*,
       c.name  AS category_name,
       c.color AS category_color,
       c.kind  AS category_kind,
       i.name  AS item_name,
       i.unit  AS item_unit
FROM transactions t
LEFT JOIN categories c ON c.id = t.category_id
LEFT JOIN items i      ON i.id = t.item_id
"""


class ValidationError(ValueError):
    """Erro de validação de lançamento — vira HTTP 422 nas rotas."""


# ------------------------------------------------------------------ categorias

def list_categories(
    conn: sqlite3.Connection,
    kind: str | None = None,
    include_archived: bool = False,
    period: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM categories WHERE 1=1"
    params: list[Any] = []
    if not include_archived:
        sql += " AND archived = 0"
    if kind in VALID_TYPES:
        sql += " AND kind = ?"
        params.append(kind)
    sql += " ORDER BY kind, name"
    rows = conn.execute(sql, tuple(params)).fetchall()

    gastos_saida: dict[int, int] = {}
    total_entrada: dict[int, int] = {}
    if period:
        for r in conn.execute(
            "SELECT category_id, type, SUM(amount_centavos) AS total FROM transactions "
            "WHERE period = ? AND category_id IS NOT NULL GROUP BY category_id, type",
            (period,),
        ):
            if r["type"] == "saida":
                gastos_saida[int(r["category_id"])] = int(r["total"] or 0)
            else:
                total_entrada[int(r["category_id"])] = int(r["total"] or 0)

    resultado = []
    for r in rows:
        d = dict(r)
        d["usos"] = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE category_id = ?", (d["id"],)
        ).fetchone()[0]
        if period:
            total_mes = gastos_saida.get(int(d["id"]), 0) if d["kind"] == "saida" else total_entrada.get(int(d["id"]), 0)
        else:
            total_mes = 0
        budget = d.get("budget_centavos")
        d.update(
            {
                "total_mes": total_mes,
                "total_mes_fmt": format_brl(total_mes),
                "budget_fmt": format_brl(budget) if budget else None,
                "budget_pct": percent(total_mes, budget) if budget else None,
                "budget_pct_fmt": format_percent(percent(total_mes, budget) if budget else None, sinal=False),
                "estourou": bool(budget and total_mes > budget),
            }
        )
        resultado.append(d)
    return resultado


def ensure_category(
    conn: sqlite3.Connection,
    name: str | None,
    kind: str = "saida",
    color: str = "#94a3b8",
    create: bool = True,
) -> int | None:
    """Retorna o id da categoria pelo nome (normalizado); cria se não existir."""
    nome = (name or "").strip()
    if not nome:
        return None
    alvo = normalize(nome)
    for row in conn.execute("SELECT id, name FROM categories"):
        if normalize(row["name"]) == alvo:
            return int(row["id"])
    if not create:
        return None
    cur = conn.execute(
        "INSERT INTO categories (name, kind, color) VALUES (?, ?, ?)",
        (nome, kind if kind in VALID_TYPES else "saida", color),
    )
    return int(cur.lastrowid)


def create_category(conn: sqlite3.Connection, name: str, kind: str, color: str, budget: int | None = None) -> int:
    nome = (name or "").strip()
    if not nome:
        raise ValidationError("Informe o nome da categoria.")
    if kind not in VALID_TYPES:
        raise ValidationError("Tipo de categoria inválido (use 'entrada' ou 'saida').")
    if ensure_category(conn, nome, kind, create=False):
        raise ValidationError(f"A categoria '{nome}' já existe.")
    cur = conn.execute(
        "INSERT INTO categories (name, kind, color, budget_centavos) VALUES (?, ?, ?, ?)",
        (nome, kind, color or "#94a3b8", budget),
    )
    return int(cur.lastrowid)


def update_category(conn: sqlite3.Connection, category_id: int, data: dict[str, Any]) -> None:
    campos, params = [], []
    if "name" in data and (data["name"] or "").strip():
        campos.append("name = ?")
        params.append(data["name"].strip())
    if "kind" in data and data["kind"] in VALID_TYPES:
        campos.append("kind = ?")
        params.append(data["kind"])
    if "color" in data and data["color"]:
        campos.append("color = ?")
        params.append(data["color"])
    if "budget" in data:
        campos.append("budget_centavos = ?")
        params.append(data["budget"])
    if "archived" in data:
        campos.append("archived = ?")
        params.append(1 if data["archived"] else 0)
    if not campos:
        return
    params.append(category_id)
    conn.execute(f"UPDATE categories SET {', '.join(campos)} WHERE id = ?", tuple(params))


def delete_category(conn: sqlite3.Connection, category_id: int) -> int:
    """Apaga a categoria; os lançamentos ficam sem categoria (NULL)."""
    afetados = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE category_id = ?", (category_id,)
    ).fetchone()[0]
    conn.execute("UPDATE transactions SET category_id = NULL WHERE category_id = ?", (category_id,))
    conn.execute("UPDATE items SET category_id = NULL WHERE category_id = ?", (category_id,))
    conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
    return int(afetados)


# ------------------------------------------------------------------ ciclos

def get_cycle(conn: sqlite3.Connection, period: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM cycles WHERE period = ?", (period,)).fetchone()
    dados = dict(row) if row else {
        "period": period,
        "expected_income_centavos": 0,
        "payday_day": None,
        "expected_locked": 0,
        "note": None,
    }
    dados["expected_locked"] = bool(dados.get("expected_locked"))
    dados["expected_fmt"] = format_brl(dados.get("expected_income_centavos") or 0)
    dados["label"] = period_label(period)
    return dados


def save_cycle(
    conn: sqlite3.Connection,
    period: str,
    expected: int | None = None,
    payday_day: int | None = None,
    note: str | None = None,
    lock: bool = True,
) -> dict[str, Any]:
    """Define/ajusta o salário previsto do mês.

    ``lock=True`` marca o valor como definido à mão, impedindo a
    auto-sincronização com os lançamentos de salário.
    """
    atual = get_cycle(conn, period)
    novo_expected = atual["expected_income_centavos"] if expected is None else max(0, int(expected))
    novo_dia = atual.get("payday_day") if payday_day is None else payday_day
    if novo_dia is not None:
        novo_dia = min(max(int(novo_dia), 1), 31)
    nova_nota = atual.get("note") if note is None else (note or None)
    novo_lock = 1 if (lock if expected is not None else atual["expected_locked"]) else 0

    conn.execute(
        """
        INSERT INTO cycles (period, expected_income_centavos, payday_day, expected_locked, note, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(period) DO UPDATE SET
            expected_income_centavos = excluded.expected_income_centavos,
            payday_day               = excluded.payday_day,
            expected_locked          = excluded.expected_locked,
            note                     = excluded.note,
            updated_at               = datetime('now')
        """,
        (period, novo_expected, novo_dia, novo_lock, nova_nota),
    )
    return get_cycle(conn, period)


def sync_cycle_from_salary(conn: sqlite3.Connection, period: str) -> None:
    """Se o mês não tem salário definido à mão, usa a soma das entradas de
    categoria "Salário" como previsão. Facilita o primeiro uso: o usuário só
    lança o salário e o painel já mostra a meta do mês."""
    ciclo = get_cycle(conn, period)
    if ciclo["expected_locked"]:
        return
    total = conn.execute(
        """
        SELECT COALESCE(SUM(t.amount_centavos), 0)
        FROM transactions t
        JOIN categories c ON c.id = t.category_id
        WHERE t.period = ? AND t.type = 'entrada' AND LOWER(c.name) LIKE 'sal%'
        """,
        (period,),
    ).fetchone()[0]
    if int(total or 0) != int(ciclo["expected_income_centavos"] or 0):
        save_cycle(conn, period, expected=int(total or 0), lock=False)


def list_cycles(conn: sqlite3.Connection, limit: int = 24) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM cycles ORDER BY period DESC LIMIT ?", (limit,)).fetchall()
    return [get_cycle(conn, r["period"]) for r in rows]


# ------------------------------------------------------------------ lançamentos

def _coerce(data: dict[str, Any]) -> dict[str, Any]:
    """Valida e normaliza o dicionário de entrada de um lançamento."""
    tipo = str(data.get("type") or "saida").strip().lower()
    if tipo in ("receita", "entrada", "income", "credito", "crédito", "+"):
        tipo = "entrada"
    elif tipo in ("despesa", "saida", "saída", "expense", "debito", "débito", "-"):
        tipo = "saida"
    if tipo not in VALID_TYPES:
        raise ValidationError("Tipo inválido: use 'entrada' ou 'saida'.")

    status = str(data.get("status") or "realizado").strip().lower()
    if status in ("pago", "recebido", "realizado", "paid", "done", "efetivado"):
        status = "realizado"
    elif status in ("previsto", "pendente", "a pagar", "a receber", "planned", "pending"):
        status = "previsto"
    if status not in VALID_STATUS:
        raise ValidationError("Status inválido: use 'previsto' ou 'realizado'.")

    centavos = data.get("amount_centavos")
    if not isinstance(centavos, int):
        # aceita "1.250,00", 1250.0 ou None — sempre normalizado para centavos
        centavos = parse_amount(centavos, default=None)
    if centavos is None:
        centavos = parse_amount(data.get("amount"))
    if centavos is None:
        raise ValidationError("Informe um valor válido (ex.: 1.250,00).")
    centavos = abs(int(centavos))
    if centavos <= 0:
        raise ValidationError("O valor precisa ser maior que zero.")

    dia = parse_date(data.get("occurred_on") or today())
    if dia is None:
        raise ValidationError("Data inválida (use AAAA-MM-DD ou DD/MM/AAAA).")

    descricao = str(data.get("description") or "").strip()
    if not descricao and data.get("item_name"):
        descricao = str(data["item_name"]).strip()
    if not descricao:
        descricao = "Salário" if tipo == "entrada" else "Lançamento sem descrição"

    metodo = (str(data.get("method")).strip() or None) if data.get("method") else None

    return {
        "type": tipo,
        "status": status,
        "occurred_on": dia.isoformat(),
        "period": period_of(dia),
        "amount_centavos": centavos,
        "description": truncate(descricao, 200),
        "category_id": data.get("category_id"),
        "category_name": data.get("category_name"),
        "item_id": data.get("item_id"),
        "item_name": data.get("item_name"),
        "method": metodo,
        "recurring": 1 if data.get("recurring") in (1, True, "1", "on", "true") else 0,
        "note": (str(data.get("note")).strip() or None) if data.get("note") else None,
        "source": data.get("source") or "manual",
        "import_id": data.get("import_id"),
    }


def create_transaction(conn: sqlite3.Connection, data: dict[str, Any], create_item: bool = True) -> dict[str, Any]:
    d = _coerce(data)

    categoria_id = d.pop("category_id", None)
    categoria_nome = d.pop("category_name", None)
    if not categoria_id and categoria_nome:
        categoria_id = ensure_category(conn, categoria_nome, d["type"])

    item_id = d.pop("item_id", None)
    item_nome = d.pop("item_name", None)
    if not item_id and item_nome and d["type"] == "saida":
        item_id = catalog.ensure_item(conn, item_nome, categoria_id, create=create_item)
    if item_id and not categoria_id:
        row = conn.execute("SELECT category_id FROM items WHERE id = ?", (item_id,)).fetchone()
        if row and row["category_id"]:
            categoria_id = int(row["category_id"])

    cur = conn.execute(
        """
        INSERT INTO transactions
            (type, status, occurred_on, period, amount_centavos, description,
             category_id, item_id, method, recurring, source, import_id, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            d["type"], d["status"], d["occurred_on"], d["period"], d["amount_centavos"],
            d["description"], categoria_id, item_id, d["method"], d["recurring"],
            d["source"], d["import_id"], d["note"],
        ),
    )
    tx_id = int(cur.lastrowid)
    sync_cycle_from_salary(conn, d["period"])
    return get_transaction(conn, tx_id)  # type: ignore[return-value]


def update_transaction(conn: sqlite3.Connection, tx_id: int, data: dict[str, Any], create_item: bool = True) -> dict[str, Any] | None:
    atual = get_transaction(conn, tx_id)
    if not atual:
        return None
    mes_antigo = atual["period"]

    base = {
        "type": data.get("type", atual["type"]),
        "status": data.get("status", atual["status"]),
        "occurred_on": data.get("occurred_on", atual["occurred_on"]),
        "amount_centavos": data.get("amount_centavos", atual["amount_centavos"]),
        "description": data.get("description", atual["description"]),
        "category_id": data.get("category_id", atual["category_id"]),
        "category_name": data.get("category_name"),
        "item_id": data.get("item_id", atual["item_id"]),
        "item_name": data.get("item_name"),
        "method": data.get("method", atual["method"]),
        "recurring": data.get("recurring", atual["recurring"]),
        "note": data.get("note", atual["note"]),
        "source": atual["source"],
        "import_id": atual.get("import_id"),
    }
    if "amount" in data and data["amount"] is not None:
        base["amount_centavos"] = parse_amount(data["amount"], default=atual["amount_centavos"])

    d = _coerce(base)
    categoria_id = d.pop("category_id", None)
    categoria_nome = d.pop("category_name", None)
    if categoria_nome and not categoria_id:
        categoria_id = ensure_category(conn, categoria_nome, d["type"])
    item_id = d.pop("item_id", None)
    item_nome = d.pop("item_name", None)
    if item_nome and not item_id and d["type"] == "saida":
        item_id = catalog.ensure_item(conn, item_nome, categoria_id, create=create_item)

    conn.execute(
        """
        UPDATE transactions SET
            type = ?, status = ?, occurred_on = ?, period = ?, amount_centavos = ?,
            description = ?, category_id = ?, item_id = ?, method = ?, recurring = ?,
            note = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            d["type"], d["status"], d["occurred_on"], d["period"], d["amount_centavos"],
            d["description"], categoria_id, item_id, d["method"], d["recurring"],
            d["note"], tx_id,
        ),
    )
    for periodo in {mes_antigo, d["period"]}:
        sync_cycle_from_salary(conn, periodo)
    return get_transaction(conn, tx_id)


def delete_transaction(conn: sqlite3.Connection, tx_id: int) -> str | None:
    row = conn.execute("SELECT period FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    if not row:
        return None
    conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
    sync_cycle_from_salary(conn, row["period"])
    return row["period"]


def get_transaction(conn: sqlite3.Connection, tx_id: int) -> dict[str, Any] | None:
    row = conn.execute(TX_SELECT + " WHERE t.id = ?", (tx_id,)).fetchone()
    return decorate_transaction(dict(row)) if row else None


def list_transactions(
    conn: sqlite3.Connection,
    period: str | None = None,
    tx_type: str | None = None,
    status: str | None = None,
    category_id: int | None = None,
    item_id: int | None = None,
    search: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    order: str = "desc",
    limit: int | None = None,
    offset: int = 0,
) -> list[dict[str, Any]]:
    where, params = _build_filters(period, tx_type, status, category_id, item_id, search, date_from, date_to)
    direcao = "ASC" if str(order).lower() == "asc" else "DESC"
    sql = TX_SELECT + f" WHERE {where} ORDER BY t.occurred_on {direcao}, t.id {direcao}"
    if limit:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    return [decorate_transaction(dict(r)) for r in conn.execute(sql, tuple(params)).fetchall()]


def list_recurring(conn: sqlite3.Connection, period: str) -> list[dict[str, Any]]:
    """Lançamentos marcados como fixos (``recurring``) no mês, maiores primeiro.

    Usada pelo cartão "Gastos fixos" do painel e pela tela de configurações.
    """
    rows = conn.execute(
        TX_SELECT + " WHERE t.period = ? AND t.recurring = 1 "
        "ORDER BY t.type, t.amount_centavos DESC",
        (period,),
    ).fetchall()
    return [decorate_transaction(dict(r)) for r in rows]


def recurring_summary(conn: sqlite3.Connection, period: str) -> dict[str, Any]:
    """Totais dos fixos do mês, separando o que já foi pago do que está previsto."""
    fixos = list_recurring(conn, period)
    saidas = [f for f in fixos if f["type"] == "saida"]
    realizadas = [f for f in saidas if f["status"] == "realizado"]
    previstas = [f for f in saidas if f["status"] == "previsto"]
    auto = count_auto_generated(conn, period)
    return {
        "period": period,
        "lancamentos": fixos,
        "qtd": len(saidas),
        "qtd_realizadas": len(realizadas),
        "qtd_previstas": len(previstas),
        "total": sum(int(f["amount_centavos"]) for f in saidas),
        "total_fmt": format_brl(sum(int(f["amount_centavos"]) for f in saidas)),
        "realizado": sum(int(f["amount_centavos"]) for f in realizadas),
        "realizado_fmt": format_brl(sum(int(f["amount_centavos"]) for f in realizadas)),
        "previsto": sum(int(f["amount_centavos"]) for f in previstas),
        "previsto_fmt": format_brl(sum(int(f["amount_centavos"]) for f in previstas)),
        "gerados_auto": auto,
        "pendentes": len(next_recurring(conn, period)),
    }


def count_transactions(conn: sqlite3.Connection, **filters: Any) -> int:
    where, params = _build_filters(
        filters.get("period"), filters.get("tx_type"), filters.get("status"),
        filters.get("category_id"), filters.get("item_id"), filters.get("search"),
        filters.get("date_from"), filters.get("date_to"),
    )
    sql = (
        "SELECT COUNT(*) FROM transactions t "
        "LEFT JOIN items i ON i.id = t.item_id "
        f"WHERE {where}"
    )
    return int(conn.execute(sql, tuple(params)).fetchone()[0])


def _build_filters(
    period, tx_type, status, category_id, item_id, search, date_from, date_to
) -> tuple[str, list[Any]]:
    where = ["1=1"]
    params: list[Any] = []
    if period:
        where.append("t.period = ?")
        params.append(period)
    if tx_type in VALID_TYPES:
        where.append("t.type = ?")
        params.append(tx_type)
    if status in VALID_STATUS:
        where.append("t.status = ?")
        params.append(status)
    if category_id:
        where.append("t.category_id = ?")
        params.append(int(category_id))
    if item_id:
        where.append("t.item_id = ?")
        params.append(int(item_id))
    if search:
        where.append("(LOWER(t.description) LIKE ? OR LOWER(COALESCE(i.name,'')) LIKE ? OR LOWER(t.note) LIKE ?)")
        like = f"%{normalize(search)}%"
        params.extend([like, like, like])
    if date_from:
        where.append("t.occurred_on >= ?")
        params.append(parse_date(date_from).isoformat())
    if date_to:
        where.append("t.occurred_on <= ?")
        params.append(parse_date(date_to).isoformat())
    return " AND ".join(where), params


def decorate_transaction(row: dict[str, Any]) -> dict[str, Any]:
    """Campos derivados de um lançamento, prontos para template/JSON."""
    valor = int(row["amount_centavos"])
    sinal = 1 if row["type"] == "entrada" else -1
    row.update(
        {
            "valor_fmt": format_brl(valor),
            "valor_sinal_fmt": format_brl(valor * sinal, sinal=True),
            "data_fmt": format_date(row["occurred_on"]),
            "label": truncate(row.get("item_name") or row.get("description") or "—", 60),
            "is_entrada": row["type"] == "entrada",
            "is_previsto": row["status"] == "previsto",
            "category_color": row.get("category_color") or "#94a3b8",
        }
    )
    return row


def toggle_status(conn: sqlite3.Connection, tx_id: int) -> dict[str, Any] | None:
    """Alterna previsto ⇄ realizado (o "chegou o salário"/"paguei a conta")."""
    row = conn.execute("SELECT status, period FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    if not row:
        return None
    novo = "realizado" if row["status"] == "previsto" else "previsto"
    conn.execute("UPDATE transactions SET status = ?, updated_at = datetime('now') WHERE id = ?", (novo, tx_id))
    sync_cycle_from_salary(conn, row["period"])
    return get_transaction(conn, tx_id)


# ------------------------------------------------------------------ resumos

def _sum(conn: sqlite3.Connection, period: str, tx_type: str, status: str) -> int:
    return int(
        conn.execute(
            "SELECT COALESCE(SUM(amount_centavos),0) FROM transactions WHERE period=? AND type=? AND status=?",
            (period, tx_type, status),
        ).fetchone()[0]
        or 0
    )


def totals(conn: sqlite3.Connection, period: str) -> dict[str, int]:
    er, ep = _sum(conn, period, "entrada", "realizado"), _sum(conn, period, "entrada", "previsto")
    sr, sp = _sum(conn, period, "saida", "realizado"), _sum(conn, period, "saida", "previsto")
    return {
        "entradas_realizadas": er,
        "entradas_previstas": ep,
        "saidas_realizadas": sr,
        "saidas_previstas": sp,
        "entradas": er + ep,
        "saidas": sr + sp,
        "saldo_real": er - sr,
        "saldo_projetado": (er + ep) - (sr + sp),
    }


def category_breakdown(conn: sqlite3.Connection, period: str, tx_type: str = "saida") -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT COALESCE(c.name, 'Sem categoria') AS name,
               COALESCE(c.color, '#94a3b8')     AS color,
               c.id                              AS id,
               c.budget_centavos                 AS budget,
               SUM(t.amount_centavos)            AS total,
               COUNT(*)                          AS qtd
        FROM transactions t
        LEFT JOIN categories c ON c.id = t.category_id
        WHERE t.period = ? AND t.type = ?
        GROUP BY COALESCE(c.name, 'Sem categoria')
        ORDER BY total DESC
        """,
        (period, tx_type),
    ).fetchall()
    total_geral = sum(int(r["total"] or 0) for r in rows) or 0
    resultado = []
    for r in rows:
        total = int(r["total"] or 0)
        budget = r["budget"]
        resultado.append(
            {
                "id": r["id"],
                "name": r["name"],
                "color": r["color"],
                "total": total,
                "total_fmt": format_brl(total),
                "qtd": r["qtd"],
                "pct": percent(total, total_geral),
                "budget": budget,
                "budget_fmt": format_brl(budget) if budget else None,
                "budget_pct": percent(total, budget) if budget else None,
                "budget_pct_fmt": format_percent(percent(total, budget) if budget else None, sinal=False),
                "estourou": bool(budget and total > budget),
                "quase_estourando": bool(budget and budget * 0.8 <= total <= budget),
            }
        )
    return resultado


def budget_summary(conn: sqlite3.Connection, period: str, tx_type: str = "saida") -> dict[str, Any]:
    """Orçamento × gasto por categoria — visão **informativa** (sem alertas).

    Duas diferenças importantes em relação a :func:`category_breakdown`:

    * parte das **categorias que têm limite definido**, e não dos lançamentos —
      assim uma categoria orçada mas ainda sem gasto no mês aparece com R$ 0,00
      em vez de sumir da tela;
    * separa o que já foi **realizado** do que está **previsto**. A barra de
      progresso usa só o realizado (é o dinheiro que efetivamente saiu), e o
      previsto aparece como informação adicional.
    """
    movimentado: dict[int, dict[str, int]] = {}
    for r in conn.execute(
        "SELECT category_id, status, SUM(amount_centavos) AS total, COUNT(*) AS qtd "
        "FROM transactions WHERE period = ? AND type = ? AND category_id IS NOT NULL "
        "GROUP BY category_id, status",
        (period, tx_type),
    ):
        alvo = movimentado.setdefault(int(r["category_id"]), {"realizado": 0, "previsto": 0, "qtd": 0})
        alvo["realizado" if r["status"] == "realizado" else "previsto"] += int(r["total"] or 0)
        alvo["qtd"] += int(r["qtd"] or 0)

    categorias: list[dict[str, Any]] = []
    for r in conn.execute(
        "SELECT id, name, color, budget_centavos AS budget FROM categories "
        "WHERE budget_centavos IS NOT NULL AND archived = 0 AND kind = ? ORDER BY name",
        (tx_type,),
    ):
        budget = int(r["budget"] or 0)
        mov = movimentado.get(int(r["id"]), {"realizado": 0, "previsto": 0, "qtd": 0})
        gasto = mov["realizado"]
        previsto = mov["previsto"]
        disponivel = budget - gasto
        pct = percent(gasto, budget)
        categorias.append(
            {
                "id": r["id"],
                "name": r["name"],
                "color": r["color"],
                "budget": budget,
                "budget_fmt": format_brl(budget),
                "gasto": gasto,
                "gasto_fmt": format_brl(gasto),
                "previsto": previsto,
                "previsto_fmt": format_brl(previsto),
                "qtd": mov["qtd"],
                "disponivel": disponivel,
                "disponivel_fmt": format_brl(abs(disponivel)),
                "pct": pct,
                "pct_fmt": format_percent(pct, sinal=False),
                "acima": gasto > budget,
                "perto": bool(budget) and budget * 0.8 <= gasto <= budget,
            }
        )
    # mais comprometido primeiro; sem limite definido não existe aqui
    categorias.sort(key=lambda c: (-(c["pct"] or 0), c["name"]))

    orcado = sum(c["budget"] for c in categorias)
    gasto = sum(c["gasto"] for c in categorias)
    previsto = sum(c["previsto"] for c in categorias)
    return {
        "period": period,
        "categorias": categorias,
        "qtd": len(categorias),
        "orcado": orcado,
        "orcado_fmt": format_brl(orcado),
        "gasto": gasto,
        "gasto_fmt": format_brl(gasto),
        "previsto": previsto,
        "previsto_fmt": format_brl(previsto),
        "disponivel": orcado - gasto,
        "disponivel_fmt": format_brl(abs(orcado - gasto)),
        "pct": percent(gasto, orcado),
        "pct_fmt": format_percent(percent(gasto, orcado), sinal=False),
        "acima": gasto > orcado,
        "tem_dados": bool(categorias),
    }


def method_breakdown(conn: sqlite3.Connection, period: str, tx_type: str = "saida") -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT COALESCE(NULLIF(method,''), 'Não informado') AS method,
               SUM(amount_centavos) AS total, COUNT(*) AS qtd
        FROM transactions WHERE period = ? AND type = ?
        GROUP BY method ORDER BY total DESC
        """,
        (period, tx_type),
    ).fetchall()
    total_geral = sum(int(r["total"] or 0) for r in rows) or 0
    return [
        {
            "method": r["method"],
            "total": int(r["total"] or 0),
            "total_fmt": format_brl(r["total"]),
            "qtd": r["qtd"],
            "pct": percent(int(r["total"] or 0), total_geral),
        }
        for r in rows
    ]


def top_items(conn: sqlite3.Connection, period: str, limit: int = 8) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT COALESCE(i.name, t.description) AS name,
               i.id AS item_id,
               COUNT(*) AS qtd,
               SUM(t.amount_centavos) AS total,
               AVG(t.amount_centavos) AS preco_medio
        FROM transactions t
        LEFT JOIN items i ON i.id = t.item_id
        WHERE t.period = ? AND t.type = 'saida'
        GROUP BY COALESCE(i.name, t.description)
        ORDER BY total DESC LIMIT ?
        """,
        (period, limit),
    ).fetchall()
    return [
        {
            "name": truncate(r["name"], 45),
            "item_id": r["item_id"],
            "qtd": r["qtd"],
            "total": int(r["total"] or 0),
            "total_fmt": format_brl(r["total"]),
            "preco_medio": int(r["preco_medio"] or 0),
            "preco_medio_fmt": format_brl(int(r["preco_medio"] or 0)),
        }
        for r in rows
    ]


def fixed_vs_variable(conn: sqlite3.Connection, period: str) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT recurring, COALESCE(SUM(amount_centavos),0) AS total, COUNT(*) AS qtd
        FROM transactions WHERE period = ? AND type = 'saida' AND status = 'realizado'
        GROUP BY recurring
        """,
        (period,),
    ).fetchall()
    fixos = variaveis = 0
    qtd_fixos = qtd_var = 0
    for r in rows:
        if r["recurring"]:
            fixos, qtd_fixos = int(r["total"]), r["qtd"]
        else:
            variaveis, qtd_var = int(r["total"]), r["qtd"]
    total = fixos + variaveis
    return {
        "fixos": fixos, "fixos_fmt": format_brl(fixos), "qtd_fixos": qtd_fixos,
        "variaveis": variaveis, "variaveis_fmt": format_brl(variaveis), "qtd_variaveis": qtd_var,
        "fixos_pct": percent(fixos, total),
        "variaveis_pct": percent(variaveis, total),
    }


def series(conn: sqlite3.Connection, end_period: str | None = None, months: int = 6) -> list[dict[str, Any]]:
    """Série mensal (mais antiga → mais recente) para gráficos."""
    fim = end_period or current_period()
    periodos = [shift_period(fim, -(months - 1 - i)) for i in range(months)]
    marcadores = ",".join("?" * len(periodos))
    rows = {
        r["period"]: dict(r)
        for r in conn.execute(
            f"""
            SELECT period,
                   SUM(CASE WHEN type='entrada' AND status='realizado' THEN amount_centavos ELSE 0 END) AS entradas,
                   SUM(CASE WHEN type='saida'   AND status='realizado' THEN amount_centavos ELSE 0 END) AS saidas,
                   SUM(CASE WHEN type='saida'   AND status='previsto'  THEN amount_centavos ELSE 0 END) AS saidas_previstas,
                   SUM(CASE WHEN type='entrada' AND status='previsto'  THEN amount_centavos ELSE 0 END) AS entradas_previstas
            FROM transactions WHERE period IN ({marcadores}) GROUP BY period
            """,
            tuple(periodos),
        )
    }
    saida: list[dict[str, Any]] = []
    for p in periodos:
        r = rows.get(p, {})
        entradas = int(r.get("entradas") or 0)
        saidas = int(r.get("saidas") or 0)
        saida.append(
            {
                "period": p,
                "entradas": entradas,
                "saidas": saidas,
                "saldo": entradas - saidas,
                "entradas_previstas": int(r.get("entradas_previstas") or 0),
                "saidas_previstas": int(r.get("saidas_previstas") or 0),
                "entradas_fmt": format_brl(entradas),
                "saidas_fmt": format_brl(saidas),
                "saldo_fmt": format_brl(entradas - saidas),
                "vazio": not r,
            }
        )
    return saida


def available_periods(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT period FROM transactions GROUP BY period "
        "UNION SELECT period FROM cycles GROUP BY period ORDER BY period DESC"
    ).fetchall()
    periodos = [r["period"] for r in rows]
    atual = current_period()
    if atual not in periodos:
        periodos.insert(0, atual)
    return sorted(set(periodos), reverse=True)


def build_alerts(conn: sqlite3.Connection, period: str, resumo: dict[str, Any]) -> list[dict[str, Any]]:
    """Alertas acionáveis do mês (preço em alta, saldo projetado, a receber…).

    Orçamento **não** entra aqui de propósito: o usuário pediu acompanhamento
    informativo, sem ser alertado. O comparativo limite × gasto vive no cartão
    "Orçamentos do mês" (``budget_summary``), sempre visível, sem alarme.
    """
    alertas: list[dict[str, Any]] = []

    for alerta in catalog.price_alerts(conn, period)[:3]:
        sentido = "subiu" if alerta["subiu"] else "caiu"
        alertas.append(
            {
                "nivel": "atencao" if alerta["subiu"] else "info",
                "tipo": "preco",
                "titulo": f"{alerta['name']} {sentido} {alerta['variacao_fmt']}",
                "texto": (
                    f"Preço médio neste mês: {alerta['media_mes_fmt']} "
                    f"(antes: {alerta['media_antes_fmt']})."
                ),
                "item_id": alerta["item_id"],
            }
        )

    if resumo["saldo_projetado"] < 0:
        alertas.append(
            {
                "nivel": "perigo",
                "tipo": "saldo",
                "titulo": "Projeção negativa para o mês",
                "texto": (
                    f"Considerando o que já entrou/saiu e o que está previsto, "
                    f"sobram {resumo['saldo_projetado_fmt']}."
                ),
            }
        )
    if resumo["entradas_previstas"] > 0:
        alertas.append(
            {
                "nivel": "info",
                "tipo": "receber",
                "titulo": f"{resumo['entradas_previstas_fmt']} a receber",
                "texto": "Marque como recebido quando o dinheiro cair na conta.",
            }
        )
    if resumo["saidas_previstas"] > 0:
        alertas.append(
            {
                "nivel": "info",
                "tipo": "pagar",
                "titulo": f"{resumo['saidas_previstas_fmt']} a pagar",
                "texto": "Contas lançadas como previstas neste mês.",
            }
        )
    ordem = {"perigo": 0, "atencao": 1, "info": 2}
    alertas.sort(key=lambda a: ordem.get(a["nivel"], 3))
    return alertas


def month_summary(conn: sqlite3.Connection, period: str | None = None, ref: date | None = None) -> dict[str, Any]:
    """Resumo completo de um mês — é o que alimenta o painel."""
    periodo = period or current_period()
    referencia = ref or today()
    total_dias = days_in_month(periodo)

    if period_of(referencia) == periodo:
        dias_corridos = referencia.day
    elif referencia > date.fromisoformat(f"{periodo}-01"):
        dias_corridos = total_dias
    else:
        dias_corridos = 0
    dias_restantes = max(0, total_dias - dias_corridos)

    t = totals(conn, periodo)
    ciclo = get_cycle(conn, periodo)
    salario_previsto = int(ciclo["expected_income_centavos"] or 0)

    base_receita = salario_previsto or t["entradas_realizadas"] or t["entradas"]
    comprometido = percent(t["saidas_realizadas"], base_receita)
    media_diaria = (t["saidas_realizadas"] // dias_corridos) if dias_corridos else 0
    saldo_disponivel = max(0, t["saldo_projetado"])
    sugestao_diaria = (saldo_disponivel // dias_restantes) if dias_restantes else saldo_disponivel

    categorias = category_breakdown(conn, periodo, "saida")
    anterior = previous_period(periodo)
    totais_anteriores = totals(conn, anterior)

    resumo: dict[str, Any] = {
        "period": periodo,
        "label": period_label(periodo),
        "anterior": anterior,
        "anterior_label": period_label(anterior),
        "total_dias": total_dias,
        "dias_corridos": dias_corridos,
        "dias_restantes": dias_restantes,
        "pct_mes_decorrido": percent(dias_corridos, total_dias),
        "hoje": referencia.isoformat(),
        "hoje_fmt": format_date(referencia),
        "ciclo": ciclo,
        "salario_previsto": salario_previsto,
        "salario_previsto_fmt": format_brl(salario_previsto),
        "payday_day": ciclo.get("payday_day"),
        "receber_total": salario_previsto + t["entradas_previstas"],
        "receber_total_fmt": format_brl(salario_previsto + t["entradas_previstas"]),
        **{k: v for k, v in t.items()},
        **{f"{k}_fmt": format_brl(v, sinal=(k.startswith("saldo"))) for k, v in t.items()},
        "comprometido_pct": comprometido,
        "comprometido_pct_fmt": format_percent(comprometido, sinal=False),
        "media_diaria_gasto": media_diaria,
        "media_diaria_gasto_fmt": format_brl(media_diaria),
        "sugestao_gasto_diario": sugestao_diaria,
        "sugestao_gasto_diario_fmt": format_brl(sugestao_diaria),
        "categorias": categorias,
        "categorias_fmt": categorias,
        "orcamento": budget_summary(conn, periodo),
        "metodos": method_breakdown(conn, periodo, "saida"),
        "top_itens": top_items(conn, periodo),
        "fixos_variaveis": fixed_vs_variable(conn, periodo),
        "total_lancamentos": count_transactions(conn, period=periodo),
        "delta_vs_anterior": {
            "entradas": t["entradas_realizadas"] - totais_anteriores["entradas_realizadas"],
            "saidas": t["saidas_realizadas"] - totais_anteriores["saidas_realizadas"],
            "entradas_pct": percent(
                t["entradas_realizadas"] - totais_anteriores["entradas_realizadas"],
                totais_anteriores["entradas_realizadas"],
            ),
            "saidas_pct": percent(
                t["saidas_realizadas"] - totais_anteriores["saidas_realizadas"],
                totais_anteriores["saidas_realizadas"],
            ),
        },
    }
    resumo["delta_vs_anterior"]["entradas_fmt"] = format_brl(resumo["delta_vs_anterior"]["entradas"], sinal=True)
    resumo["delta_vs_anterior"]["saidas_fmt"] = format_brl(resumo["delta_vs_anterior"]["saidas"], sinal=True)
    resumo["delta_vs_anterior"]["entradas_pct_fmt"] = format_percent(resumo["delta_vs_anterior"]["entradas_pct"])
    resumo["delta_vs_anterior"]["saidas_pct_fmt"] = format_percent(resumo["delta_vs_anterior"]["saidas_pct"])
    resumo["alertas"] = build_alerts(conn, periodo, resumo)
    resumo["ultimos"] = list_transactions(conn, period=periodo, limit=8)
    resumo["serie"] = series(conn, periodo, 6)
    return resumo


def daily_breakdown(conn: sqlite3.Connection, period: str) -> list[dict[str, Any]]:
    """Totais por dia do mês (usado no gráfico de linha e na tabela diária)."""
    rows = conn.execute(
        """
        SELECT occurred_on,
               SUM(CASE WHEN type='entrada' AND status='realizado' THEN amount_centavos ELSE 0 END) AS entradas,
               SUM(CASE WHEN type='saida'   AND status='realizado' THEN amount_centavos ELSE 0 END) AS saidas,
               COUNT(*) AS qtd
        FROM transactions WHERE period = ? GROUP BY occurred_on ORDER BY occurred_on
        """,
        (period,),
    ).fetchall()
    return [
        {
            "date": r["occurred_on"],
            "date_fmt": format_date(r["occurred_on"]),
            "entradas": int(r["entradas"] or 0),
            "saidas": int(r["saidas"] or 0),
            "saldo": int(r["entradas"] or 0) - int(r["saidas"] or 0),
            "entradas_fmt": format_brl(r["entradas"]),
            "saidas_fmt": format_brl(r["saidas"]),
            "saldo_fmt": format_brl(int(r["entradas"] or 0) - int(r["saidas"] or 0), sinal=True),
            "qtd": r["qtd"],
        }
        for r in rows
    ]


def _identidade_conta(descricao: Any, categoria_id: Any) -> tuple[str, int | None]:
    """Identidade de uma conta, usada para saber se ela já está no mês.

    Descrição normalizada + categoria — **sem o valor**: se o aluguel subiu de
    R$ 1.200 para R$ 1.250 e você já lançou o novo, a cópia automática não pode
    criar um segundo "Aluguel" só porque o número é diferente.
    """
    return (normalize(descricao or ""), int(categoria_id) if categoria_id else None)


def next_recurring(conn: sqlite3.Connection, period: str) -> list[dict[str, Any]]:
    """Lançamentos recorrentes do mês anterior que ainda não existem no mês atual.

    Base tanto do botão "repetir gastos fixos" quanto da geração automática.

    A regra de ouro é **nunca duplicar**: se o mês de destino já tem um
    lançamento com a mesma identidade (descrição normalizada + categoria),
    o fixo é considerado lançado — mesmo que o valor tenha mudado (o aluguel
    subiu, a mensalidade foi reajustada) e mesmo que você o tenha digitado à
    mão em vez de marcá-lo como fixo.
    """
    anterior = previous_period(period)
    existentes = {
        _identidade_conta(r["description"], r["category_id"])
        for r in conn.execute(
            "SELECT description, category_id FROM transactions WHERE period = ?", (period,)
        )
    }
    sugestoes = []
    for r in conn.execute(
        TX_SELECT + " WHERE t.period = ? AND t.recurring = 1 AND t.type = 'saida' "
        "ORDER BY t.amount_centavos DESC",
        (anterior,),
    ):
        chave = _identidade_conta(r["description"], r["category_id"])
        if chave in existentes:
            continue
        existentes.add(chave)
        sugestoes.append(decorate_transaction(dict(r)))
    return sugestoes


def duplicate_recurring(conn: sqlite3.Connection, period: str) -> int:
    """Copia os gastos fixos do mês anterior como *previstos* no mês informado.

    É a versão **manual** (botão "Repetir gastos fixos"): funciona para qualquer
    mês, inclusive passados e futuros.
    """
    return len(_copy_recurring(conn, period, source=f"recorrente:{period}"))


def _copy_recurring(conn: sqlite3.Connection, period: str, source: str) -> list[dict[str, Any]]:
    """Cria, no mês ``period``, um previsto para cada fixo do mês anterior.

    Idempotente: ``next_recurring`` já descarta o que existe no mês de destino.
    Retorna os lançamentos criados (decorados).
    """
    origem = period_label(previous_period(period))
    criados = []
    for tx in next_recurring(conn, period):
        dia = min(int(tx["occurred_on"][8:10]), days_in_month(period))
        criados.append(
            create_transaction(
                conn,
                {
                    "type": tx["type"],
                    "status": "previsto",
                    "occurred_on": f"{period}-{dia:02d}",
                    "amount_centavos": tx["amount_centavos"],
                    "description": tx["description"],
                    "category_id": tx["category_id"],
                    "item_id": tx["item_id"],
                    "method": tx["method"],
                    "recurring": 1,
                    "source": source,
                    "note": f"Copiado de {origem}",
                },
            )
        )
    conn.commit()
    return criados


def auto_generate_recurring(
    conn: sqlite3.Connection, period: str | None = None, force: bool = False
) -> dict[str, Any]:
    """Gera sozinha os gastos fixos do mês em curso, como *previsto*.

    Chamada ao abrir o painel/a lista de lançamentos. Diferenças em relação ao
    botão manual (``duplicate_recurring``):

    * só atua no **mês atual** — nunca reescreve meses fechados nem cria
      previsões para meses que ainda não começaram;
    * respeita a preferência ``auto_recurring`` (Configurações), a menos que
      ``force=True``;
    * marca os lançamentos com ``source='recorrente-auto'``, o que permite
      desfazer a geração em bloco (``undo_auto_generated``).

    É idempotente: chamar duas vezes no mesmo mês não duplica nada.
    """
    periodo = period or current_period()
    resultado: dict[str, Any] = {"period": periodo, "criados": 0, "lancamentos": [], "motivo": None}

    if periodo != current_period():
        resultado["motivo"] = "fora_do_mes_atual"
        return resultado
    if not force and not settings.is_auto_recurring(conn):
        resultado["motivo"] = "desativado"
        return resultado

    criados = _copy_recurring(conn, periodo, source=SOURCE_AUTO_RECORRENTE)
    resultado["criados"] = len(criados)
    resultado["lancamentos"] = criados
    resultado["motivo"] = None if criados else "nada_novo"
    return resultado


def count_auto_generated(conn: sqlite3.Connection, period: str) -> int:
    """Quantos fixos do mês foram criados pela geração automática."""
    return conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE period = ? AND source = ?",
        (period, SOURCE_AUTO_RECORRENTE),
    ).fetchone()[0]


def undo_auto_generated(conn: sqlite3.Connection, period: str) -> int:
    """Desfaz a geração automática do mês (remove só o que ela criou)."""
    cur = conn.execute(
        "DELETE FROM transactions WHERE period = ? AND source = ?",
        (period, SOURCE_AUTO_RECORRENTE),
    )
    conn.commit()
    return cur.rowcount


def stats_gerais(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT COUNT(*) AS lancamentos,
               MIN(occurred_on) AS primeiro,
               MAX(occurred_on) AS ultimo,
               COUNT(DISTINCT period) AS meses,
               COUNT(DISTINCT category_id) AS categorias,
               COALESCE((SELECT COUNT(*) FROM items), 0) AS itens,
               COALESCE((SELECT COUNT(*) FROM import_batches), 0) AS importacoes
        FROM transactions
        """
    ).fetchone()
    return dict(row) if row else {}


def delete_import(conn: sqlite3.Connection, import_id: int) -> int:
    """Desfaz uma importação inteira (remove os lançamentos daquele lote)."""
    cur = conn.execute("DELETE FROM transactions WHERE import_id = ?", (import_id,))
    conn.execute("DELETE FROM import_batches WHERE id = ?", (import_id,))
    return cur.rowcount


def list_imports(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM import_batches ORDER BY imported_at DESC")]


def methods_in_use(conn: sqlite3.Connection) -> list[str]:
    padroes = list(config.DEFAULT_METHODS)
    usados = [
        r["method"]
        for r in conn.execute(
            "SELECT DISTINCT method FROM transactions WHERE method IS NOT NULL AND method != '' ORDER BY method"
        )
    ]
    vistos: set[str] = set()
    ordem: list[str] = []
    for m in padroes + usados:
        if m and m not in vistos:
            vistos.add(m)
            ordem.append(m)
    return ordem


def all_categories_map(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        normalize(r["name"]): int(r["id"])
        for r in conn.execute("SELECT id, name FROM categories")
    }


def bulk_create(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]], create_item: bool = True) -> list[int]:
    ids: list[int] = []
    for row in rows:
        ids.append(int(create_transaction(conn, row, create_item=create_item)["id"]))
    return ids


def validate_periods(periods: Sequence[str]) -> list[str]:
    return [p for p in periods if p]
