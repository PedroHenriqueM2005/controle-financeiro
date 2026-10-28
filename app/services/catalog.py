"""Catálogo de itens.

É o que permite ao sistema "reconhecer" gastos repetidos: ao lançar uma despesa
o usuário digita o nome do item e recebe sugestões do histórico (com preço médio
e última compra). Itens novos podem ser criados no próprio lançamento, formando
uma base que alimenta os comparativos de preço entre meses.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..money import format_brl, format_centavos, format_percent, percent
from ..utils import normalize, truncate

# variação de preço considerada "alerta"
PRICE_ALERT_THRESHOLD = 10.0

_ITEM_STATS_SQL = """
SELECT
    i.id,
    i.name,
    i.unit,
    i.note,
    i.created_at,
    c.name  AS category_name,
    c.color AS category_color,
    c.id    AS category_id,
    COALESCE(s.compras, 0)        AS compras,
    COALESCE(s.total, 0)          AS total_centavos,
    COALESCE(s.preco_medio, 0)    AS preco_medio,
    COALESCE(s.preco_min, 0)      AS preco_min,
    COALESCE(s.preco_max, 0)      AS preco_max,
    s.ultima_data                 AS ultima_data,
    (SELECT t2.amount_centavos FROM transactions t2
      WHERE t2.item_id = i.id AND t2.type = 'saida'
      ORDER BY t2.occurred_on DESC, t2.id DESC LIMIT 1) AS ultimo_preco,
    COALESCE(m.compras_mes, 0)    AS compras_mes,
    COALESCE(m.total_mes, 0)      AS total_mes
