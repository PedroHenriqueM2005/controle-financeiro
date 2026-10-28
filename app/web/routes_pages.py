"""Rotas que renderizam as páginas HTML."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import config
from ..deps import get_db
from ..money import format_brl
from ..services import catalog, charts, compare, importer, ledger
from ..utils import current_period, is_valid_period, period_label, previous_period, shift_period

router = APIRouter(tags=["Páginas"])

NAV = [
    ("painel", "/", "Painel"),
    ("lancamentos", "/lancamentos", "Lançamentos"),
    ("itens", "/itens", "Itens"),
    ("relatorios", "/relatorios", "Relatórios"),
    ("importar", "/importar", "Importar planilha"),
    ("configuracoes", "/configuracoes", "Configurações"),
]


def render(request: Request, template: str, **contexto: Any) -> HTMLResponse:
    """Renderiza com o contexto comum (navegação, período, mensagens flash)."""
    templates = request.app.state.templates
    periodo = contexto.get("period") or current_period()
    base: dict[str, Any] = {
        "request": request,
        "nav": NAV,
        "active": template.split(".")[0],
        "period": periodo,
        "period_label": period_label(periodo),
        "current_period": current_period(),
        "periodos": [],
        "msg": request.query_params.get("msg"),
        "erro": request.query_params.get("erro"),
        "methods": config.DEFAULT_METHODS,
    }
    base.update(contexto)
    return templates.TemplateResponse(request, template, base)


def _periodo_ou_atual(period: str | None) -> str:
    return period if (period and is_valid_period(period)) else current_period()


# ------------------------------------------------------------------ painel

@router.get("/", response_class=HTMLResponse)
def painel(
    request: Request,
    period: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> HTMLResponse:
    periodo = _periodo_ou_atual(period)
    resumo = ledger.month_summary(conn, periodo)
    serie = [{**p, "label": p["period"][5:7] + "/" + p["period"][2:4]} for p in resumo["serie"]]

    contexto = {
        "period": periodo,
        "periodos": ledger.available_periods(conn),
        "resumo": resumo,
        "categorias_saida": ledger.list_categories(conn, kind="saida"),
        "categorias_entrada": ledger.list_categories(conn, kind="entrada"),
        "methods": ledger.methods_in_use(conn),
        "anterior": previous_period(periodo),
        "proximo": shift_period(periodo, 1),
        "grafico_serie": charts.bars_series(serie, title="Entradas × saídas — últimos 6 meses"),
        "grafico_categorias": charts.hbar(resumo["categorias"], title="Onde o dinheiro foi parar neste mês"),
        "grafico_donut": charts.donut(
            resumo["categorias"], center_label="gasto", center_value=format_brl(resumo["saidas_realizadas"])
        ),
        "alertas_preco": catalog.price_alerts(conn, periodo),
        "recorrentes_pendentes": ledger.next_recurring(conn, periodo),
    }
    return render(request, "dashboard.html", **contexto)


# ------------------------------------------------------------------ lançamentos

@router.get("/lancamentos", response_class=HTMLResponse)
def lancamentos(
    request: Request,
    period: str | None = None,
    type: str | None = None,
    status: str | None = None,
    category_id: int | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    conn: sqlite3.Connection = Depends(get_db),
) -> HTMLResponse:
    periodo = _periodo_ou_atual(period) if period else None
    filtros = dict(period=periodo, tx_type=type, status=status, category_id=category_id, search=q)
    total = ledger.count_transactions(conn, **filtros)
    page_size = config.PAGE_SIZE
    paginas = max(1, (total + page_size - 1) // page_size)
    page = min(page, paginas)
    itens = ledger.list_transactions(conn, limit=page_size, offset=(page - 1) * page_size, **filtros)

    totais = ledger.totals(conn, periodo) if periodo else None
    contexto = {
        "period": periodo or current_period(),
        "periodos": ledger.available_periods(conn),
        "lancamentos": itens,
        "total": total,
        "page": page,
        "pages": paginas,
        "filtros": {"type": type, "status": status, "category_id": category_id, "q": q},
        "filtro_period_label": period_label(periodo) if periodo else None,
        "categorias_saida": ledger.list_categories(conn, kind="saida"),
        "categorias_entrada": ledger.list_categories(conn, kind="entrada"),
        "methods": ledger.methods_in_use(conn),
        "totais": totais,
    }
    return render(request, "lancamentos.html", **contexto)


# ------------------------------------------------------------------ itens

@router.get("/itens", response_class=HTMLResponse)
def itens(
    request: Request,
    q: str | None = None,
    category_id: int | None = None,
    period: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> HTMLResponse:
    periodo = _periodo_ou_atual(period)
    lista = catalog.list_items(conn, search=q, category_id=category_id, period=periodo, limit=1000)
    contexto = {
        "period": periodo,
        "periodos": ledger.available_periods(conn),
        "itens": lista,
        "q": q or "",
        "category_id": category_id,
        "categorias_saida": ledger.list_categories(conn, kind="saida"),
        "alertas_preco": catalog.price_alerts(conn, periodo),
        "total_itens": len(lista),
        "usados": sum(1 for i in lista if i["compras"]),
        "catalogo_fmt": format_brl(sum(i["total_centavos"] for i in lista)),
    }
    return render(request, "itens.html", **contexto)


# ------------------------------------------------------------------ relatórios

@router.get("/relatorios", response_class=HTMLResponse)
def relatorios(
    request: Request,
    a: str | None = None,
    b: str | None = None,
    months: int = Query(12, ge=3, le=36),
    conn: sqlite3.Connection = Depends(get_db),
) -> HTMLResponse:
    mes_a = _periodo_ou_atual(a)
    mes_b = _periodo_ou_atual(b) if b else previous_period(mes_a)
    comparativo = compare.compare(conn, mes_a, mes_b)
    matriz = compare.comparison_table(conn, months=months, end_period=mes_a)
    acumulado = compare.accumulated(conn, mes_a, months)
    destaques = compare.best_and_worst(conn, months, end_period=mes_a)
    anual = compare.year_over_year(conn, mes_a)

    contexto = {
        "period": mes_a,
        "periodos": ledger.available_periods(conn),
        "mes_a": mes_a,
        "mes_b": mes_b,
        "meses": months,
        "comparativo": comparativo,
        "matriz": matriz,
        "acumulado": acumulado,
        "destaques": destaques,
        "anual": anual,
        "tem_dados": bool(matriz["linhas"]),
        "grafico_serie": charts.bars_series(
            [
                {
                    "period": c["period"],
                    "label": c["label"],
                    "entradas": matriz["totais"][c["period"]]["entradas_realizadas"],
                    "saidas": matriz["totais"][c["period"]]["saidas_realizadas"],
                    "saldo": matriz["totais"][c["period"]]["saldo_real"],
                    "vazio": matriz["totais"][c["period"]]["qtd"] == 0,
                }
                for c in matriz["cabecalho"]
            ],
            width=900,
            title=f"Entradas × saídas — últimos {months} meses",
        ),
        "grafico_acumulado": charts.line_chart(acumulado["pontos"], width=900, title="Saldo acumulado"),
        "grafico_variacoes": charts.hbar(
            [
                {
                    "name": c["name"],
                    "total": abs(c["delta"]),
                    "color": "#ef4444" if c["delta"] > 0 else "#22c55e",
                }
                for c in comparativo["categorias"]
            ],
            title="Maiores variações por categoria",
            value_key="total",
        ),
    }
    return render(request, "relatorios.html", **contexto)


# ------------------------------------------------------------------ importação

@router.get("/importar", response_class=HTMLResponse)
def importar(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> HTMLResponse:
    contexto = {
        "period": current_period(),
        "periodos": ledger.available_periods(conn),
        "importacoes": ledger.list_imports(conn),
        "categorias_saida": ledger.list_categories(conn, kind="saida"),
        "categorias_entrada": ledger.list_categories(conn, kind="entrada"),
        "max_mb": round(config.MAX_UPLOAD_BYTES / 1024 / 1024),
        "campos": importer.FIELD_LABELS,
    }
    return render(request, "importar.html", **contexto)


# ------------------------------------------------------------------ configurações

@router.get("/configuracoes", response_class=HTMLResponse)
def configuracoes(request: Request, period: str | None = None, conn: sqlite3.Connection = Depends(get_db)) -> HTMLResponse:
    periodo = _periodo_ou_atual(period)
    contexto = {
        "period": periodo,
        "periodos": ledger.available_periods(conn),
        "ciclo": ledger.get_cycle(conn, periodo),
        "ciclos": ledger.list_cycles(conn, limit=18),
        "categorias_saida": ledger.list_categories(conn, kind="saida", period=periodo),
        "categorias_entrada": ledger.list_categories(conn, kind="entrada", period=periodo),
        "stats": ledger.stats_gerais(conn),
        "methods": ledger.methods_in_use(conn),
        "anterior": previous_period(periodo),
        "proximo": shift_period(periodo, 1),
    }
    return render(request, "configuracoes.html", **contexto)


# ------------------------------------------------------------------ utilidades

@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> RedirectResponse:
    return RedirectResponse("/static/favicon.svg")
