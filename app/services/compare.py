"""Comparativos entre meses.

Aqui mora a parte de "comparar com tabelas/planilhas passadas": como as
planilhas importadas viram lançamentos normais (com ``period``), a comparação é
sempre mês × mês — não importa se o dado veio do formulário ou de um XLSX de
2023.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..money import delta, format_brl, format_percent, percent
from ..utils import (
    current_period,
    normalize,
    period_label,
    period_short,
    previous_period,
    same_period_last_year,
    shift_period,
    truncate,
)
from . import ledger


def periods_with_data(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT period FROM transactions GROUP BY period
        UNION SELECT period FROM cycles WHERE expected_income_centavos > 0
        ORDER BY period DESC
        """
    ).fetchall()
    return [r["period"] for r in rows]


def month_totals(conn: sqlite3.Connection, period: str) -> dict[str, Any]:
    """Totais de um mês + abertura por categoria, item e forma de pagamento."""
    t = ledger.totals(conn, period)
    por_categoria: dict[str, int] = {}
    for r in conn.execute(
        """
        SELECT COALESCE(c.name,'Sem categoria') AS name, SUM(t.amount_centavos) AS total
        FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
        WHERE t.period = ? AND t.type = 'saida'
        GROUP BY name
        """,
        (period,),
    ):
        por_categoria[r["name"]] = int(r["total"] or 0)

    por_item: dict[str, dict[str, Any]] = {}
    for r in conn.execute(
        """
        SELECT COALESCE(i.name, t.description) AS name,
               COUNT(*) AS qtd,
               SUM(t.amount_centavos) AS total,
               AVG(t.amount_centavos) AS preco_medio
        FROM transactions t LEFT JOIN items i ON i.id = t.item_id
        WHERE t.period = ? AND t.type = 'saida'
        GROUP BY name
        """,
        (period,),
    ):
        por_item[normalize(r["name"])] = {
            "name": r["name"],
            "qtd": int(r["qtd"]),
            "total": int(r["total"] or 0),
            "preco_medio": int(r["preco_medio"] or 0),
        }

    entradas_por_categoria: dict[str, int] = {}
    for r in conn.execute(
        """
        SELECT COALESCE(c.name,'Sem categoria') AS name, SUM(t.amount_centavos) AS total
        FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
        WHERE t.period = ? AND t.type = 'entrada'
        GROUP BY name
        """,
        (period,),
    ):
        entradas_por_categoria[r["name"]] = int(r["total"] or 0)

    t.update(
        {
            "period": period,
            "label": period_label(period),
            "short": period_short(period),
            "por_categoria": por_categoria,
            "entradas_por_categoria": entradas_por_categoria,
            "por_item": por_item,
            "metodos": {m["method"]: m["total"] for m in ledger.method_breakdown(conn, period, "saida")},
            "qtd": ledger.count_transactions(conn, period=period),
        }
    )
    return t


