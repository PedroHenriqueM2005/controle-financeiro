"""Testes do livro-razão: lançamentos, ciclos, resumos e orçamentos."""

from __future__ import annotations

import pytest

from app.services import ledger


class TestCriacao:
    def test_cria_saida_com_valor_brasileiro(self, conn):
        tx = ledger.create_transaction(
            conn,
            {
                "type": "saida",
                "occurred_on": "10/10/2026",
                "amount": "1.234,56",
                "description": "Mercado",
                "category_name": "Mercado / Alimentação",
                "method": "Pix",
            },
        )
        assert tx["amount_centavos"] == 123456
        assert tx["occurred_on"] == "2026-10-10"
        assert tx["period"] == "2026-10"
        assert tx["category_name"] == "Mercado / Alimentação"
        assert tx["valor_fmt"] == "R$ 1.234,56"
        assert tx["is_entrada"] is False

    def test_cria_entrada_prevista(self, conn):
        tx = ledger.create_transaction(
            conn,
            {"type": "entrada", "status": "previsto", "amount": "3.500", "description": "Salário",
             "occurred_on": "2026-11-05", "category_name": "Salário"},
        )
        assert tx["status"] == "previsto"
        assert tx["is_previsto"] is True
        assert tx["valor_sinal_fmt"] == "+R$ 3.500,00"

    def test_aliases_de_tipo_e_status(self, conn):
        tx = ledger.create_transaction(conn, {"type": "receita", "status": "pendente", "amount": 10,
                                              "occurred_on": "2026-10-01", "description": "x"})
        assert tx["type"] == "entrada"
        assert tx["status"] == "previsto"

    def test_valor_negativo_vira_positivo_com_tipo_preservado(self, conn):
        tx = ledger.create_transaction(conn, {"type": "saida", "amount": "-50,00", "occurred_on": "2026-10-01",
                                              "description": "ajuste"})
        assert tx["amount_centavos"] == 5000

    def test_item_criado_automaticamente(self, conn):
        tx = ledger.create_transaction(
            conn, {"type": "saida", "amount": "28,90", "occurred_on": "2026-10-01",
                   "description": "Compra", "item_name": "Arroz 5kg", "category_name": "Mercado / Alimentação"}
        )
        assert tx["item_id"] is not None
        assert tx["item_name"] == "Arroz 5kg"

    def test_item_nao_criado_quando_desativado(self, conn):
        tx = ledger.create_transaction(
            conn, {"type": "saida", "amount": "28,90", "occurred_on": "2026-10-01",
                   "description": "Compra", "item_name": "Arroz 5kg"}, create_item=False
        )
        assert tx["item_id"] is None

    @pytest.mark.parametrize(
        "payload,mensagem",
        [
            ({"type": "saida", "amount": "0", "occurred_on": "2026-10-01", "description": "x"}, "maior que zero"),
            ({"type": "saida", "amount": "abc", "occurred_on": "2026-10-01", "description": "x"}, "valor válido"),
            ({"type": "saida", "occurred_on": "2026-10-01", "description": "x"}, "valor válido"),
            ({"type": "saida", "amount": "10", "occurred_on": "31/31/2026", "description": "x"}, "Data inválida"),
            ({"type": "investimento", "amount": "10", "occurred_on": "2026-10-01", "description": "x"}, "Tipo inválido"),
            ({"type": "saida", "amount": "10", "occurred_on": "2026-10-01", "status": "talvez"}, "Status inválido"),
        ],
    )
    def test_validacoes(self, conn, payload, mensagem):
        with pytest.raises(ledger.ValidationError) as exc:
            ledger.create_transaction(conn, payload)
        assert mensagem in str(exc.value)

    def test_descricao_vazia_recebe_padrao(self, conn):
        tx = ledger.create_transaction(conn, {"type": "saida", "amount": "10", "occurred_on": "2026-10-01"})
        assert tx["description"]


class TestEdicao:
    def test_update_valor_e_data_muda_periodo(self, banco_com_dados):
        conn = banco_com_dados
        tx = ledger.list_transactions(conn, period="2026-10", search="Internet")[0]
        atualizado = ledger.update_transaction(conn, tx["id"], {"amount": "180,00", "occurred_on": "2026-11-02"})
        assert atualizado["amount_centavos"] == 18000
        assert atualizado["period"] == "2026-11"
        assert ledger.count_transactions(conn, period="2026-10") == 4

    def test_update_parcial_preserva_campos(self, banco_com_dados):
        conn = banco_com_dados
        tx = ledger.list_transactions(conn, period="2026-10", search="Aluguel")[0]
        atualizado = ledger.update_transaction(conn, tx["id"], {"status": "previsto"})
        assert atualizado["status"] == "previsto"
        assert atualizado["amount_centavos"] == tx["amount_centavos"]
        assert atualizado["category_id"] == tx["category_id"]

    def test_delete(self, banco_com_dados):
        conn = banco_com_dados
        antes = ledger.count_transactions(conn, period="2026-10")
        tx = ledger.list_transactions(conn, period="2026-10")[0]
        assert ledger.delete_transaction(conn, tx["id"]) == "2026-10"
        assert ledger.count_transactions(conn, period="2026-10") == antes - 1
        assert ledger.delete_transaction(conn, tx["id"]) is None

    def test_toggle_status(self, banco_com_dados):
        conn = banco_com_dados
        tx = ledger.list_transactions(conn, period="2026-10", status="previsto")[0]
        novo = ledger.toggle_status(conn, tx["id"])
        assert novo["status"] == "realizado"
        assert ledger.toggle_status(conn, tx["id"])["status"] == "previsto"


