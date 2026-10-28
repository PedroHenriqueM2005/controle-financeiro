"""API JSON — tudo que a interface web consome (e que você pode scriptar).

Documentação interativa em ``/api/docs``.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import config
from ..deps import get_db
from ..money import format_brl, parse_amount
from ..services import catalog, charts, compare, exporter, importer, ledger
from ..utils import current_period, is_valid_period, previous_period

router = APIRouter(prefix="/api", tags=["API"])


# ------------------------------------------------------------------ schemas

class TransactionIn(BaseModel):
    type: str = Field("saida", description="'entrada' ou 'saida'")
    status: str = Field("realizado", description="'previsto' ou 'realizado'")
    occurred_on: str | None = Field(None, description="AAAA-MM-DD ou DD/MM/AAAA")
    amount: str | float | int | None = Field(None, description="Valor em reais (aceita '1.234,56')")
    amount_centavos: int | None = Field(None, description="Valor em centavos (alternativo)")
    description: str | None = None
    category_id: int | None = None
    category_name: str | None = None
    item_id: int | None = None
    item_name: str | None = None
    method: str | None = None
    recurring: bool = False
    note: str | None = None
    create_item: bool = True


class CategoryIn(BaseModel):
    name: str
    kind: str = "saida"
    color: str = "#94a3b8"
    budget: int | None = Field(None, description="Limite mensal em centavos")
    archived: bool | None = None


class ItemIn(BaseModel):
    name: str
    category_id: int | None = None
    unit: str | None = None
    note: str | None = None


class CycleIn(BaseModel):
    expected_income: int | None = Field(None, description="Salário previsto do mês, em centavos")
    payday_day: int | None = None
    note: str | None = None
    lock: bool = True


class ImportCommitIn(BaseModel):
    token: str
    filename: str
    mapping: dict[str, int] | None = None
    default_type: str = "saida"
    default_status: str = "realizado"
    default_category: str | None = None
    create_categories: bool = True
    create_items: bool = True
    skip_duplicates: bool = True
    sheet: int | str = 0
    header_row: int | None = None


def _check_period(period: str) -> str:
    if not is_valid_period(period):
        raise HTTPException(422, f"Período inválido: '{period}' (use AAAA-MM).")
    return period


def _dump(model: BaseModel, exclude_unset: bool = False) -> dict[str, Any]:
    return model.model_dump(exclude_unset=exclude_unset)


# ------------------------------------------------------------------ saúde e metadados

@router.get("/health")
def health(conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    stats = ledger.stats_gerais(conn)
    return {
        "status": "ok",
        "app": config.APP_NAME,
        "version": config.APP_VERSION,
        "banco": str(conn.execute("PRAGMA database_list").fetchone()["file"]),
        "estatisticas": stats,
    }


@router.get("/periods")
def periods(conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return {
        "atual": current_period(),
        "disponiveis": ledger.available_periods(conn),
        "com_dados": compare.periods_with_data(conn),
    }


@router.get("/methods")
def methods(conn: sqlite3.Connection = Depends(get_db)) -> list[str]:
    return ledger.methods_in_use(conn)


# ------------------------------------------------------------------ lançamentos

@router.get("/transactions")
def list_transactions(
    conn: sqlite3.Connection = Depends(get_db),
    period: str | None = None,
    type: str | None = None,
    status: str | None = None,
    category_id: int | None = None,
    item_id: int | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    order: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(config.PAGE_SIZE, ge=1, le=200),
) -> dict[str, Any]:
    filtros = dict(
        period=period, tx_type=type, status=status, category_id=category_id,
        item_id=item_id, search=q, date_from=date_from, date_to=date_to,
    )
    total = ledger.count_transactions(conn, **filtros)
    itens = ledger.list_transactions(
        conn, order=order, limit=page_size, offset=(page - 1) * page_size, **filtros
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
        "items": itens,
    }


@router.post("/transactions", status_code=201)
def create_transaction(
    payload: TransactionIn, conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    dados = _dump(payload)
    create_item = dados.pop("create_item", True)
    try:
        return ledger.create_transaction(conn, dados, create_item=create_item)
    except ledger.ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/transactions/{tx_id}")
def get_transaction(tx_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    tx = ledger.get_transaction(conn, tx_id)
    if not tx:
        raise HTTPException(404, "Lançamento não encontrado.")
    return tx


@router.patch("/transactions/{tx_id}")
def update_transaction(
    tx_id: int, payload: TransactionIn = Body(...), conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    dados = _dump(payload, exclude_unset=True)
    create_item = dados.pop("create_item", True)
    try:
        tx = ledger.update_transaction(conn, tx_id, dados, create_item=create_item)
    except ledger.ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not tx:
        raise HTTPException(404, "Lançamento não encontrado.")
    return tx


@router.delete("/transactions/{tx_id}")
def delete_transaction(tx_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    periodo = ledger.delete_transaction(conn, tx_id)
    if periodo is None:
        raise HTTPException(404, "Lançamento não encontrado.")
    return {"ok": True, "id": tx_id, "period": periodo}


@router.post("/transactions/{tx_id}/toggle")
def toggle_transaction(tx_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    tx = ledger.toggle_status(conn, tx_id)
    if not tx:
        raise HTTPException(404, "Lançamento não encontrado.")
    return tx


@router.get("/transactions-next-recurring/{period}")
def next_recurring(period: str, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _check_period(period)
    return {"period": period, "sugestoes": ledger.next_recurring(conn, period)}


@router.post("/cycles/{period}/repeat-recurring")
def repeat_recurring(period: str, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _check_period(period)
    criados = ledger.duplicate_recurring(conn, period)
    return {"period": period, "criados": criados}


# ------------------------------------------------------------------ resumo e comparativos

@router.get("/summary/{period}")
def summary(period: str, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _check_period(period)
    resumo = ledger.month_summary(conn, period)
    resumo["graficos"] = {
        "serie": charts.bars_series(
            [{**p, "label": p["period"][5:7] + "/" + p["period"][2:4]} for p in resumo["serie"]],
            title="Entradas × saídas (6 meses)",
        ),
        "categorias": charts.hbar(resumo["categorias"], title="Gastos por categoria no mês"),
        "donut": charts.donut(
            resumo["categorias"], center_label="Total gasto", center_value=format_brl(resumo["saidas_realizadas"])
        ),
    }
    resumo["diario"] = ledger.daily_breakdown(conn, period)
    return resumo


@router.get("/compare")
def compare_months(
    conn: sqlite3.Connection = Depends(get_db),
    a: str | None = Query(None, description="Mês de referência (AAAA-MM)"),
    b: str | None = Query(None, description="Mês de comparação (AAAA-MM)"),
) -> dict[str, Any]:
    mes_a = _check_period(a) if a else current_period()
    mes_b = _check_period(b) if b else previous_period(mes_a)
    resultado = compare.compare(conn, mes_a, mes_b)
    resultado["graficos"] = {
        "categorias": charts.hbar(
            [
                {
                    "name": c["name"],
                    "total": abs(c["delta"]),
                    "color": "#ef4444" if c["delta"] > 0 else "#22c55e",
                }
                for c in resultado["categorias"]
            ],
            title="Maiores variações por categoria",
            value_key="total",
        ),
    }
    return resultado


@router.get("/reports/matrix")
def report_matrix(
    conn: sqlite3.Connection = Depends(get_db),
    months: int = Query(12, ge=2, le=36),
    period: str | None = Query(None, description="mês que encerra a janela"),
) -> dict[str, Any]:
    fim = _check_period(period) if period else None
    tabela = compare.comparison_table(conn, months=months, end_period=fim)
    tabela.pop("totais", None)
    return tabela


@router.get("/reports/accumulated")
def report_accumulated(
    conn: sqlite3.Connection = Depends(get_db),
    period: str | None = None,
    months: int = Query(12, ge=2, le=36),
) -> dict[str, Any]:
    fim = _check_period(period) if period else None
    dados = compare.accumulated(conn, fim, months)
    dados["destaques"] = compare.best_and_worst(conn, months, end_period=fim)
    dados["grafico"] = charts.line_chart(dados["pontos"], title="Saldo acumulado")
    return dados


# ------------------------------------------------------------------ categorias

@router.get("/categories")
def list_categories(
    conn: sqlite3.Connection = Depends(get_db),
    kind: str | None = None,
    period: str | None = None,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    return ledger.list_categories(conn, kind=kind, period=period, include_archived=include_archived)


@router.post("/categories", status_code=201)
def create_category(payload: CategoryIn, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    try:
        category_id = ledger.create_category(conn, payload.name, payload.kind, payload.color, payload.budget)
    except ledger.ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"id": category_id, "name": payload.name, "kind": payload.kind}


@router.patch("/categories/{category_id}")
def update_category(
    category_id: int, payload: CategoryIn = Body(...), conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    dados = _dump(payload, exclude_unset=True)
    ledger.update_category(conn, category_id, dados)
    row = conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Categoria não encontrada.")
    return dict(row)


@router.delete("/categories/{category_id}")
def delete_category(category_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    afetados = ledger.delete_category(conn, category_id)
    return {"ok": True, "id": category_id, "lancamentos_descategorizados": afetados}


# ------------------------------------------------------------------ itens

@router.get("/items")
def list_items(
    conn: sqlite3.Connection = Depends(get_db),
    q: str | None = None,
    category_id: int | None = None,
    period: str | None = None,
    only_used: bool = False,
    limit: int = Query(200, ge=1, le=2000),
) -> list[dict[str, Any]]:
    return catalog.list_items(conn, search=q, category_id=category_id, period=period, only_used=only_used, limit=limit)


@router.get("/items/suggest")
def suggest_items(
    conn: sqlite3.Connection = Depends(get_db), q: str = "", limit: int = Query(8, ge=1, le=20)
) -> list[dict[str, Any]]:
    return catalog.suggest(conn, q, limit=limit)


@router.get("/items/{item_id}")
def get_item(item_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    item = catalog.get_item(conn, item_id)
    if not item:
        raise HTTPException(404, "Item não encontrado.")
    item["historico"] = ledger.list_transactions(conn, item_id=item_id, order="desc", limit=20)
    return item


@router.post("/items", status_code=201)
def create_item(payload: ItemIn, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    nome = (payload.name or "").strip()
    if not nome:
        raise HTTPException(422, "Informe o nome do item.")
    item_id = catalog.create_item(conn, nome, payload.category_id, payload.unit, payload.note)
    return {"id": item_id, "name": nome}


@router.patch("/items/{item_id}")
def update_item(item_id: int, payload: ItemIn = Body(...), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    dados = _dump(payload, exclude_unset=True)
    if "name" in dados and (dados["name"] or "").strip():
        catalog.rename_item(conn, item_id, dados["name"])
    campos = []
    params: list[Any] = []
    for campo in ("unit", "note"):
        if campo in dados:
            campos.append(f"{campo} = ?")
            params.append(dados[campo])
    if "category_id" in dados:
        campos.append("category_id = ?")
        params.append(dados["category_id"])
    if campos:
        params.append(item_id)
        conn.execute(f"UPDATE items SET {', '.join(campos)} WHERE id = ?", tuple(params))
    item = catalog.get_item(conn, item_id)
    if not item:
        raise HTTPException(404, "Item não encontrado.")
    return item


@router.delete("/items/{item_id}")
def delete_item(item_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    catalog.delete_item(conn, item_id)
    return {"ok": True, "id": item_id}


@router.get("/items/{item_id}/price-check")
def price_check(
    item_id: int,
    amount: str | float,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    centavos = parse_amount(amount)
    if centavos is None:
        raise HTTPException(422, "Valor inválido.")
    return catalog.price_variation(conn, item_id, abs(centavos))


@router.get("/items-price-alerts/{period}")
def price_alerts(period: str, conn: sqlite3.Connection = Depends(get_db)) -> list[dict[str, Any]]:
    _check_period(period)
    return catalog.price_alerts(conn, period)


# ------------------------------------------------------------------ ciclos

@router.get("/cycles/{period}")
def get_cycle(period: str, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return ledger.get_cycle(conn, _check_period(period))


@router.put("/cycles/{period}")
def save_cycle(period: str, payload: CycleIn, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _check_period(period)
    return ledger.save_cycle(
        conn, period, expected=payload.expected_income, payday_day=payload.payday_day,
        note=payload.note, lock=payload.lock,
    )


@router.get("/cycles")
def list_cycles(conn: sqlite3.Connection = Depends(get_db), limit: int = Query(24, ge=1, le=120)) -> list[dict[str, Any]]:
    return ledger.list_cycles(conn, limit=limit)


# ------------------------------------------------------------------ importação

@router.post("/import/upload")
async def import_upload(
    request: Request,
    file: UploadFile = File(...),
    default_type: str = Form("saida"),
    default_status: str = Form("realizado"),
    default_category: str | None = Form(None),
    create_categories: bool = Form(True),
    create_items: bool = Form(True),
    skip_duplicates: bool = Form(True),
    sheet: int | str = Form(0),
    header_row: int | None = Form(None),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    conteudo = await file.read()
    if not conteudo:
        raise HTTPException(422, "Arquivo vazio.")
    try:
        token, caminho = importer.save_upload(conteudo, file.filename or "planilha")
        options = importer.ImportOptions.from_form(
            {
                "default_type": default_type,
                "default_status": default_status,
                "default_category": default_category,
                "create_categories": create_categories,
                "create_items": create_items,
                "skip_duplicates": skip_duplicates,
                "sheet": sheet,
                "header_row": header_row,
            }
        )
        previa = importer.preview(conn, token, file.filename or caminho.name, options)
        previa["path"] = str(caminho)
        return previa
    except importer.ImportException as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/import/preview")
def import_preview(
    payload: ImportCommitIn, conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    options = importer.ImportOptions(
        default_type=payload.default_type,
        default_status=payload.default_status,
        default_category=payload.default_category,
        create_categories=payload.create_categories,
        create_items=payload.create_items,
        skip_duplicates=payload.skip_duplicates,
        sheet=payload.sheet,
        header_row=payload.header_row,
    )
    try:
        return importer.preview(conn, payload.token, payload.filename, options, payload.mapping)
    except importer.ImportException as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/import/commit")
def import_commit(
    payload: ImportCommitIn, conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    options = importer.ImportOptions(
        default_type=payload.default_type,
        default_status=payload.default_status,
        default_category=payload.default_category,
        create_categories=payload.create_categories,
        create_items=payload.create_items,
        skip_duplicates=payload.skip_duplicates,
        sheet=payload.sheet,
        header_row=payload.header_row,
    )
    try:
        resultado = importer.commit(conn, payload.token, payload.filename, options, payload.mapping)
    except importer.ImportException as exc:
        raise HTTPException(422, str(exc)) from exc
    if not resultado["imported"]:
        raise HTTPException(
            422,
            "Nenhuma linha foi importada. Verifique o mapeamento das colunas de Data e Valor.",
        )
    return resultado


@router.get("/imports")
def list_imports(conn: sqlite3.Connection = Depends(get_db)) -> list[dict[str, Any]]:
    return ledger.list_imports(conn)


@router.delete("/imports/{import_id}")
def delete_import(import_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    removidos = ledger.delete_import(conn, import_id)
    if not removidos:
        raise HTTPException(404, "Importação não encontrada (ou já desfeita).")
    return {"ok": True, "id": import_id, "lancamentos_removidos": removidos}


# ------------------------------------------------------------------ exportação

def _file_response(nome: str, conteudo: bytes, media_type: str) -> Response:
    return Response(
        content=conteudo,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


@router.get("/export/csv")
def export_csv(
    conn: sqlite3.Connection = Depends(get_db), period: str | None = None, type: str | None = None
) -> Response:
    nome, conteudo = exporter.csv_bytes(conn, period, type)
    return _file_response(nome, conteudo, "text/csv; charset=utf-8")


@router.get("/export/resumo-csv")
def export_resumo_csv(conn: sqlite3.Connection = Depends(get_db), months: int = Query(12, ge=2, le=36)) -> Response:
    nome, conteudo = exporter.resumo_csv_bytes(conn, months)
    return _file_response(nome, conteudo, "text/csv; charset=utf-8")


@router.get("/export/xlsx")
def export_xlsx(
    conn: sqlite3.Connection = Depends(get_db), period: str | None = None, months: int = Query(12, ge=2, le=36)
) -> Response:
    nome, conteudo = exporter.xlsx_bytes(conn, period, months)
    return _file_response(
        nome, conteudo, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@router.get("/export/template")
def export_template() -> Response:
    nome, conteudo = exporter.template_bytes()
    return _file_response(
        nome, conteudo, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@router.post("/demo")
def seed_demo(months: int = Query(4, ge=1, le=12), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Popula o banco com dados de demonstração (útil para conhecer o sistema)."""
    from ..seed import populate_demo

    criados = populate_demo(conn, months=months)
    return {"ok": True, "lancamentos_criados": criados, "months": months}
