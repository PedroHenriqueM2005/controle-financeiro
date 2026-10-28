"""Testes dos comparativos entre meses e da matriz categorias × meses."""

from __future__ import annotations

from app.services import compare, ledger


def _cenario(conn):
    """Setembro e outubro de 2026 com categorias e itens diferentes."""
    dados = [
        ("2026-09-05", "entrada", "Salário", "Salário", "3.500,00", None),
        ("2026-09-06", "saida", "Aluguel", "Moradia", "1.200,00", "Aluguel"),
        ("2026-09-10", "saida", "Mercado", "Mercado / Alimentação", "600,00", "Arroz 5kg"),
        ("2026-09-20", "saida", "Cinema", "Lazer", "80,00", "Cinema"),
        ("2026-10-05", "entrada", "Salário", "Salário", "3.500,00", None),
        ("2026-10-06", "saida", "Aluguel", "Moradia", "1.250,00", "Aluguel"),
        ("2026-10-10", "saida", "Mercado", "Mercado / Alimentação", "420,00", "Arroz 5kg"),
        ("2026-10-11", "saida", "Farmácia", "Saúde", "130,00", "Dipirona"),
    ]
    for data, tipo, descricao, categoria, valor, item in dados:
        ledger.create_transaction(
            conn,
            {"type": tipo, "amount": valor, "occurred_on": data, "description": descricao,
             "category_name": categoria, "item_name": item, "source": "teste"},
        )


class TestComparacao:
    def test_totais_e_deltas(self, conn):
        _cenario(conn)
        r = compare.compare(conn, "2026-10", "2026-09")
        assert r["atual"]["saidas_realizadas"] == 125000 + 42000 + 13000
        assert r["anterior"]["saidas_realizadas"] == 120000 + 60000 + 8000
        assert r["totais"]["saidas"]["delta"] == 180000 - 188000
        assert r["totais"]["saidas"]["caiu"] is True
        assert r["totais"]["entradas"]["delta"] == 0

    def test_variacao_por_categoria(self, conn):
        _cenario(conn)
        r = compare.compare(conn, "2026-10", "2026-09")
        por_nome = {c["name"]: c for c in r["categorias"]}
        assert por_nome["Moradia"]["delta"] == 5000
        assert por_nome["Mercado / Alimentação"]["delta"] == -18000
        assert por_nome["Saúde"]["novo"] is True          # só existe em outubro
        assert por_nome["Lazer"]["atual"] == 0            # só existe em setembro

    def test_preco_medio_por_item(self, conn):
        _cenario(conn)
        r = compare.compare(conn, "2026-10", "2026-09")
        itens = {i["key"]: i for i in r["itens"]}
        arroz = next(v for k, v in itens.items() if "arroz" in k)
        assert arroz["preco_medio_atual"] == 42000
        assert arroz["preco_subiu"] is False
        assert arroz["preco_variacao_pct"] == -30.0

    def test_resumo_textual(self, conn):
        _cenario(conn)
        r = compare.compare(conn, "2026-10", "2026-09")
        assert "economizou" in r["resumo_texto"]

    def test_mes_sem_dados(self, conn):
        _cenario(conn)
        r = compare.compare(conn, "2026-10", "2020-01")
        assert r["anterior"]["saidas_realizadas"] == 0
        assert r["totais"]["saidas"]["pct"] is None

    def test_padrao_compara_com_mes_anterior(self, banco_com_dados):
        r = compare.compare(banco_com_dados, "2026-10")
        assert r["periodo_anterior"] == "2026-09"

    def test_year_over_year(self, conn):
        _cenario(conn)
        r = compare.year_over_year(conn, "2026-10")
        assert r["periodo_anterior"] == "2025-10"


class TestMatriz:
    def test_matriz_ancorada_no_mes_informado(self, conn):
        _cenario(conn)
        tabela = compare.comparison_table(conn, months=3, end_period="2026-10")
        assert tabela["periodos"] == ["2026-08", "2026-09", "2026-10"]
        nomes = [l["name"] for l in tabela["linhas"]]
        assert "Moradia" in nomes and "Saúde" in nomes
        moradia = next(l for l in tabela["linhas"] if l["name"] == "Moradia")
        assert [c["valor"] for c in moradia["celulas"]] == [0, 120000, 125000]
        assert moradia["total"] == 245000
        assert moradia["media"] == 245000 // 3

    def test_rodape_com_entradas_saidas_saldo(self, conn):
        _cenario(conn)
        tabela = compare.comparison_table(conn, months=2, end_period="2026-10")
        saldos = {c["period"]: c["valor"] for c in tabela["rodape"]["saldo"]}
        assert saldos["2026-10"] == 350000 - 180000
        assert saldos["2026-09"] == 350000 - 188000

    def test_matriz_vazia(self, conn):
        tabela = compare.comparison_table(conn, months=3)
        assert tabela["linhas"] == []


class TestAcumulado:
    def test_saldo_acumulado(self, conn):
        _cenario(conn)
        r = compare.accumulated(conn, "2026-10", months=3)
        pontos = {p["period"]: p for p in r["pontos"]}
        assert pontos["2026-08"]["acumulado"] == 0
        assert pontos["2026-09"]["acumulado"] == 350000 - 188000
        assert pontos["2026-10"]["acumulado"] == (350000 - 188000) + (350000 - 180000)
        assert r["final"] == pontos["2026-10"]["acumulado"]

    def test_melhor_e_pior_mes(self, conn):
        _cenario(conn)
        r = compare.best_and_worst(conn, months=3)
        assert r["melhor"]["period"] == "2026-10"
        assert r["pior"]["period"] == "2026-09"
        assert r["meses_analisados"] == 2

    def test_sem_dados(self, conn):
        assert compare.best_and_worst(conn)["melhor"] is None


class TestPeriodos:
    def test_lista_periodos_com_dados(self, banco_com_dados):
        periodos = compare.periods_with_data(banco_com_dados)
        assert "2026-09" in periodos and "2026-10" in periodos
        assert periodos == sorted(periodos, reverse=True)
