.PHONY: help install install-dev run demo dev test test-cov lint clean backup reset

VENV  ?= .venv
PY    := $(VENV)/bin/python
PIP   := $(VENV)/bin/pip
PORT  ?= 8000

help:
	@echo "Comandos disponíveis:"
	@echo "  make install     cria o venv e instala as dependências"
	@echo "  make install-dev instala também pytest e httpx"
	@echo "  make run         sobe o servidor em http://localhost:$(PORT)"
	@echo "  make demo        sobe o servidor com dados de demonstração"
	@echo "  make dev         sobe em modo desenvolvimento (reload)"
	@echo "  make test        roda os testes"
	@echo "  make lint        checagens rápidas (compilação + testes)"
	@echo "  make backup      exporta tudo para backups/financas-AAAA-MM-DD.xlsx"
	@echo "  make reset       APAGA o banco local (data/)"
	@echo "  make clean       remove caches e artefatos"

$(VENV)/bin/python:
	python3 -m venv $(VENV)

install: $(VENV)/bin/python
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

install-dev: install
	$(PIP) install -r requirements-dev.txt

run: install
	$(PY) run.py --port $(PORT)

demo: install
	$(PY) run.py --demo --port $(PORT)

dev: install-dev
	$(PY) run.py --reload --port $(PORT)

test: install-dev
	$(PY) -m pytest

lint: install-dev
	$(PY) -m compileall -q app tests run.py
	$(PY) -m pytest -q

backup: install
	@mkdir -p backups
	@echo "Abra http://localhost:$(PORT)/api/export/xlsx ou use o script abaixo"
	$(PY) - <<'PY'
from datetime import date
from app import db
from app.services import exporter
conn = db.init_db()
nome, conteudo = exporter.xlsx_bytes(conn, None)
destino = f"backups/{date.today():%Y-%m-%d}-{nome}"
open(destino, "wb").write(conteudo)
print("backup salvo em", destino)
PY

reset:
	rm -rf data
	@echo "Banco apagado. Rode 'make demo' para recriar com dados de exemplo."

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage dist build
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	find . -name '*.pyc' -delete
