"""Testes do importador de planilhas (CSV e XLSX)."""

from __future__ import annotations

import io
from datetime import date, datetime

import pytest

from app.services import importer, ledger
from app.services.importer import ImportException, ImportOptions, ParsedRow

CSV_BR = """Planilha de gastos da família - 2025
Data;Descrição;Categoria;Valor;Forma de pagamento;Status
05/01/2025;Salário;Salário;4.100,00;Transferência;Recebido
05/01/2025;Aluguel;Moradia;1.150,00;Boleto;Pago
08/01/2025;Mercado do mês;Mercado;612,40;Cartão de débito;Pago
15/01/2025;Cinema;Lazer;(85,00);Pix;Pago
30/01/2025;Lançamento sem data válida;Lazer;;Pix;Pago
"""

CSV_EXTRATO = """date,description,amount
2025-03-05,SALARIO EMPRESA,5200.00
2025-03-06,SUPERMERCADO,-487.32
2025-03-08,UBER,-32.90
2025-03-10,CONTA LUZ,-189.44
2025-03-12,PIX RECEBIDO,250.00
2025-03-15,FARMACIA,-64.20
"""


def _salva(conteudo: bytes | str, nome: str) -> str:
    if isinstance(conteudo, str):
        conteudo = conteudo.encode("utf-8")
    token, _ = importer.save_upload(conteudo, nome)
    return token


def _preview(conn, token, nome, **opts):
    return importer.preview(conn, token, nome, ImportOptions(**opts))


class TestDeteccaoDeColunas:
    @pytest.mark.parametrize(
        "cabecalho,campo",
        [
            ("Data", "date"), ("DATA DO PAGAMENTO", "date"), ("effective date", "date"),
            ("Valor", "amount"), ("Valor (R$)", "amount"), ("amount", "amount"),
            ("Descrição", "description"), ("histórico", "description"), ("memo", "description"),
            ("Categoria", "category"), ("grupo", "category"),
            ("Tipo", "type"), ("D/C", "type"),
            ("Status", "status"), ("situação", "status"),
            ("Forma de pagamento", "method"), ("cartão", "method"),
            ("Item", "item"), ("produto", "item"),
            ("obs", "note"),
        ],
    )
    def test_aliases(self, cabecalho, campo):
        assert importer.match_field(cabecalho) == campo

    def test_cabecalho_desconhecido(self):
        assert importer.match_field("xyz") is None
        assert importer.match_field("") is None

    def test_detecta_cabecalho_apos_titulo(self):
        rows = [c.split(";") for c in CSV_BR.strip().splitlines()]
        idx, mapping = importer.detect_header(rows)
        assert idx == 1
        assert mapping["date"] == 0 and mapping["amount"] == 3 and mapping["category"] == 2

    def test_planilha_sem_cabecalho(self):
        rows = [["05/01/2025", "Aluguel", "1150,00"], ["06/01/2025", "Feira", "80,00"]]
        idx, mapping = importer.detect_header(rows)
        assert idx == 0
        assert mapping.get("date") == 0 and mapping.get("amount") == 2


class TestParsingCSV:
    def test_previa_conta_linhas_validas_e_invalidas(self, conn):
        token = _salva(CSV_BR, "gastos.csv")
        p = _preview(conn, token, "gastos.csv", default_type="saida")
        assert p["rows_total"] == 5
        assert p["validas"] == 4
        assert p["invalidas"] == 1
        assert p["errors"][0]["error"]

    def test_tipos_e_status_inferidos(self, conn):
        token = _salva(CSV_BR, "gastos.csv")
        p = _preview(conn, token, "gastos.csv", default_type="saida")
        por_desc = {r["description"]: r for r in p["preview"]}
        assert por_desc["Salário"]["type"] == "entrada"        # dica textual de receita
        assert por_desc["Aluguel"]["type"] == "saida"
        assert por_desc["Cinema"]["type"] == "saida"           # (85,00) => negativo => saída
        assert por_desc["Aluguel"]["status"] == "realizado"    # "Pago"
        assert por_desc["Salário"]["status"] == "realizado"    # "Recebido"

    def test_categoria_da_planilha_vira_categoria_nova(self, conn):
        token = _salva(CSV_BR, "gastos.csv")
        p = _preview(conn, token, "gastos.csv", default_type="saida")
        assert "Mercado" in p["categorias_novas"]      # não existia
        assert "Moradia" not in p["categorias_novas"]   # já é categoria padrão

    def test_periodos_agrupados(self, conn):
        token = _salva(CSV_BR, "gastos.csv")
        p = _preview(conn, token, "gastos.csv", default_type="saida")
        assert p["periodos"] == {"2025-01": 4}

    def test_delimitador_virgula(self, conn):
        token = _salva(CSV_EXTRATO, "extrato.csv")
        p = _preview(conn, token, "extrato.csv")
        assert p["mapping"]["amount"] == 2
        assert p["modo_extrato"] is True


