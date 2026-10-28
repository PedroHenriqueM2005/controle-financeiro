"""Configuração da aplicação.

Tudo pode ser sobrescrito por variáveis de ambiente, o que permite rodar o
sistema localmente (``data/financas.db``) ou apontar para outro arquivo em
produção/hospedagem sem tocar no código.
"""

from __future__ import annotations

import os
from pathlib import Path

# diretório raiz do projeto (…/controle-financeiro)
BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.getenv("FINANCAS_DATA_DIR", BASE_DIR / "data"))
IMPORT_DIR = DATA_DIR / "imports"

DB_PATH = Path(os.getenv("FINANCAS_DB", DATA_DIR / "financas.db"))

APP_NAME = os.getenv("FINANCAS_APP_NAME", "Saldo")
APP_TAGLINE = "Registro de entradas e saídas do seu dinheiro"
APP_VERSION = "1.0.0"

CURRENCY = os.getenv("FINANCAS_CURRENCY", "BRL")
LOCALE = os.getenv("FINANCAS_LOCALE", "pt-BR")

HOST = os.getenv("FINANCAS_HOST", "0.0.0.0")
PORT = int(os.getenv("FINANCAS_PORT", "8000"))

# tamanho máximo de upload (5 MB é folgado para planilhas domésticas)
MAX_UPLOAD_BYTES = int(os.getenv("FINANCAS_MAX_UPLOAD", 5 * 1024 * 1024))
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xlsm", ".txt"}

PAGE_SIZE = int(os.getenv("FINANCAS_PAGE_SIZE", 25))

DEFAULT_METHODS = [
    "Pix",
    "Dinheiro",
    "Cartão de débito",
    "Cartão de crédito",
    "Boleto",
    "Débito automático",
    "Transferência",
]


def ensure_dirs() -> None:
    """Cria os diretórios de dados (chamado no boot e nos testes)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
