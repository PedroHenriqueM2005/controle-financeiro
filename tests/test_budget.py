"""Orçamento por categoria: comparativo informativo (sem alertas)."""

from __future__ import annotations

import pytest

from app.services import ledger


@pytest.fixture()
def com_limites(conn):
    """Duas categorias com limite, uma delas sem nenhum gasto no mês."""
    mercado = ledger.ensure_category(conn, "Mercado / Alimentação", "saida")
    transporte = ledger.ensure_category(conn, "Transporte", "saida")
    lazer = ledger.ensure_category(conn, "Lazer", "saida")
    ledger.update_category(conn, mercado, {"budget": 80000})      # R$ 800,00
    ledger.update_category(conn, transporte, {"budget": 30000})   # R$ 300,00
    # lazer fica SEM limite: não pode aparecer no resumo de orçamento

    ledger.create_transaction(conn, {"type": "saida", "status": "realizado", "occurred_on": "2026-10-03",
                                     "amount": "250,00", "description": "feira", "category_id": mercado})
    ledger.create_transaction(conn, {"type": "saida", "status": "realizado", "occurred_on": "2026-10-17",
                                     "amount": "120,00", "description": "mercado", "category_id": mercado})
    ledger.create_transaction(conn, {"type": "saida", "status": "previsto", "occurred_on": "2026-10-28",
                                     "amount": "500,00", "description": "compra do mês", "category_id": mercado})
    ledger.create_transaction(conn, {"type": "saida", "status": "realizado", "occurred_on": "2026-10-09",
                                     "amount": "350,00", "description": "gasolina", "category_id": transporte})
    ledger.create_transaction(conn, {"type": "saida", "status": "realizado", "occurred_on": "2026-10-11",
                                     "amount": "90,00", "description": "cinema", "category_id": lazer})
    # entrada não entra no orçamento de saídas
    ledger.create_transaction(conn, {"type": "entrada", "status": "realizado", "occurred_on": "2026-10-05",
                                     "amount": "3.500,00", "description": "Salário", "category_name": "Salário"})
    return conn


class TestResumoDeOrcamento:
    def test_categoria_orcada_sem_gasto_aparece(self, com_limites):
        """Diferença central para category_breakdown: parte das categorias, não dos gastos."""
        conn = com_limites
        ledger.create_transaction(conn, {"type": "saida", "occurred_on": "2026-09-10", "amount": "10,00",
                                         "description": "x", "category_name": "Vestuário"})
        vestuario = ledger.ensure_category(conn, "Vestuário", "saida")
        ledger.update_category(conn, vestuario, {"budget": 20000})

        orc = ledger.budget_summary(conn, "2026-10")
        nomes = [c["name"] for c in orc["categorias"]]
        assert "Vestuário" in nomes
        v = next(c for c in orc["categorias"] if c["name"] == "Vestuário")
        assert v["gasto"] == 0 and v["gasto_fmt"] == "R$ 0,00"
        assert v["budget_fmt"] == "R$ 200,00"
        assert v["pct"] == 0.0
        assert v["disponivel_fmt"] == "R$ 200,00" and v["acima"] is False

    def test_separa_realizado_de_previsto(self, com_limites):
        orc = ledger.budget_summary(com_limites, "2026-10")
        mercado = next(c for c in orc["categorias"] if c["name"] == "Mercado / Alimentação")
        # a barra usa só o que já saiu do bolso (250 + 120)
        assert mercado["gasto"] == 37000
        assert mercado["previsto"] == 50000
        assert mercado["pct"] == pytest.approx(46.3, abs=0.1)
        assert mercado["qtd"] == 3

    def_categoria = None  # noqa: placeholder removido abaixo


class TestOrdemEFaixas:
    def test_mais_comprometido_vem_primeiro(self, com_limites):
        nomes = [c["name"] for c in ledger.budget_summary(com_limites, "2026-10")["categorias"]]
        assert nomes[0] == "Transporte"          # 116,7% do limite
        assert nomes[1] == "Mercado / Alimentação"  # 46,3%

    def test_acima_e_perto_do_limite(self, com_limites):
        orc = ledger.budget_summary(com_limites, "2026-10")
        transporte = next(c for c in orc["categorias"] if c["name"] == "Transporte")
        assert transporte["acima"] is True
        assert transporte["disponivel_fmt"] == "R$ 50,00"   # valor absoluto
        assert transporte["pct"] == pytest.approx(116.7, abs=0.1)

        mercado = next(c for c in orc["categorias"] if c["name"] == "Mercado / Alimentação")
        assert mercado["acima"] is False and mercado["perto"] is False

        # 80% do limite já conta como "perto" (informação, não alarme)
        ledger.create_transaction(com_limites, {"type": "saida", "occurred_on": "2026-10-20",
                                                "amount": "280,00", "description": "mais feira",
                                                "category_name": "Mercado / Alimentação"})
        mercado = next(c for c in ledger.budget_summary(com_limites, "2026-10")["categorias"]
                       if c["name"] == "Mercado / Alimentação")
        assert mercado["perto"] is True and mercado["acima"] is False

    def test_categoria_sem_limite_fica_de_fora(self, com_limites):
        orc = ledger.budget_summary(com_limites, "2026-10")
        assert "Lazer" not in [c["name"] for c in orc["categorias"]]
        assert orc["qtd"] == 2


class TestTotaisGerais:
    def test_totais_do_mes(self, com_limites):
        orc = ledger.budget_summary(com_limites, "2026-10")
        assert orc["orcado"] == 110000                 # 800 + 300
        assert orc["gasto"] == 37000 + 35000           # só realizado
        assert orc["previsto"] == 50000
        assert orc["disponivel"] == 110000 - 72000
        assert orc["pct"] == pytest.approx(65.5, abs=0.1)
        assert orc["acima"] is False
        assert orc["tem_dados"] is True
        assert orc["orcado_fmt"] == "R$ 1.100,00"
        assert orc["gasto_fmt"] == "R$ 720,00"

    def test_mes_sem_nada(self, conn):
        orc = ledger.budget_summary(conn, "2026-10")
        assert orc["tem_dados"] is False
        assert orc["categorias"] == [] and orc["orcado"] == 0 and orc["gasto"] == 0
        assert orc["pct"] is None

    def test_entra_no_resumo_do_mes(self, com_limites):
        r = ledger.month_summary(com_limites, "2026-10")
        assert r["orcamento"]["orcado"] == 110000
        assert r["orcamento"]["categorias"][0]["name"] == "Transporte"


class TestSemAlertas:
    """Decisão de produto: orçamento informa, não alerta."""

    def test_limite_estourado_nao_gera_alerta(self, com_limites):
        r = ledger.month_summary(com_limites, "2026-10")
        assert not any(a["tipo"] == "orcamento" for a in r["alertas"])
        assert not any("limite" in a["titulo"].lower() for a in r["alertas"])

    def test_outros_alertas_continuam_valendo(self, com_limites):
        ledger.create_transaction(com_limites, {"type": "entrada", "status": "previsto",
                                                "occurred_on": "2026-10-20", "amount": "500,00",
                                                "description": "Freela", "category_name": "Freelance / Extra"})
        r = ledger.month_summary(com_limites, "2026-10")
        assert any(a["tipo"] == "receber" for a in r["alertas"])

    def test_categoria_estourada_mantem_o_flag_para_a_tela(self, com_limites):
        """O dado continua disponível (API/planilha); só a apresentação é sóbria."""
        r = ledger.month_summary(com_limites, "2026-10")
        transporte = next(c for c in r["categorias"] if c["name"] == "Transporte")
        assert transporte["estourou"] is True


class TestApiOrcamento:
    def test_endpoint(self, client):
        cat = client.post("/api/categories", json={"name": "Pets", "kind": "saida",
                                                   "color": "#f472b6", "budget": 30000}).json()
        client.post("/api/transactions", json={"type": "saida", "occurred_on": "2026-10-04",
                                               "amount": "320,00", "description": "ração",
                                               "category_id": cat["id"]})
        r = client.get("/api/budget/2026-10")
        assert r.status_code == 200
        corpo = r.json()
        assert corpo["orcado"] == 30000 and corpo["gasto"] == 32000
        assert corpo["categorias"][0]["name"] == "Pets"
        assert corpo["categorias"][0]["acima"] is True

    def test_periodo_invalido(self, client):
        assert client.get("/api/budget/2026-99").status_code == 422

    def test_summary_traz_orcamento(self, client):
        assert "orcamento" in client.get("/api/summary/2026-10").json()
