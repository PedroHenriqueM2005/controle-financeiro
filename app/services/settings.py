"""Preferências do sistema, guardadas na tabela ``meta`` (chave/valor).

Ficam num módulo próprio porque não são regra de negócio: são interruptores
que mudam o comportamento da aplicação sem tocar no esquema do banco.
Adicionar uma preferência nova custa uma entrada em ``DEFAULTS``.

Valores são persistidos como ``TEXT`` (limitação da tabela ``meta``) e
devolvidos já convertidos para o tipo declarado em ``DEFAULTS``.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .. import db

# chave -> valor padrão. O tipo do padrão define o tipo devolvido por get().
DEFAULTS: dict[str, Any] = {
    # gera automaticamente os lançamentos fixos (previstos) do mês em curso
    "auto_recurring": True,
}

DESCRICOES: dict[str, str] = {
    "auto_recurring": "Criar automaticamente os gastos fixos do mês como “previsto”",
}

_VERDADEIROS = {"1", "true", "on", "yes", "sim", "s"}


class SettingError(ValueError):
    """Chave de preferência inexistente."""


def _converter(chave: str, bruto: Any) -> Any:
    padrao = DEFAULTS.get(chave)
    if isinstance(padrao, bool):
        if isinstance(bruto, bool):
            return bruto
        return str(bruto).strip().lower() in _VERDADEIROS
    if isinstance(padrao, int) and not isinstance(bruto, int):
        return int(bruto)
    return bruto


def get(conn: sqlite3.Connection, chave: str, default: Any = None) -> Any:
    """Lê uma preferência; usa o default declarado (ou o informado) se ausente."""
    if chave not in DEFAULTS and default is None:
        raise SettingError(f"Preferência desconhecida: '{chave}'.")
    bruto = db.get_meta(conn, chave)
    if bruto is None:
        return DEFAULTS.get(chave, default)
    return _converter(chave, bruto)


def is_auto_recurring(conn: sqlite3.Connection) -> bool:
    return bool(get(conn, "auto_recurring"))


def all(conn: sqlite3.Connection) -> dict[str, Any]:  # noqa: A001 - espelha dict.all
    """Todas as preferências, com valores efetivos (default quando não gravadas)."""
    return {chave: get(conn, chave) for chave in DEFAULTS}


def update(conn: sqlite3.Connection, dados: dict[str, Any]) -> dict[str, Any]:
    """Grava as preferências informadas e devolve o conjunto completo.

    Chaves desconhecidas são rejeitadas (evita typo virar preferência fantasma).
    """
    invalidas = sorted(set(dados) - set(DEFAULTS))
    if invalidas:
        raise SettingError(
            "Preferência(s) desconhecida(s): " + ", ".join(invalidas)
            + ". Válidas: " + ", ".join(sorted(DEFAULTS)) + "."
        )
    for chave, valor in dados.items():
        convertido = _converter(chave, valor)
        db.set_meta(conn, chave, "1" if convertido is True else "0" if convertido is False else str(convertido))
    conn.commit()
    return all(conn)


def descricoes() -> dict[str, str]:
    return dict(DESCRICOES)
