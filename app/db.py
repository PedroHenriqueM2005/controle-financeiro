"""Camada de acesso ao banco (SQLite puro, sem ORM).

Motivos da escolha:

* zero dependência além da stdlib — ``pip install -r requirements.txt`` e roda;
* o banco é **um único arquivo** (``data/financas.db``), fácil de copiar/levar;
* as consultas de relatório (agrupamentos por mês/categoria/item) são SQL
  direto, sem mágica de ORM no caminho.

Os valores monetários são sempre **inteiros em centavos** e as datas são
``TEXT`` no formato ISO (``YYYY-MM-DD``), o que permite ordenação e
comparação lexicográfica corretas.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import config

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    kind            TEXT    NOT NULL DEFAULT 'saida' CHECK (kind IN ('entrada','saida')),
    color           TEXT    NOT NULL DEFAULT '#64748b',
    budget_centavos INTEGER,
    archived        INTEGER NOT NULL DEFAULT 0,
    is_system       INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    category_id     INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    unit            TEXT,
    note            TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- "Ciclo" = mês de referência do salário.
-- Guarda quanto o usuário PRETENDE receber no mês; entradas extras
-- (freelas, reembolsos) são lançamentos avulsos do tipo 'entrada'.
CREATE TABLE IF NOT EXISTS cycles (
    period                   TEXT PRIMARY KEY,          -- YYYY-MM
    expected_income_centavos INTEGER NOT NULL DEFAULT 0,
    payday_day               INTEGER,                   -- dia previsto do pagamento
    expected_locked          INTEGER NOT NULL DEFAULT 0, -- 1 = definido à mão, não auto-sincroniza
    note                     TEXT,
    updated_at               TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS import_batches (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    filename      TEXT    NOT NULL,
    source_tag    TEXT    NOT NULL UNIQUE,
    imported_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    rows_total    INTEGER NOT NULL DEFAULT 0,
    rows_imported INTEGER NOT NULL DEFAULT 0,
    rows_skipped  INTEGER NOT NULL DEFAULT 0,
    first_date    TEXT,
    last_date     TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    type            TEXT    NOT NULL CHECK (type IN ('entrada','saida')),
    status          TEXT    NOT NULL DEFAULT 'realizado' CHECK (status IN ('previsto','realizado')),
    occurred_on     TEXT    NOT NULL,                    -- YYYY-MM-DD
    period          TEXT    NOT NULL,                    -- YYYY-MM (gerado, indexado)
    amount_centavos INTEGER NOT NULL CHECK (amount_centavos >= 0),
    description     TEXT    NOT NULL DEFAULT '',
    category_id     INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    item_id         INTEGER REFERENCES items(id) ON DELETE SET NULL,
    method          TEXT,
    recurring       INTEGER NOT NULL DEFAULT 0,          -- 1 = gasto/recarga mensal recorrente
    source          TEXT    NOT NULL DEFAULT 'manual',   -- manual | import:<arquivo> | demo
    import_id       INTEGER REFERENCES import_batches(id) ON DELETE SET NULL,
    note            TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tx_period      ON transactions(period);
CREATE INDEX IF NOT EXISTS idx_tx_type_period ON transactions(type, period);
CREATE INDEX IF NOT EXISTS idx_tx_date        ON transactions(occurred_on);
CREATE INDEX IF NOT EXISTS idx_tx_category    ON transactions(category_id);
CREATE INDEX IF NOT EXISTS idx_tx_item        ON transactions(item_id);
CREATE INDEX IF NOT EXISTS idx_items_norm     ON items(normalized_name);
"""

# (nome, tipo, cor, é do sistema?)
DEFAULT_CATEGORIES: list[tuple[str, str, str]] = [
    ("Salário", "entrada", "#16a34a"),
    ("Freelance / Extra", "entrada", "#0d9488"),
    ("13º salário", "entrada", "#65a30d"),
    ("Férias", "entrada", "#84cc16"),
    ("Reembolso", "entrada", "#22c55e"),
    ("Rendimentos", "entrada", "#059669"),
    ("Outras entradas", "entrada", "#4ade80"),
    ("Moradia", "saida", "#f97316"),
    ("Mercado / Alimentação", "saida", "#ef4444"),
    ("Contas (água, luz, internet)", "saida", "#eab308"),
    ("Transporte", "saida", "#3b82f6"),
    ("Saúde", "saida", "#ec4899"),
    ("Educação", "saida", "#8b5cf6"),
    ("Assinaturas", "saida", "#a855f7"),
    ("Lazer", "saida", "#06b6d4"),
    ("Vestuário", "saida", "#f43f5e"),
    ("Impostos e taxas", "saida", "#78716c"),
    ("Dívidas e empréstimos", "saida", "#b91c1c"),
    ("Investimento / Reserva", "saida", "#0ea5e9"),
    ("Restaurantes e delivery", "saida", "#fb923c"),
    ("Outras saídas", "saida", "#94a3b8"),
]


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Abre uma conexão nova.

    ``check_same_thread=False`` é necessário porque o FastAPI resolve as
    dependências síncronas em um *threadpool*, enquanto endpoints ``async``
    rodam no loop principal — a conexão pode, portanto, ser criada numa thread
    e usada em outra. Como cada request tem a sua conexão (sem compartilhamento
    concorrente), isso é seguro.
    """
    caminho = Path(db_path) if db_path else config.DB_PATH
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(caminho, timeout=15.0, check_same_thread=False)
    _apply_pragmas(conn)
    return conn


@contextmanager
def session(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Context manager com commit/rollback automático."""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def seed_categories(conn: sqlite3.Connection) -> int:
    """Cria as categorias padrão que ainda não existem. Retorna quantas criou."""
    criadas = 0
    for nome, tipo, cor in DEFAULT_CATEGORIES:
        existe = conn.execute("SELECT 1 FROM categories WHERE name = ?", (nome,)).fetchone()
        if not existe:
            conn.execute(
                "INSERT INTO categories (name, kind, color, is_system) VALUES (?, ?, ?, 1)",
                (nome, tipo, cor),
            )
            criadas += 1
    return criadas


def init_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Cria o esquema (se necessário), aplica migrações e popula categorias."""
    conn = connect(db_path)
    conn.executescript(SCHEMA)
    versao_atual = get_meta(conn, "schema_version")
    if versao_atual is None:
        seed_categories(conn)
        set_meta(conn, "schema_version", str(SCHEMA_VERSION))
        set_meta(conn, "created_at", _now())
    else:
        _migrate(conn, int(versao_atual))
    conn.commit()
    return conn


def _now() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


def _migrate(conn: sqlite3.Connection, versao: int) -> None:
    """Migrações incrementais e idempotentes."""
    colunas = {row["name"] for row in conn.execute("PRAGMA table_info(transactions)")}
    if versao < 2:
        if "status" not in colunas:
            conn.execute("ALTER TABLE transactions ADD COLUMN status TEXT NOT NULL DEFAULT 'realizado'")
        if "recurring" not in colunas:
            conn.execute("ALTER TABLE transactions ADD COLUMN recurring INTEGER NOT NULL DEFAULT 0")
    if versao < 3:
        if "import_id" not in colunas:
            conn.execute("ALTER TABLE transactions ADD COLUMN import_id INTEGER REFERENCES import_batches(id) ON DELETE SET NULL")
        colunas_cat = {row["name"] for row in conn.execute("PRAGMA table_info(categories)")}
        if "budget_centavos" not in colunas_cat:
            conn.execute("ALTER TABLE categories ADD COLUMN budget_centavos INTEGER")
        if "archived" not in colunas_cat:
            conn.execute("ALTER TABLE categories ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
    seed_categories(conn)
    set_meta(conn, "schema_version", str(SCHEMA_VERSION))


def reset_db(db_path: str | Path | None = None) -> None:
    """Apaga os arquivos do banco (usado em testes e no botão de reset)."""
    caminho = Path(db_path) if db_path else config.DB_PATH
    for sufixo in ("", "-wal", "-shm"):
        arquivo = Path(str(caminho) + sufixo)
        if arquivo.exists():
            arquivo.unlink()


# ------------------------------------------------------------------ consultas

def q(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return conn.execute(sql, params).fetchall()


def q1(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> sqlite3.Row | None:
    return conn.execute(sql, params).fetchone()


def scalar(conn: sqlite3.Connection, sql: str, params: tuple = (), default: int = 0) -> int:
    row = q1(conn, sql, params)
    if row is None:
        return default
    valor = row[0]
    return default if valor is None else int(valor)