class TestTotais:
    def test_totals_separa_previsto_de_realizado(self, banco_com_dados):
        t = ledger.totals(banco_com_dados, "2026-10")
        assert t["entradas_realizadas"] == 350000
        assert t["entradas_previstas"] == 80000
        assert t["saidas_realizadas"] == 160000
        assert t["saidas_previstas"] == 15000
        assert t["saldo_real"] == 190000
        assert t["saldo_projetado"] == 350000 + 80000 - 160000 - 15000

    def test_mes_sem_dados_zera(self, conn):
        t = ledger.totals(conn, "2020-01")
        assert t["saldo_real"] == 0 and t["entradas"] == 0

    def test_category_breakdown_ordena_por_total(self, banco_com_dados):
        cats = ledger.category_breakdown(banco_com_dados, "2026-10", "saida")
        assert cats[0]["name"] == "Moradia"
        assert cats[0]["total"] == 120000
        assert sum(c["pct"] for c in cats) == pytest.approx(100.0, abs=0.5)

    def test_series_tem_janela_de_6_meses(self, banco_com_dados):
        serie = ledger.series(banco_com_dados, "2026-10", 6)
        assert len(serie) == 6
        assert serie[-1]["period"] == "2026-10"
        assert serie[-1]["entradas"] == 350000
        assert serie[0]["vazio"] is True

    def test_fixed_vs_variable(self, banco_com_dados):
        fv = ledger.fixed_vs_variable(banco_com_dados, "2026-10")
        assert fv["fixos"] == 120000
        assert fv["variaveis"] == 40000


class TestResumoMensal:
    def test_resumo_campos_principais(self, banco_com_dados):
        from datetime import date

        r = ledger.month_summary(banco_com_dados, "2026-10", ref=date(2026, 10, 20))
        assert r["period"] == "2026-10"
        assert r["dias_corridos"] == 20
        assert r["dias_restantes"] == 11
        assert r["entradas_realizadas_fmt"] == "R$ 3.500,00"
        assert r["receber_total"] == r["salario_previsto"] + r["entradas_previstas"]
        assert r["media_diaria_gasto"] == 160000 // 20
        assert r["sugestao_gasto_diario"] > 0
        assert r["comprometido_pct"] == pytest.approx(160000 / 350000 * 100, abs=0.1)
        assert isinstance(r["alertas"], list)
        assert len(r["serie"]) == 6

    def test_mes_futuro_tem_zero_dias_corridos(self, banco_com_dados):
        from datetime import date

        r = ledger.month_summary(banco_com_dados, "2027-01", ref=date(2026, 10, 20))
        assert r["dias_corridos"] == 0
        assert r["media_diaria_gasto"] == 0
        assert r["sugestao_gasto_diario"] == 0

    def test_alerta_de_saldo_negativo(self, conn):
        from datetime import date

        ledger.create_transaction(conn, {"type": "entrada", "amount": "100", "occurred_on": "2026-10-01",
                                         "description": "Salário", "category_name": "Salário"})
        ledger.create_transaction(conn, {"type": "saida", "amount": "500", "occurred_on": "2026-10-02",
                                         "description": "Conta", "category_name": "Moradia"})
        r = ledger.month_summary(conn, "2026-10", ref=date(2026, 10, 15))
        tipos = [a["tipo"] for a in r["alertas"]]
        assert "saldo" in tipos
        assert r["saldo_projetado"] < 0

    def test_alerta_de_orcamento_estourado(self, conn):
        from datetime import date

        cat_id = ledger.ensure_category(conn, "Mercado / Alimentação", "saida")
        ledger.update_category(conn, cat_id, {"budget": 10000})  # R$ 100,00
        ledger.create_transaction(conn, {"type": "saida", "amount": "150", "occurred_on": "2026-10-02",
                                         "description": "feira", "category_id": cat_id})
        r = ledger.month_summary(conn, "2026-10", ref=date(2026, 10, 15))
        assert any(a["tipo"] == "orcamento" and a["nivel"] == "perigo" for a in r["alertas"])
        assert r["categorias"][0]["estourou"] is True


