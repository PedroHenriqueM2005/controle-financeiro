"""Utilidades monetárias.

Regra de ouro do projeto: **nenhum valor em reais trafega como ``float``**.
Tudo é armazenado e calculado em **centavos (inteiro)** e convertido para
``Decimal`` apenas na hora de exibir. Isso elimina os erros clássicos de
ponto flutuante (``0.1 + 0.2 != 0.3``) em somatórios de extrato.

As funções de *parse* aceitam o formato brasileiro (``1.234,56``), o formato
internacional (``1234.56``), valores vindos de planilhas (``float``/``Decimal``)
e notação contábil negativa (``(150,00)``).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Union

Number = Union[int, float, str, Decimal, None]

CENTAVOS = Decimal(100)
_ONE = Decimal(1)

_CURRENCY_NOISE = re.compile(r"(R\$|BRL|US\$|\$|\s)", re.IGNORECASE)


def _group_thousands(digits: str) -> str:
    """Insere o separador de milhar brasileiro a cada 3 dígitos."""
    out, resto = "", digits
    while len(resto) > 3:
        out = "." + resto[-3:] + out
        resto = resto[:-3]
    return resto + out


def _reais_to_centavos(value: Decimal) -> int:
    return int((value * CENTAVOS).quantize(_ONE, rounding=ROUND_HALF_UP))


def _normalize_number_string(raw: str) -> Decimal | None:
    """Converte uma string numérica ambígua em ``Decimal``.

    Heurística (documentada em ``docs/FORMATO_IMPORTACAO.md``):

    * se ``','`` e ``'.'`` aparecem juntos, o **último** é o separador decimal;
    * com um único separador e **exatamente 3 dígitos** depois dele (e 1 a 3
      antes), trata-se de separador de **milhar** — ``1.234`` e ``1,234`` viram
      ``1234``;
    * separador repetido (``1.234.567``) também é milhar;
    * nos demais casos o separador é **decimal** (``12,34`` → ``12.34``).
    """
    s = raw.strip()
    if not s:
        return None

    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        for sep in (",", "."):
            if sep not in s:
                continue
            if s.count(sep) > 1:
                s = s.replace(sep, "")          # 1.234.567 => milhar
            else:
                head, _, tail = s.rpartition(sep)
                eh_milhar = len(tail) == 3 and re.fullmatch(r"[1-9]\d{0,2}", head or "")
                if eh_milhar:
                    s = s.replace(sep, "")      # 1.234 => 1234
                else:
                    s = s.replace(sep, ".")     # 12,34 => 12.34
            break

    s = s.strip()
    if not re.fullmatch(r"\d*\.?\d*", s) or s in (".", ""):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:  # pragma: no cover - defensivo
        return None


def parse_amount(value: Number, default: int | None = None) -> int | None:
    """Interpreta ``value`` como **reais** e devolve **centavos** (int).

    Retorna ``default`` quando o valor é invazio/inválido, o que permite usar a
    função diretamente na leitura de planilhas com células vazias.

    >>> parse_amount("1.234,56")
    123456
    >>> parse_amount("R$ 49,90")
    4990
    >>> parse_amount(12.5)
    1250
    >>> parse_amount("") is None
    True
    """
    if value is None or isinstance(value, bool):
        return default

    if isinstance(value, (int, Decimal)):
        return _reais_to_centavos(Decimal(value))
    if isinstance(value, float):
        return _reais_to_centavos(Decimal(str(value)))

    s = _CURRENCY_NOISE.sub("", str(value)).strip()
    if not s:
        return default

    negative = False
    if s.startswith("(") and s.endswith(")"):  # notação contábil
        negative, s = True, s[1:-1].strip()
    if s.startswith("-"):
        negative, s = True, s[1:]
    elif s.startswith("+"):
        s = s[1:]

    dec = _normalize_number_string(s)
    if dec is None:
        return default

    centavos = _reais_to_centavos(dec)
    return -centavos if negative else centavos


def format_centavos(centavos: int | None, sinal: bool = False) -> str:
    """Formata centavos no padrão brasileiro: ``123456`` → ``1.234,56``."""
    if centavos is None:
        return "—"
    valor = int(centavos)
    negativo = valor < 0
    texto = str(abs(valor)).rjust(3, "0")
    inteiro, cent = texto[:-2], texto[-2:]
    saida = f"{_group_thousands(inteiro)},{cent}"
    prefixo = "-" if negativo else ("+" if sinal and valor > 0 else "")
    return prefixo + saida


def format_brl(centavos: int | None, sinal: bool = False) -> str:
    """Formata como moeda: ``123456`` → ``R$ 1.234,56``; ``-5000`` → ``-R$ 50,00``."""
    if centavos is None:
        return "—"
    valor = int(centavos)
    prefixo = "-" if valor < 0 else ("+" if sinal and valor > 0 else "")
    return f"{prefixo}R$ {format_centavos(abs(valor))}"


def format_qtd(centavos: int | None) -> str:
    """Formata quantidade decimal vinda de planilha (ex.: 2,5 kg)."""
    if centavos is None:
        return "—"
    texto = format_centavos(centavos)
    return texto.rstrip("0").rstrip(",") if texto.endswith("0") else texto


def percent(part: int | None, whole: int | None, digits: int = 1) -> float | None:
    """Porcentagem de ``part`` em relação a ``whole`` (None se não divisível)."""
    if not whole:
        return None
    return round((Decimal(part or 0) / Decimal(whole) * 100), digits).__float__()


def format_percent(value: float | None, digits: int = 1, sinal: bool = True) -> str:
    if value is None:
        return "—"
    texto = f"{value:.{digits}f}".replace(".", ",") + "%"
    if sinal and value > 0:
        return "+" + texto
    return texto


def delta(atual: int | None, anterior: int | None) -> dict:
    """Variação absoluta (centavos) e percentual entre dois valores."""
    a = int(atual or 0)
    b = int(anterior or 0)
    diferenca = a - b
    return {
        "atual": a,
        "anterior": b,
        "delta": diferenca,
        "delta_fmt": format_brl(diferenca, sinal=True),
        "pct": percent(diferenca, b) if b else None,
        "pct_fmt": format_percent(percent(diferenca, b) if b else None),
        "subiu": diferenca > 0,
        "caiu": diferenca < 0,
        "novo": bool(a) and not b,
    }