class TestModoExtrato:
    def test_extrato_com_muitos_negativos_vira_entrada_saida(self, conn):
        token = _salva(CSV_EXTRATO, "extrato.csv")
        p = _preview(conn, token, "extrato.csv", default_type="saida")
        tipos = {r["description"]: r["type"] for r in p["preview"]}
        assert tipos["SALARIO EMPRESA"] == "entrada"
        assert tipos["SUPERMERCADO"] == "saida"
        assert tipos["PIX RECEBIDO"] == "entrada"

    def test_planilha_de_gastos_com_um_negativo_nao_vira_extrato(self, conn):
        csv = "Data;Descrição;Valor\n01/10/2026;Mercado;100,00\n02/10/2026;Feira;50,00\n03/10/2026;Estorno;-20,00\n"
        token = _salva(csv, "gastos.csv")
        p = _preview(conn, token, "gastos.csv", default_type="saida")
        assert p["modo_extrato"] is False
        assert all(r["type"] == "saida" for r in p["preview"])

    def test_limiar_de_negativos_do_modo_extrato(self, conn):
        # 2 negativos em 4 linhas ainda não caracteriza extrato bancário
        csv = ("Data;Descrição;Valor\n01/10/2026;A;100,00\n02/10/2026;B;-50,00\n"
               "03/10/2026;C;80,00\n04/10/2026;D;-20,00\n")
        p = _preview(conn, _salva(csv, "g.csv"), "g.csv", default_type="saida")
        assert p["modo_extrato"] is False
        # 3 negativos em 4 linhas (75%) => extrato
        csv2 = ("Data;Descrição;Valor\n01/10/2026;A;100,00\n02/10/2026;B;-50,00\n"
                "03/10/2026;C;-80,00\n04/10/2026;D;-20,00\n")
        p2 = _preview(conn, _salva(csv2, "e.csv"), "e.csv", default_type="saida")
        assert p2["modo_extrato"] is True

    def test_coluna_tipo_vence_o_sinal(self, conn):
        csv = "Data;Descrição;Valor;Tipo\n01/10/2026;Salário;3000,00;entrada\n02/10/2026;Aluguel;-1000,00;saída\n"
        token = _salva(csv, "c.csv")
        p = _preview(conn, token, "c.csv")
        tipos = {r["description"]: r["type"] for r in p["preview"]}
        assert tipos == {"Salário": "entrada", "Aluguel": "saida"}


class TestDatas:
    def test_data_excel_serial(self):
        assert importer._as_date(45658) == date(2025, 1, 1)

    def test_data_datetime(self):
        assert importer._as_date(datetime(2025, 3, 5, 10, 30)) == date(2025, 3, 5)

    def test_data_texto(self):
        assert importer._as_date("05/03/2025") == date(2025, 3, 5)
        assert importer._as_date("2025-03-05") == date(2025, 3, 5)
        assert importer._as_date("nada") is None


class TestXLSX:
    def _gera(self, linhas, abas=("Lançamentos",)):
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = abas[0]
        for linha in linhas:
            ws.append(linha)
        for extra in abas[1:]:
            outra = wb.create_sheet(extra)
            outra.append(["Data", "Valor"])
            outra.append([datetime(2025, 6, 1), 50])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_le_xlsx_com_datetime(self, conn):
        conteudo = self._gera(
            [
                ["Data", "Descrição", "Categoria", "Valor"],
                [datetime(2025, 5, 3), "Aluguel", "Moradia", 1200.5],
                [datetime(2025, 5, 10), "Mercado", "Mercado", 340],
            ]
        )
        token = _salva(conteudo, "plan.xlsx")
        p = _preview(conn, token, "plan.xlsx", default_type="saida")
        assert p["validas"] == 2
        assert p["preview"][0]["date"] == "2025-05-03"
        assert p["preview"][0]["amount"] == 120050

    def test_multiplas_abas(self, conn):
        conteudo = self._gera(
            [["Data", "Valor"], [datetime(2025, 5, 3), 100]], abas=("Maio", "Junho")
        )
        token = _salva(conteudo, "multi.xlsx")
        p = _preview(conn, token, "multi.xlsx")
        assert p["sheets"] == ["Maio", "Junho"]
        assert p["preview"][0]["date"] == "2025-05-03"
        p2 = _preview(conn, token, "multi.xlsx", sheet=1)
        assert p2["preview"][0]["date"] == "2025-06-01"

    def test_extensao_invalida(self):
        with pytest.raises(ImportException):
            importer.save_upload(b"qualquer", "arquivo.pdf")

    def test_arquivo_grande_demais(self, monkeypatch):
        from app import config

        monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 10)
        with pytest.raises(ImportException):
            importer.save_upload(b"0123456789abcdef", "grande.csv")