def _merge_rows(
    atual: dict[str, Any],
    anterior: dict[str, Any],
    chaves: list[str],
    rotulos: dict[str, str] | None = None,
    cores: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    linhas = []
    for chave in chaves:
        d = delta(atual.get(chave), anterior.get(chave))
        linhas.append(
            {
                "key": chave,
                "name": (rotulos or {}).get(chave, chave),
                "color": (cores or {}).get(chave),
                "atual_fmt": format_brl(d["atual"]),
                "anterior_fmt": format_brl(d["anterior"]),
                **d,
            }
        )
    linhas.sort(key=lambda l: (-abs(l["delta"]), l["name"]))
    return linhas


def compare(conn: sqlite3.Connection, atual: str, anterior: str | None = None) -> dict[str, Any]:
    """Comparação completa entre dois meses (padrão: mês atual × anterior)."""
    periodo_a = atual or current_period()
    periodo_b = anterior or previous_period(periodo_a)

    a = month_totals(conn, periodo_a)
    b = month_totals(conn, periodo_b)

    cores = {
        r["name"]: r["color"]
        for r in conn.execute("SELECT name, color FROM categories")
    }

    chaves_categoria = sorted({*a["por_categoria"], *b["por_categoria"]})
    chaves_item = sorted({*a["por_item"], *b["por_item"]})
    chaves_metodo = sorted({*a["metodos"], *b["metodos"]})
    chaves_entrada = sorted({*a["entradas_por_categoria"], *b["entradas_por_categoria"]})

    itens: list[dict[str, Any]] = []
    for chave in chaves_item:
        ia = a["por_item"].get(chave, {})
        ib = b["por_item"].get(chave, {})
        d = delta(ia.get("total"), ib.get("total"))
        preco = delta(ia.get("preco_medio"), ib.get("preco_medio"))
        itens.append(
            {
                "key": chave,
                "name": truncate(ia.get("name") or ib.get("name") or chave, 45),
                "qtd_atual": ia.get("qtd", 0),
                "qtd_anterior": ib.get("qtd", 0),
                "preco_medio_atual": ia.get("preco_medio", 0),
                "preco_medio_atual_fmt": format_brl(ia.get("preco_medio")) if ia else None,
                "preco_medio_anterior_fmt": format_brl(ib.get("preco_medio")) if ib else None,
                "preco_variacao_pct": preco["pct"],
                "preco_variacao_fmt": preco["pct_fmt"],
                "preco_subiu": preco["subiu"],
                **{k: v for k, v in d.items() if k != "pct"},
                "pct": d["pct"],
                "pct_fmt": d["pct_fmt"],
                "novo": d["novo"],
                "sumiu": bool(ib) and not ia,
            }
        )
    itens.sort(key=lambda i: (-abs(i["delta"]), i["name"]))

    maiores_altas = [i for i in itens if i["delta"] > 0][:5]
    maiores_quedas = sorted([i for i in itens if i["delta"] < 0], key=lambda i: i["delta"])[:5]

    resultado = {
        "atual": a,
        "anterior": b,
        "periodo_atual": periodo_a,
        "periodo_anterior": periodo_b,
        "rotulo_atual": a["label"],
        "rotulo_anterior": b["label"],
        "totais": {
            "entradas": delta(a["entradas_realizadas"], b["entradas_realizadas"]),
            "saidas": delta(a["saidas_realizadas"], b["saidas_realizadas"]),
            "saldo": delta(a["saldo_real"], b["saldo_real"]),
            "previsto": delta(a["saidas_previstas"], b["saidas_previstas"]),
        },
        "categorias": _merge_rows(a["por_categoria"], b["por_categoria"], chaves_categoria, None, cores),
        "entradas_categorias": _merge_rows(
            a["entradas_por_categoria"], b["entradas_por_categoria"], chaves_entrada, None, cores
        ),
        "itens": itens,
        "metodos": _merge_rows(a["metodos"], b["metodos"], chaves_metodo),
        "maiores_altas": maiores_altas,
        "maiores_quedas": maiores_quedas,
        "mesmo_mes_ano_anterior": same_period_last_year(periodo_a),
    }

    resumo_txt = []
    if resultado["totais"]["saidas"]["delta"] > 0:
        resumo_txt.append(
            f"você gastou {resultado['totais']['saidas']['delta_fmt']} a mais que em {b['label']}"
        )
    elif resultado["totais"]["saidas"]["delta"] < 0:
        resumo_txt.append(
            f"você economizou {format_brl(abs(resultado['totais']['saidas']['delta']))} frente a {b['label']}"
        )
    if resultado["totais"]["entradas"]["delta"] != 0:
        resumo_txt.append(
            f"entradas {resultado['totais']['entradas']['delta_fmt']} ({resultado['totais']['entradas']['pct_fmt']})"
        )
    resultado["resumo_texto"] = "; ".join(resumo_txt) or "sem variação relevante entre os meses"
    return resultado


def comparison_table(
    conn: sqlite3.Connection,
    periods: list[str] | None = None,
    months: int = 12,
    end_period: str | None = None,
) -> dict[str, Any]:
    """Matriz categorias × meses — a "planilha mestra" gerada pelo sistema.

    ``end_period`` ancora a janela (padrão: mês atual). Ao olhar um mês antigo,
    a tabela termina nele — senão os dados importados ficariam fora da janela.
    """
    fim = end_period or current_period()
    periodos = periods or [shift_period(fim, -i) for i in range(months - 1, -1, -1)]
    periodos = sorted({p for p in periodos if p})

    totais = {p: month_totals(conn, p) for p in periodos}
    chaves = sorted({c for p in periodos for c in totais[p]["por_categoria"]})
    cores = {r["name"]: r["color"] for r in conn.execute("SELECT name, color FROM categories")}

    linhas = []
    for chave in chaves:
        celulas = [{"period": p, "valor": totais[p]["por_categoria"].get(chave, 0)} for p in periodos]
        valores = [c["valor"] for c in celulas]
        linhas.append(
            {
                "name": chave,
                "color": cores.get(chave, "#94a3b8"),
                "celulas": [
                    {**c, "valor_fmt": format_brl(c["valor"]) if c["valor"] else "—"} for c in celulas
                ],
                "total": sum(valores),
                "total_fmt": format_brl(sum(valores)),
                "media": int(sum(valores) / len(valores)) if valores else 0,
                "media_fmt": format_brl(int(sum(valores) / len(valores)) if valores else 0),
                "maximo": max(valores) if valores else 0,
                "maximo_fmt": format_brl(max(valores)) if valores else 0,
            }
        )
    linhas.sort(key=lambda l: -l["total"])

    rodape = {
        "entradas": [{"period": p, "valor": totais[p]["entradas_realizadas"]} for p in periodos],
        "saidas": [{"period": p, "valor": totais[p]["saidas_realizadas"]} for p in periodos],
        "saldo": [{"period": p, "valor": totais[p]["saldo_real"]} for p in periodos],
    }
    for chave in rodape:
        for cel in rodape[chave]:
            cel["valor_fmt"] = format_brl(cel["valor"], sinal=(chave == "saldo"))

    return {
        "periodos": periodos,
        "cabecalho": [{"period": p, "label": period_short(p), "full": period_label(p)} for p in periodos],
        "linhas": linhas,
        "rodape": rodape,
        "totais": totais,
    }


def year_over_year(conn: sqlite3.Connection, period: str) -> dict[str, Any]:
    """Compara o mês com o mesmo mês do ano anterior."""
    return compare(conn, period, same_period_last_year(period))


def accumulated(conn: sqlite3.Connection, end_period: str | None = None, months: int = 12) -> dict[str, Any]:
    """Saldo acumulado mês a mês (evolução do patrimônio líquido do fluxo)."""
    fim = end_period or current_period()
    periodos = [shift_period(fim, -(months - 1 - i)) for i in range(months)]
    acumulado = 0
    pontos = []
    for p in periodos:
        t = ledger.totals(conn, p)
        acumulado += t["saldo_real"]
        pontos.append(
            {
                "period": p,
                "label": period_short(p),
                "saldo_mes": t["saldo_real"],
                "saldo_mes_fmt": format_brl(t["saldo_real"], sinal=True),
                "acumulado": acumulado,
                "acumulado_fmt": format_brl(acumulado),
            }
        )
    return {"pontos": pontos, "final": acumulado, "final_fmt": format_brl(acumulado)}


def best_and_worst(
    conn: sqlite3.Connection, months: int = 12, end_period: str | None = None
) -> dict[str, Any]:
    """Melhor e pior mês (por saldo) no período analisado — leitura rápida."""
    fim = end_period or current_period()
    periodos = [shift_period(fim, -i) for i in range(months)]
    dados = [(p, ledger.totals(conn, p)) for p in periodos]
    com_movimento = [(p, t) for p, t in dados if t["entradas"] or t["saidas"]]
    if not com_movimento:
        return {
            "melhor": None, "pior": None, "media_saldo": 0, "media_saldo_fmt": format_brl(0),
            "meses_analisados": 0, "taxa_poupanca": None, "taxa_poupanca_fmt": format_percent(None, sinal=False),
        }
    melhor = max(com_movimento, key=lambda x: x[1]["saldo_real"])
    pior = min(com_movimento, key=lambda x: x[1]["saldo_real"])
    media = int(sum(t["saldo_real"] for _, t in com_movimento) / len(com_movimento))
    return {
        "melhor": {"period": melhor[0], "label": period_label(melhor[0]), "saldo": melhor[1]["saldo_real"],
                   "saldo_fmt": format_brl(melhor[1]["saldo_real"], sinal=True)},
        "pior": {"period": pior[0], "label": period_label(pior[0]), "saldo": pior[1]["saldo_real"],
                 "saldo_fmt": format_brl(pior[1]["saldo_real"], sinal=True)},
        "media_saldo": media,
        "media_saldo_fmt": format_brl(media, sinal=True),
        "meses_analisados": len(com_movimento),
        "taxa_poupanca": percent(media, int(sum(t["entradas_realizadas"] for _, t in com_movimento) / len(com_movimento))),
        "taxa_poupanca_fmt": format_percent(
            percent(media, int(sum(t["entradas_realizadas"] for _, t in com_movimento) / len(com_movimento))),
            sinal=False,
        ),
    }
