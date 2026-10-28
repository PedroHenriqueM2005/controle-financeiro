#!/usr/bin/env python3
"""Atalho para subir o servidor.

    python run.py                 # http://localhost:8000
    python run.py --demo          # já com 4 meses de dados de exemplo
    python run.py --port 9000     # outra porta
    python run.py --reload        # recarrega ao editar código (desenvolvimento)
"""

from __future__ import annotations

import argparse

import uvicorn

from app import config, db
from app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Servidor do sistema de finanças pessoais")
    parser.add_argument("--host", default=config.HOST, help=f"interface de escuta (padrão: {config.HOST})")
    parser.add_argument("--port", type=int, default=config.PORT, help=f"porta (padrão: {config.PORT})")
    parser.add_argument("--db", default=None, help="caminho do banco SQLite (padrão: data/financas.db)")
    parser.add_argument("--demo", action="store_true", help="popula dados de demonstração se o banco estiver vazio")
    parser.add_argument("--reset", action="store_true", help="apaga o banco antes de subir (cuidado!)")
    parser.add_argument("--reload", action="store_true", help="modo desenvolvimento com reload")
    args = parser.parse_args()

    if args.reset:
        db.reset_db(args.db)
        print("Banco apagado.")

    conn = db.init_db(args.db)
    vazio = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    conn.close()

    if args.demo and vazio:
        from app.seed import populate_demo

        with db.session(args.db) as conexao:
            total = populate_demo(conexao)
        print(f"Dados de demonstração criados: {total} lançamentos.")

    print()
    print(f"  {config.APP_NAME} v{config.APP_VERSION} — {config.APP_TAGLINE}")
    print(f"  Painel:    http://localhost:{args.port}/")
    print(f"  API docs:  http://localhost:{args.port}/api/docs")
    print(f"  Banco:     {args.db or config.DB_PATH}")
    print()

    if args.reload:
        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=True)
    else:
        uvicorn.run(create_app(args.db), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
