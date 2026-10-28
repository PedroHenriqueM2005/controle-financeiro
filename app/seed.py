"""Gera uma base de demonstração (3 meses de dados realistas).

Útil para conhecer o sistema sem digitar nada:

    python run.py --demo        # sobe o servidor já com dados
    python -m app.seed --reset  # regrava a base demo no banco padrão
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date

from . import db
from .services import ledger
from .utils import current_period, days_in_month, shift_period

# Valores sempre em CENTAVOS (inteiros). O helper R() mantém a tabela legível:
# R("1.150,00") == 115000.
def R(valor: str) -> int:
    from .money import parse_amount

    centavos = parse_amount(valor)
    assert centavos is not None, valor
    return centavos


SALARIO = R("3.450,00")

GASTOS_FIXOS = [
    # (descrição, categoria, valor, dia de vencimento, é recorrente?)
    ("Aluguel", "Moradia", R("950,00"), 5, True),
    ("Energia elétrica", "Contas (água, luz, internet)", R("165,30"), 10, True),
    ("Internet 400MB", "Contas (água, luz, internet)", R("89,90"), 12, True),
    ("Água", "Contas (água, luz, internet)", R("68,40"), 15, True),
    ("Plano de saúde", "Saúde", R("320,00"), 8, True),
    ("Academia", "Saúde", R("99,90"), 7, True),
    ("Streaming de vídeo", "Assinaturas", R("44,90"), 20, True),
    ("Streaming de música", "Assinaturas", R("21,90"), 20, True),
    ("Celular pós-pago", "Contas (água, luz, internet)", R("54,99"), 18, True),
]

COMPRAS = [
    # (descrição, categoria, faixa de valor, vezes por mês)
    ("Feira / hortifrúti", "Mercado / Alimentação", (R("35,00"), R("75,00")), 3),
    ("Padaria", "Mercado / Alimentação", (R("12,00"), R("32,00")), 6),
    ("Delivery de comida", "Restaurantes e delivery", (R("35,00"), R("75,00")), 2),
    ("Restaurante / almoço fora", "Restaurantes e delivery", (R("25,00"), R("55,00")), 3),
    ("Combustível", "Transporte", (R("140,00"), R("210,00")), 1),
    ("App de transporte", "Transporte", (R("15,00"), R("45,00")), 2),
    ("Farmácia", "Saúde", (R("28,00"), R("120,00")), 1),
    ("Cinema / lazer", "Lazer", (R("35,00"), R("110,00")), 1),
    ("Livro / curso", "Educação", (R("45,00"), R("180,00")), 1),
    ("Roupa / calçado", "Vestuário", (R("70,00"), R("220,00")), 1),
    ("Presente", "Outras saídas", (R("45,00"), R("130,00")), 1),
]

ITENS_MERCADO = [
    # (item, preço base, variação sorteada) — com inflação simulada mês a mês,
    # para o comparativo de preço ter o que mostrar.
    ("Arroz 5kg", R("28,90"), R("8,00")),
    ("Feijão 1kg", R("8,49"), R("1,50")),
    ("Café 500g", R("21,90"), R("4,00")),
    ("Leite integral 1L", R("5,49"), R("0,90")),
    ("Óleo de soja 900ml", R("7,89"), R("1,40")),
    ("Açúcar 1kg", R("4,79"), R("0,80")),
    ("Macarrão 500g", R("4,29"), R("0,90")),
    ("Carne moída 1kg", R("39,90"), R("9,00")),
    ("Frango peito 1kg", R("19,90"), R("4,50")),
    ("Detergente", R("2,79"), R("0,50")),
    ("Sabão em pó 1kg", R("18,90"), R("4,00")),
    ("Papel higiênico 12un", R("24,90"), R("6,00")),
]

METODOS = ["Pix", "Cartão de débito", "Cartão de crédito", "Dinheiro", "Boleto", "Débito automático"]

EXTRAS = [
    ("Freelance — site institucional", "Freelance / Extra", (R("450,00"), R("1.200,00"))),
    ("Reembolso de viagem", "Reembolso", (R("120,00"), R("380,00"))),
    ("Venda de item usado", "Outras entradas", (R("80,00"), R("450,00"))),
]


def _sorteia(rng: random.Random, faixa: tuple[int, int]) -> int:
    return rng.randint(faixa[0], faixa[1])


def populate_demo(conn: sqlite3.Connection, months: int = 4, seed: int = 7) -> int:
    """Cria dados de demonstração nos últimos ``months`` meses. Retorna qtd de lançamentos."""
    db.seed_categories(conn)
    rng = random.Random(seed)
    criados = 0

    for deslocamento in range(months - 1, -1, -1):
        periodo = shift_period(current_period(), -deslocamento)
        ultimo_dia = days_in_month(periodo)
        hoje = date.today()
        limite = ultimo_dia
        if periodo == current_period():
            limite = min(hoje.day, ultimo_dia)

        def dia(preferido: int) -> str:
            return f"{periodo}-{min(max(preferido, 1), limite):02d}"

        # salário (no mês corrente só é "realizado" depois do dia de pagamento)
        if periodo == current_period():
            salario_status = "realizado" if hoje.day >= 5 else "previsto"
        else:
            salario_status = "realizado"
        ledger.create_transaction(
            conn,
            {
                "type": "entrada",
                "status": salario_status,
                "occurred_on": dia(5),
                "amount_centavos": SALARIO,
                "description": "Salário mensal",
                "category_name": "Salário",
                "method": "Transferência",
                "recurring": True,
                "source": "demo",
            },
        )
        criados += 1

        # entrada extra em ~60% dos meses
        if rng.random() < 0.6:
            descricao, categoria, faixa = rng.choice(EXTRAS)
            ledger.create_transaction(
                conn,
                {
                    "type": "entrada",
                    "status": "realizado",
                    "occurred_on": dia(rng.randint(10, max(11, limite))),
                    "amount_centavos": _sorteia(rng, faixa),
                    "description": descricao,
                    "category_name": categoria,
                    "method": "Pix",
                    "source": "demo",
                },
            )
            criados += 1

        # gastos fixos
        for descricao, categoria, valor, dia_pg, recorrente in GASTOS_FIXOS:
            variacao = rng.randint(-int(valor * 0.06), int(valor * 0.09))
            ledger.create_transaction(
                conn,
                {
                    "type": "saida",
                    "status": "realizado" if dia_pg <= limite else "previsto",
                    "occurred_on": dia(dia_pg),
                    "amount_centavos": max(valor + variacao, 100),
                    "description": descricao,
                    "category_name": categoria,
                    "item_name": descricao,
                    "method": rng.choice(METODOS[:3] + ["Débito automático", "Boleto"]),
                    "recurring": recorrente,
                    "source": "demo",
                },
            )
            criados += 1

        # compras variáveis
        for descricao, categoria, faixa, vezes in COMPRAS:
            for _ in range(rng.randint(max(1, vezes - 1), vezes + 1)):
                # gastos eventuais não acontecem todo mês
                chance_pular = 0.70 if categoria in ("Educação", "Vestuário", "Outras saídas", "Lazer", "Saúde") else 0.12
                if rng.random() < chance_pular:
                    continue
                ledger.create_transaction(
                    conn,
                    {
                        "type": "saida",
                        "status": "realizado",
                        "occurred_on": dia(rng.randint(1, ultimo_dia)),
                        "amount_centavos": _sorteia(rng, faixa),
                        "description": descricao,
                        "category_name": categoria,
                        "item_name": descricao,
                        "method": rng.choice(METODOS),
                        "source": "demo",
                    },
                )
                criados += 1

        # itens específicos de mercado (alimentam o comparativo de preço)
        for nome, preco_base, variacao in ITENS_MERCADO:
            for _ in range(rng.randint(1, 2)):
                tendencia = 1 + (months - deslocamento) * 0.012  # inflação simulada
                valor = int(preco_base * tendencia) + rng.randint(-variacao, variacao)
                ledger.create_transaction(
                    conn,
                    {
                        "type": "saida",
                        "status": "realizado",
                        "occurred_on": dia(rng.randint(1, ultimo_dia)),
                        "amount_centavos": max(valor, 100),
                        "description": f"Compra — {nome}",
                        "category_name": "Mercado / Alimentação",
                        "item_name": nome,
                        "method": rng.choice(["Cartão de débito", "Pix", "Cartão de crédito"]),
                        "source": "demo",
                    },
                )
                criados += 1

    # orçamentos por categoria, para os alertas fazerem sentido
    for nome, limite in (
        ("Mercado / Alimentação", R("750,00")),
        ("Restaurantes e delivery", R("300,00")),
        ("Transporte", R("400,00")),
        ("Lazer", R("200,00")),
        ("Moradia", R("1.000,00")),
    ):
        row = conn.execute("SELECT id FROM categories WHERE name = ?", (nome,)).fetchone()
        if row:
            conn.execute("UPDATE categories SET budget_centavos = ? WHERE id = ?", (limite, row["id"]))

    conn.commit()
    return criados


if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="Gera base de demonstração")
    parser.add_argument("--reset", action="store_true", help="apaga o banco antes")
    parser.add_argument("--months", type=int, default=4)
    parser.add_argument("--db", default=None)
    args = parser.parse_args()

    if args.reset:
        db.reset_db(args.db)
    connexao = db.init_db(args.db)
    total = populate_demo(connexao, months=args.months)
    print(f"Base demo criada: {total} lançamentos em {args.months} meses.")