class TestCiclos:
    def test_sincroniza_salario_previsto(self, conn):
        ledger.create_transaction(conn, {"type": "entrada", "amount": "3.500,00", "occurred_on": "2026-10-05",
                                         "description": "Salário", "category_name": "Salário"})
        ciclo = ledger.get_cycle(conn, "2026-10")
        assert ciclo["expected_income_centavos"] == 350000
        assert ciclo["expected_locked"] is False

    def test_valor_manual_nao_e_sobrescrito(self, conn):
        ledger.save_cycle(conn, "2026-10", expected=500000, payday_day=5, lock=True)
        ledger.create_transaction(conn, {"type": "entrada", "amount": "3.500,00", "occurred_on": "2026-10-05",
                                         "description": "Salário", "category_name": "Salário"})
        ciclo = ledger.get_cycle(conn, "2026-10")
        assert ciclo["expected_income_centavos"] == 500000
        assert ciclo["payday_day"] == 5

    def test_dia_de_pagamento_limitado(self, conn):
        ciclo = ledger.save_cycle(conn, "2026-10", payday_day=99)
        assert ciclo["payday_day"] == 31

    def test_apagar_salario_zera_ciclo(self, conn):
        tx = ledger.create_transaction(conn, {"type": "entrada", "amount": "2.000", "occurred_on": "2026-10-05",
                                              "description": "Salário", "category_name": "Salário"})
        assert ledger.get_cycle(conn, "2026-10")["expected_income_centavos"] == 200000
        ledger.delete_transaction(conn, tx["id"])
        assert ledger.get_cycle(conn, "2026-10")["expected_income_centavos"] == 0


class TestCategorias:
    def test_ensure_case_e_acento_insensivel(self, conn):
        a = ledger.ensure_category(conn, "Mercado / Alimentação")
        b = ledger.ensure_category(conn, "mercado / alimentacao")
        assert a == b

    def test_criar_duplicada_falha(self, conn):
        ledger.create_category(conn, "Pets", "saida", "#f472b6")
        with pytest.raises(ledger.ValidationError):
            ledger.create_category(conn, "pets", "saida", "#000000")

    def test_orcamento_e_arquivamento(self, conn):
        cat_id = ledger.create_category(conn, "Pets", "saida", "#f472b6", budget=30000)
        ledger.update_category(conn, cat_id, {"archived": True})
        nomes = [c["name"] for c in ledger.list_categories(conn, kind="saida")]
        assert "Pets" not in nomes
        nomes_todos = [c["name"] for c in ledger.list_categories(conn, kind="saida", include_archived=True)]
        assert "Pets" in nomes_todos

    def test_excluir_categoria_descategoriza(self, conn):
        cat_id = ledger.create_category(conn, "Temporária", "saida", "#000")
        tx = ledger.create_transaction(conn, {"type": "saida", "amount": "10", "occurred_on": "2026-10-01",
                                              "description": "x", "category_id": cat_id})
        assert ledger.delete_category(conn, cat_id) == 1
        assert ledger.get_transaction(conn, tx["id"])["category_id"] is None


class TestRecorrentes:
    def test_copia_gastos_fixos_como_previstos(self, banco_com_dados):
        conn = banco_com_dados
        sugestoes = ledger.next_recurring(conn, "2026-11")
        assert any(s["description"] == "Aluguel" for s in sugestoes)
        criados = ledger.duplicate_recurring(conn, "2026-11")
        assert criados >= 1
        novos = ledger.list_transactions(conn, period="2026-11")
        assert all(t["status"] == "previsto" for t in novos)
        # segunda chamada não duplica
        assert ledger.duplicate_recurring(conn, "2026-11") == 0

    def test_dia_limitado_ao_fim_do_mes(self, conn):
        ledger.create_transaction(conn, {"type": "saida", "amount": "100", "occurred_on": "2026-01-31",
                                         "description": "Assinatura", "category_name": "Assinaturas", "recurring": True})
        ledger.duplicate_recurring(conn, "2026-02")
        tx = ledger.list_transactions(conn, period="2026-02")[0]
        assert tx["occurred_on"] == "2026-02-28"


class TestFiltros:
    def test_busca_por_descricao_e_item(self, banco_com_dados):
        conn = banco_com_dados
        assert ledger.count_transactions(conn, search="aluguel") == 2
        assert ledger.count_transactions(conn, period="2026-10", tx_type="saida") == 3
        assert ledger.count_transactions(conn, status="previsto") == 2

    def test_paginacao(self, banco_com_dados):
        conn = banco_com_dados
        primeira = ledger.list_transactions(conn, limit=2, offset=0)
        segunda = ledger.list_transactions(conn, limit=2, offset=2)
        assert len(primeira) == 2
        assert {t["id"] for t in primeira}.isdisjoint({t["id"] for t in segunda})

    def test_filtro_por_intervalo_de_datas(self, banco_com_dados):
        conn = banco_com_dados
        achados = ledger.list_transactions(conn, date_from="2026-10-06", date_to="2026-10-20")
        assert all("2026-10-06" <= t["occurred_on"] <= "2026-10-20" for t in achados)

    def test_available_periods_inclui_mes_atual(self, banco_com_dados):
        from app.utils import current_period

        periodos = ledger.available_periods(banco_com_dados)
        assert current_period() in periodos
        assert "2026-09" in periodos
        assert periodos == sorted(periodos, reverse=True)