FROM items i
LEFT JOIN categories c ON c.id = i.category_id
LEFT JOIN (
    SELECT item_id,
           COUNT(*)             AS compras,
           SUM(amount_centavos) AS total,
           AVG(amount_centavos) AS preco_medio,
           MIN(amount_centavos) AS preco_min,
           MAX(amount_centavos) AS preco_max,
           MAX(occurred_on)     AS ultima_data
    FROM transactions
    WHERE item_id IS NOT NULL AND type = 'saida'
    GROUP BY item_id
) s ON s.item_id = i.id
LEFT JOIN (
    SELECT item_id,
           COUNT(*)             AS compras_mes,
           SUM(amount_centavos) AS total_mes
    FROM transactions
    WHERE item_id IS NOT NULL AND type = 'saida' AND period = ?
    GROUP BY item_id
) m ON m.item_id = i.id
"""


def ensure_item(
    conn: sqlite3.Connection,
    name: str | None,
    category_id: int | None = None,
    unit: str | None = None,
    note: str | None = None,
    create: bool = True,
) -> int | None:
    """Retorna o ``id`` do item com esse nome, criando-o se necessário.

    O casamento é feito pelo nome normalizado (sem acento, minúsculo), então
    "Café 500g", "cafe 500g" e "CAFÉ 500G" são o mesmo item.
    """
    nome = (name or "").strip()
    if not nome:
        return None
    chave = normalize(nome)

    row = conn.execute("SELECT id FROM items WHERE normalized_name = ?", (chave,)).fetchone()
    if row:
        if category_id and conn.execute(
            "SELECT 1 FROM items WHERE id = ? AND (category_id IS NULL OR category_id != ?)",
            (row["id"], category_id),
        ).fetchone():
            conn.execute("UPDATE items SET category_id = ? WHERE id = ?", (category_id, row["id"]))
        return int(row["id"])

    if not create:
        return None

    cur = conn.execute(
        "INSERT INTO items (name, normalized_name, category_id, unit, note) VALUES (?, ?, ?, ?, ?)",
        (nome, chave, category_id, (unit or None), (note or None)),
    )
    return int(cur.lastrowid)


def create_item(
    conn: sqlite3.Connection,
    name: str,
    category_id: int | None = None,
    unit: str | None = None,
    note: str | None = None,
) -> int:
    item_id = ensure_item(conn, name, category_id, unit, note, create=True)
    assert item_id is not None
    return item_id


def get_item(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    row = conn.execute(_ITEM_STATS_SQL + " WHERE i.id = ?", ("", item_id)).fetchone()
    return _decorate(dict(row)) if row else None


def list_items(
    conn: sqlite3.Connection,
    search: str | None = None,
    category_id: int | None = None,
    period: str | None = None,
    only_used: bool = False,
    limit: int = 500,
) -> list[dict[str, Any]]:
    periodo = period or ""
    sql = _ITEM_STATS_SQL + " WHERE 1=1"
    params: list[Any] = [periodo]
    if search:
        sql += " AND i.normalized_name LIKE ?"
        params.append(f"%{normalize(search)}%")
    if category_id:
        sql += " AND i.category_id = ?"
        params.append(category_id)
    if only_used:
        sql += " AND COALESCE(s.compras, 0) > 0"
    sql += " ORDER BY COALESCE(s.compras,0) DESC, COALESCE(s.ultima_data,'') DESC, i.name LIMIT ?"
    params.append(limit)
    return [_decorate(dict(r)) for r in conn.execute(sql, tuple(params)).fetchall()]


def suggest(conn: sqlite3.Connection, search: str, limit: int = 8) -> list[dict[str, Any]]:
    """Autocomplete: itens por nome + descrição de lançamentos antigos.

    Ordena por frequência de uso, depois por recência — o item que você compra
    toda semana aparece primeiro.
    """
    texto = (search or "").strip()
    if len(texto) < 1:
        return []
    chave = normalize(texto)
    like = f"%{chave}%"

    rows = conn.execute(
        """
        SELECT i.id, i.name, i.unit, c.id AS category_id, c.name AS category_name,
               c.color AS category_color, COUNT(t.id) AS compras,
               AVG(t.amount_centavos) AS preco_medio,
               MAX(t.occurred_on) AS ultima_data
        FROM items i
        LEFT JOIN categories c ON c.id = i.category_id
        LEFT JOIN transactions t ON t.item_id = i.id AND t.type = 'saida'
        WHERE i.normalized_name LIKE ?
        GROUP BY i.id
        ORDER BY compras DESC, ultima_data DESC, i.name
        LIMIT ?
        """,
        (like, limit),
    ).fetchall()

    sugestoes = [
        {
            "id": r["id"],
            "name": r["name"],
            "unit": r["unit"],
            "category_id": r["category_id"],
            "category_name": r["category_name"],
            "category_color": r["category_color"],
            "compras": r["compras"],
            "preco_medio": int(r["preco_medio"] or 0),
            "preco_medio_fmt": format_brl(int(r["preco_medio"] or 0)) if r["compras"] else None,
            "ultima_data": r["ultima_data"],
            "origem": "catalogo",
        }
        for r in rows
    ]

    # se o catálogo não conhece, oferecemos descrições já lançadas
    if len(sugestoes) < limit:
        vistos = {s["name"].lower() for s in sugestoes}
        extras = conn.execute(
            """
            SELECT description, COUNT(*) AS vezes, AVG(amount_centavos) AS preco_medio,
                   MAX(occurred_on) AS ultima_data
            FROM transactions
            WHERE type = 'saida' AND description != ''
            GROUP BY LOWER(description)
            HAVING vezes >= 1
            ORDER BY vezes DESC, ultima_data DESC
            LIMIT ?
            """,
            (limit * 6,),
        ).fetchall()
        for e in extras:
            nome = e["description"].strip()
            if nome.lower() in vistos or chave not in normalize(nome):
                continue
            vistos.add(nome.lower())
            sugestoes.append(
                {
                    "id": None,
                    "name": nome,
                    "unit": None,
                    "category_id": None,
                    "category_name": None,
                    "category_color": None,
                    "compras": e["vezes"],
                    "preco_medio": int(e["preco_medio"] or 0),
                    "preco_medio_fmt": format_brl(int(e["preco_medio"] or 0)),
                    "ultima_data": e["ultima_data"],
                    "origem": "historico",
                }
            )
            if len(sugestoes) >= limit:
                break
    return sugestoes


def _decorate(row: dict[str, Any]) -> dict[str, Any]:
    """Adiciona campos derivados (variação de preço, formatação) a um item."""
    preco_medio = int(row.get("preco_medio") or 0)
    ultimo = row.get("ultimo_preco")
    ultimo = int(ultimo) if ultimo else 0

    variacao = None
    if ultimo and preco_medio and row.get("compras", 0) >= 2:
        variacao = percent(ultimo - preco_medio, preco_medio)

    row.update(
        {
            "preco_medio": preco_medio,
            "preco_medio_fmt": format_brl(preco_medio) if row.get("compras") else None,
            "total_fmt": format_brl(row.get("total_centavos")),
            "total_mes_fmt": format_brl(row.get("total_mes")),
            "ultimo_preco_fmt": format_brl(ultimo) if ultimo else None,
            "preco_min_fmt": format_brl(row.get("preco_min")) if row.get("compras") else None,
            "preco_max_fmt": format_brl(row.get("preco_max")) if row.get("compras") else None,
            "variacao_pct": variacao,
            "variacao_fmt": format_percent(variacao),
            "alerta_preco": bool(variacao is not None and variacao >= PRICE_ALERT_THRESHOLD),
        }
    )
    return row


def price_variation(conn: sqlite3.Connection, item_id: int | None, amount: int) -> dict[str, Any]:
    """Compara o preço informado com a média histórica do item.

    Usado no formulário de lançamento para avisar, na hora, que o produto está
    mais caro do que de costume.
    """
    if not item_id:
        return {"tem_historico": False}
    row = conn.execute(
        """
        SELECT COUNT(*) AS compras, AVG(amount_centavos) AS media, MAX(occurred_on) AS ultima
        FROM transactions WHERE item_id = ? AND type = 'saida'
        """,
        (item_id,),
    ).fetchone()
    compras = row["compras"] if row else 0
    if not compras:
        return {"tem_historico": False, "compras": 0}
    media = int(row["media"] or 0)
    variacao = percent(amount - media, media)
    return {
        "tem_historico": True,
        "compras": compras,
        "media": media,
        "media_fmt": format_brl(media),
        "diferenca": amount - media,
        "diferenca_fmt": format_brl(amount - media, sinal=True),
        "variacao_pct": variacao,
        "variacao_fmt": format_percent(variacao),
        "alerta": bool(variacao is not None and abs(variacao) >= PRICE_ALERT_THRESHOLD),
        "ultima_compra": row["ultima"],
    }


def price_alerts(conn: sqlite3.Connection, period: str) -> list[dict[str, Any]]:
    """Itens cujo preço médio no mês subiu frente ao histórico anterior."""
    rows = conn.execute(
        """
        WITH mes AS (
            SELECT item_id, AVG(amount_centavos) AS media_mes, COUNT(*) AS qtd_mes,
                   SUM(amount_centavos) AS total_mes
            FROM transactions
            WHERE type = 'saida' AND item_id IS NOT NULL AND period = ?
            GROUP BY item_id
        ),
        antes AS (
            SELECT item_id, AVG(amount_centavos) AS media_antes, COUNT(*) AS qtd_antes
            FROM transactions
            WHERE type = 'saida' AND item_id IS NOT NULL AND period < ?
            GROUP BY item_id
        )
        SELECT i.name, i.id AS item_id, mes.media_mes, mes.qtd_mes, mes.total_mes,
               antes.media_antes, antes.qtd_antes
        FROM mes
        JOIN antes ON antes.item_id = mes.item_id
        JOIN items i ON i.id = mes.item_id
        """,
        (period, period),
    ).fetchall()

    alertas = []
    for r in rows:
        media_mes = int(r["media_mes"] or 0)
        media_antes = int(r["media_antes"] or 0)
        if not media_antes:
            continue
        variacao = percent(media_mes - media_antes, media_antes)
        if variacao is None or abs(variacao) < PRICE_ALERT_THRESHOLD:
            continue
        alertas.append(
            {
                "item_id": r["item_id"],
                "name": r["name"],
                "qtd_mes": r["qtd_mes"],
                "total_mes": r["total_mes"],
                "total_mes_fmt": format_brl(r["total_mes"]),
                "media_mes": media_mes,
                "media_mes_fmt": format_brl(media_mes),
                "media_antes": media_antes,
                "media_antes_fmt": format_brl(media_antes),
                "variacao_pct": variacao,
                "variacao_fmt": format_percent(variacao),
                "subiu": media_mes > media_antes,
            }
        )
    alertas.sort(key=lambda a: -abs(a["variacao_pct"] or 0))
    return alertas


def merge_items(conn: sqlite3.Connection, source_id: int, target_id: int) -> int:
    """Junta dois itens duplicados, movendo os lançamentos."""
    if source_id == target_id:
        return 0
    cur = conn.execute("UPDATE transactions SET item_id = ? WHERE item_id = ?", (target_id, source_id))
    movidos = cur.rowcount
    conn.execute("DELETE FROM items WHERE id = ?", (source_id,))
    return movidos


def rename_item(conn: sqlite3.Connection, item_id: int, name: str) -> None:
    conn.execute(
        "UPDATE items SET name = ?, normalized_name = ? WHERE id = ?",
        (name.strip(), normalize(name), item_id),
    )


def delete_item(conn: sqlite3.Connection, item_id: int) -> None:
    """Remove do catálogo mas preserva os lançamentos (``item_id`` vai a NULL)."""
    conn.execute("DELETE FROM items WHERE id = ?", (item_id,))


def describe_item(name: str | None, unit: str | None = None) -> str:
    return truncate(name, 40) + (f" ({unit})" if unit else "") or "—"


def format_price_range(item: dict[str, Any]) -> str:
    if not item.get("compras"):
        return "sem histórico"
    if item.get("preco_min") == item.get("preco_max"):
        return format_centavos(item["preco_min"])
    return f"{format_centavos(item['preco_min'])} – {format_centavos(item['preco_max'])}"
