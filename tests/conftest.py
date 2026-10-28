"""Fixtures: banco isolado por teste e cliente HTTP da aplicação."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# dados temporários ANTES de importar o app (config lê o ambiente no import)
_TMP = Path(tempfile.mkdtemp(prefix="saldo-testes-"))
os.environ["FINANCAS_DATA_DIR"] = str(_TMP)
os.environ["FINANCAS_DB"] = str(_TMP / "financas.db")


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "teste.db"


@pytest.fixture()
def conn(db_path: Path):
    from app import db

    conexao = db.init_db(db_path)
    try:
        yield conexao
    finally:
        conexao.close()


@pytest.fixture()
def client(db_path: Path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(db_path)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def banco_com_dados(conn):
    """Cenário pronto: 2 meses de lançamentos com salário, gastos fixos e variáveis."""
    from app.services import ledger

    def add(**kw):
        kw.setdefault("source", "teste")
        return ledger.create_transaction(conn, kw)

    add(type="entrada", status="realizado", occurred_on="2026-09-05", amount="3.500,00",
        description="Salário", category_name="Salário", method="Transferência")
    add(type="saida", status="realizado", occurred_on="2026-09-05", amount="1.200,00",
        description="Aluguel", category_name="Moradia", item_name="Aluguel", recurring=True)
    add(type="saida", status="realizado", occurred_on="2026-09-10", amount="300,00",
        description="Mercado", category_name="Mercado / Alimentação", item_name="Arroz 5kg")
    add(type="saida", status="realizado", occurred_on="2026-09-18", amount="320,00",
        description="Mercado", category_name="Mercado / Alimentação", item_name="Arroz 5kg")

    add(type="entrada", status="realizado", occurred_on="2026-10-05", amount="3.500,00",
        description="Salário", category_name="Salário", method="Transferência")
    add(type="entrada", status="previsto", occurred_on="2026-10-20", amount="800,00",
        description="Freela", category_name="Freelance / Extra")
    add(type="saida", status="realizado", occurred_on="2026-10-05", amount="1.200,00",
        description="Aluguel", category_name="Moradia", item_name="Aluguel", recurring=True)
    add(type="saida", status="realizado", occurred_on="2026-10-12", amount="400,00",
        description="Mercado", category_name="Mercado / Alimentação", item_name="Arroz 5kg")
    add(type="saida", status="previsto", occurred_on="2026-10-25", amount="150,00",
        description="Internet", category_name="Contas (água, luz, internet)", item_name="Internet 400MB",
        recurring=True)
    return conn
