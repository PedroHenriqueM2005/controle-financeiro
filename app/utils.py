"""Funções auxiliares de texto e data compartilhadas pelo projeto."""

from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date, datetime

# ---------------------------------------------------------------- datas

def today() -> date:
    return date.today()


def period_of(day: date | str) -> str:
    """Extrai o período ``YYYY-MM`` de uma data."""
    if isinstance(day, str):
        return day[:7]
    return f"{day.year:04d}-{day.month:02d}"


def current_period() -> str:
    return period_of(today())


def is_valid_period(period: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}", period or ""):
        return False
    mes = int(period[5:7])
    return 1 <= mes <= 12


def parse_period(period: str) -> tuple[int, int]:
    ano, mes = period.split("-")
    return int(ano), int(mes)


def month_range(period: str) -> tuple[date, date]:
    """Primeiro e último dia do mês de ``period``."""
    ano, mes = parse_period(period)
    ultimo = calendar.monthrange(ano, mes)[1]
    return date(ano, mes, 1), date(ano, mes, ultimo)


def days_in_month(period: str) -> int:
    return month_range(period)[1].day


def shift_period(period: str, months: int) -> str:
    """Desloca um período em ``months`` meses (negativo volta no tempo)."""
    ano, mes = parse_period(period)
    indice = (ano * 12 + (mes - 1)) + months
    return f"{indice // 12:04d}-{indice % 12 + 1:02d}"


def previous_period(period: str) -> str:
    return shift_period(period, -1)


def same_period_last_year(period: str) -> str:
    return shift_period(period, -12)


def period_label(period: str) -> str:
    """``2026-10`` → ``outubro de 2026``."""
    if not is_valid_period(period):
        return period
    meses = [
        "janeiro", "fevereiro", "março", "abril", "maio", "junho",
        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
    ]
    ano, mes = parse_period(period)
    return f"{meses[mes - 1]} de {ano}"


def period_short(period: str) -> str:
    """``2026-10`` → ``out/26``."""
    if not is_valid_period(period):
        return period
    abrev = ["jan", "fev", "mar", "abr", "mai", "jun",
             "jul", "ago", "set", "out", "nov", "dez"]
    ano, mes = parse_period(period)
    return f"{abrev[mes - 1]}/{str(ano)[2:]}"


def parse_date(value: str | date | datetime | None) -> date | None:
    """Aceita ``YYYY-MM-DD``, ``DD/MM/YYYY`` e ``DD-MM-YYYY``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    texto = str(value).strip()
    if not texto:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(texto[:10], fmt).date()
        except ValueError:
            continue
    return None


def format_date(day: date | str | None) -> str:
    """``2026-10-28`` → ``28/10/2026``."""
    data = parse_date(day)
    return data.strftime("%d/%m/%Y") if data else "—"


def format_datetime(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return value[:16].replace("T", " ")


def weekday_name(day: date | str | None) -> str:
    nomes = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    data = parse_date(day)
    return nomes[data.weekday()] if data else ""


# ---------------------------------------------------------------- texto

def normalize(text: str | None) -> str:
    """Minúsculas, sem acentos e sem espaços duplos — usado para casar itens/categorias."""
    if not text:
        return ""
    sem_acento = unicodedata.normalize("NFKD", str(text))
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento).strip().lower()


def slug(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize(text)).strip("-")


def truncate(text: str | None, size: int = 60) -> str:
    texto = str(text or "")
    return texto if len(texto) <= size else texto[: size - 1] + "…"


def first_line(text: str | None) -> str:
    return str(text or "").strip().splitlines()[0] if text else ""
