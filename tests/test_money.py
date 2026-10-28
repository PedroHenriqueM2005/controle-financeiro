"""Testes de parsing/formatação monetária e de datas — a base de tudo."""

from __future__ import annotations

import pytest

from app.money import (
    delta,
    format_brl,
    format_centavos,
    format_percent,
    parse_amount,
    percent,
)
from app.utils import (
    days_in_month,
    normalize,
    parse_date,
    period_label,
    period_of,
    period_short,
    previous_period,
    same_period_last_year,
    shift_period,
)


class TestParseAmount:
    @pytest.mark.parametrize(
        "entrada,esperado",
        [
            ("1.234,56", 123456),
            ("R$ 1.234,56", 123456),
            ("1234,56", 123456),
            ("1234.56", 123456),
            ("49,90", 4990),
            ("49.90", 4990),
            ("0,5", 50),
            ("1.234", 123400),      # 3 dígitos após o ponto => milhar
            ("1,234", 123400),      # idem com vírgula
            ("12,34", 1234),
            ("1.234.567,89", 123456789),
            ("1,234,567.89", 123456789),
            ("-50,00", -5000),
            ("(85,00)", -8500),     # notação contábil
            ("+300", 30000),
            ("  250  ", 25000),
            ("3.450", 345000),
        ],
    )
    def test_string_brasileira_e_internacional(self, entrada, esperado):
        assert parse_amount(entrada) == esperado

    @pytest.mark.parametrize("entrada,esperado", [(12, 1200), (12.5, 1250), (0.07, 7), ("1000", 100000)])
    def test_numeros(self, entrada, esperado):
        assert parse_amount(entrada) == esperado

    @pytest.mark.parametrize("entrada", ["", None, "abc", "R$", "---", "12,ab", " "])
    def test_invalidos_devem_none(self, entrada):
        assert parse_amount(entrada) is None

    def test_default_para_invalidos(self):
        assert parse_amount("", default=0) == 0

    def test_arredondamento_meio_centavo(self):
        assert parse_amount("0,005") == 1
        assert parse_amount("1,0049") == 100

    def test_bool_nao_vira_numero(self):
        assert parse_amount(True) is None


class TestFormat:
    @pytest.mark.parametrize(
        "centavos,esperado",
        [(0, "0,00"), (5, "0,05"), (1050, "10,50"), (123456, "1.234,56"), (123456789, "1.234.567,89"),
         (-5000, "-50,00")],
    )
    def test_format_centavos(self, centavos, esperado):
        assert format_centavos(centavos) == esperado

    def test_format_brl(self):
        assert format_brl(123456) == "R$ 1.234,56"
        assert format_brl(-5000) == "-R$ 50,00"
        assert format_brl(5000, sinal=True) == "+R$ 50,00"
        assert format_brl(None) == "—"

    def test_percent(self):
        assert percent(50, 200) == 25.0
        assert percent(1, 3) == 33.3
        assert percent(10, 0) is None

    def test_format_percent(self):
        assert format_percent(12.34) == "+12,3%"
        assert format_percent(-5.0) == "-5,0%"
        assert format_percent(None) == "—"
        assert format_percent(9.0, sinal=False) == "9,0%"

    def test_delta(self):
        d = delta(15000, 10000)
        assert d["delta"] == 5000
        assert d["pct"] == 50.0
        assert d["subiu"] is True
        assert delta(0, 0)["pct"] is None
        assert delta(100, 0)["novo"] is True


class TestDatas:
    def test_period_of(self):
        assert period_of("2026-10-28") == "2026-10"
        assert period_of(parse_date("05/01/2025")) == "2025-01"

    @pytest.mark.parametrize(
        "texto,esperado",
        [("2026-10-28", "2026-10-28"), ("28/10/2026", "2026-10-28"), ("28-10-2026", "2026-10-28")],
    )
    def test_parse_date(self, texto, esperado):
        assert parse_date(texto).isoformat() == esperado

    @pytest.mark.parametrize("texto", ["", None, "abc", "99/99/9999"])
    def test_parse_date_invalida(self, texto):
        assert parse_date(texto) is None

    def test_shift_period(self):
        assert shift_period("2026-01", -1) == "2025-12"
        assert shift_period("2025-12", 1) == "2026-01"
        assert shift_period("2026-10", -12) == "2025-10"
        assert previous_period("2026-03") == "2026-02"
        assert same_period_last_year("2026-03") == "2025-03"

    def test_days_in_month(self):
        assert days_in_month("2026-02") == 28
        assert days_in_month("2024-02") == 29  # bissexto
        assert days_in_month("2026-12") == 31

    def test_labels(self):
        assert period_label("2026-10") == "outubro de 2026"
        assert period_short("2026-10") == "out/26"


class TestNormalize:
    @pytest.mark.parametrize(
        "entrada,esperado",
        [("Café 500g", "cafe 500g"), ("  ALUGUEL  ", "aluguel"), ("Ação   Social", "acao social")],
    )
    def test_normalize(self, entrada, esperado):
        assert normalize(entrada) == esperado

    def test_normalize_vazio(self):
        assert normalize(None) == ""
        assert normalize("   ") == ""