class TestCommit:
    def test_importa_cria_itens_categorias_e_lote(self, conn):
        token = _salva(CSV_BR, "gastos-2025.csv")
        p = _preview(conn, token, "gastos-2025.csv", default_type="saida")
        r = importer.commit(conn, token, "gastos-2025.csv", ImportOptions(default_type="saida"), p["mapping"])
        conn.commit()
        assert r["imported"] == 4
        assert r["skipped"] == 1
        assert r["periodos"] == ["2025-01"]
        assert ledger.count_transactions(conn, period="2025-01") == 4

        aluguel = ledger.list_transactions(conn, period="2025-01", search="Aluguel")[0]
        assert aluguel["category_name"] == "Moradia"
        assert aluguel["item_name"] == "Aluguel"          # item novo entrou no catálogo
        assert aluguel["source"].startswith("import:gastos-2025.csv")
        assert aluguel["import_id"] == r["batch_id"]

    def test_reimportar_ignora_duplicadas(self, conn):
        token = _salva(CSV_BR, "g.csv")
        p = _preview(conn, token, "g.csv", default_type="saida")
        importer.commit(conn, token, "g.csv", ImportOptions(default_type="saida"), p["mapping"])
        conn.commit()

        token2 = _salva(CSV_BR, "g.csv")
        p2 = _preview(conn, token2, "g.csv", default_type="saida")
        assert p2["duplicadas"] == 4
        r = importer.commit(conn, token2, "g.csv", ImportOptions(default_type="saida"), p2["mapping"])
        assert r["imported"] == 0 and r["skipped"] == 5
        assert ledger.count_transactions(conn, period="2025-01") == 4

    def test_duplicadas_dentro_do_proprio_arquivo(self, conn):
        csv = "Data;Descrição;Valor\n01/10/2026;Café;10,00\n01/10/2026;Café;10,00\n"
        token = _salva(csv, "d.csv")
        p = _preview(conn, token, "d.csv", default_type="saida")
        assert p["duplicadas"] == 1
        r = importer.commit(conn, token, "d.csv", ImportOptions(default_type="saida"), p["mapping"])
        assert r["imported"] == 1

    def test_desfazer_importacao(self, conn):
        token = _salva(CSV_BR, "g.csv")
        p = _preview(conn, token, "g.csv", default_type="saida")
        r = importer.commit(conn, token, "g.csv", ImportOptions(default_type="saida"), p["mapping"])
        conn.commit()
        assert ledger.count_transactions(conn, period="2025-01") == 4
        assert ledger.delete_import(conn, r["batch_id"]) == 4
        assert ledger.count_transactions(conn, period="2025-01") == 0
        assert ledger.list_imports(conn) == []

    def test_override_de_mapeamento(self, conn):
        csv = "A;B;C\n01/10/2026;Mercado;250,00\n"
        token = _salva(csv, "sem-nomes.csv")
        mapping = {"date": 0, "description": 1, "amount": 2}
        p = importer.preview(conn, token, "sem-nomes.csv", ImportOptions(default_type="saida"), mapping)
        assert p["validas"] == 1
        r = importer.commit(conn, token, "sem-nomes.csv", ImportOptions(default_type="saida"), mapping)
        assert r["imported"] == 1

    def test_sem_colunas_obrigatorias(self, conn):
        token = _salva("nome;idade\njoão;30\n", "x.csv")
        with pytest.raises(ImportException):
            _preview(conn, token, "x.csv")

    def test_arquivo_inexistente(self, conn):
        with pytest.raises(ImportException):
            importer.pending_path("naoexiste")


class TestParsedRow:
    def test_ok_e_chave_de_duplicidade(self):
        linha = ParsedRow(line=1, occurred_on="2026-10-01", amount_centavos=1000,
                          type="saida", description="Café")
        assert linha.ok is True
        assert linha.dedupe_key() == ("2026-10-01", 1000, "saida", "cafe")

    def test_erro_invalida(self):
        linha = ParsedRow(line=2, error="valor inválido")
        assert linha.ok is False
        assert linha.as_dict()["ok"] is False


class TestOptions:
    def test_from_form_com_strings(self):
        opts = ImportOptions.from_form({
            "default_type": "saida", "default_status": "previsto",
            "create_categories": "on", "create_items": "false", "skip_duplicates": "1",
            "sheet": "2", "header_row": "3",
        })
        assert opts.create_categories is True
        assert opts.create_items is False
        assert opts.skip_duplicates is True
        assert opts.sheet == 2 and opts.header_row == 3

    def test_from_form_tipo_invalido_cai_no_padrao(self):
        assert ImportOptions.from_form({"default_type": "abc"}).default_type == "saida"
