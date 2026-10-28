"""Dependências compartilhadas pelas rotas (conexão e templates)."""

from __future__ import annotations

import sqlite3
from typing import Iterator

from fastapi import Request
from fastapi.templating import Jinja2Templates

from . import db


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    """Uma conexão por request, com commit/rollback automático.

    Rotas de leitura podem ignorar o commit; rotas de escrita não precisam se
    preocupar em chamar ``conn.commit()`` manualmente.
    """
    conn = db.connect(request.app.state.db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates
