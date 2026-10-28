"""Testes do catálogo de itens, autocomplete e comparativo de preços."""

from __future__ import annotations

from app.services import catalog, ledger


def _compra(conn, item, valor, data, categoria="Mercado / Alimentação"):
    return ledger.create_transaction(
        conn,
        {
            "type": "saida", "amount": valor, "occurred_on": data,
            "description": f"Compra — {item}", "item_name": item, "category_name": categoria,
        },
    )


class TestEnsureItem:
    def test_mesmo_item_com_acento_e_caixa(self, conn):
        a = catalog.ensure_item(conn, "Café 500g")
        b = catalog.ensure_item(conn, "cafe 500G")
        c = catalog.ensure_item(conn, "  CAFÉ 500G  ")
        assert a == b == c

    def test_nao_cria_quando_create_false(self, conn):
        assert catalog.ensure_item(conn, "Item novo", create=False) is None
        assert catalog.ensure_item(conn, "", create=False) is None

    def test_nome_preserva_acento_original(self, conn):
        item_id = catalog.ensure_item(conn, "Feijão 1kg")
        item = catalog.get_item(conn, item_id)
        assert item["name"] == "Feijão 1kg"

    def test_categoria_herdada_do_lancamento(self, conn):
        cat_id = ledger.ensure_category(conn, "Mercado / Alimentação", "saida")
        tx = ledger.create_transaction(conn, {"type": "saida", "amount": "10", "occurred_on": "2026-10-01",
                                              "description": "x", "item_name": "Arroz", "category_id": cat_id})
        item = catalog.get_item(conn, tx["item_id"])
        assert item["category_id"] == cat_id


class TestEstatisticas:
    def test_preco_medio_min_max_ultimo(self, conn):
        _compra(conn, "Arroz 5kg", "28,90", "2026-08-05")
        _compra(conn, "Arroz 5kg", "31,40", "2026-09-05")
        _compra(conn, "Arroz 5kg", "35,00", "2026-10-05")

        item_id = catalog.ensure_item(conn, "Arroz 5kg")
        item = catalog.get_item(conn, item_id)
        assert item["compras"] == 3
        assert item["preco_min"] == 2890
        assert item["preco_max"] == 3500
        assert item["ultimo_preco"] == 3500
        assert item["total_centavos"] == 2890 + 3140 + 3500
        # média = 3176,67 -> último preço está ~10,2% acima
        assert item["variacao_pct"] > 9
        assert item["alerta_preco"] is True
        assert item["ultima_data"] == "2026-10-05"

    def test_item_sem_compras(self, conn):
        item_id = catalog.create_item(conn, "Item fantasma", unit="un")
        item = catalog.get_item(conn, item_id)
        assert item["compras"] == 0
        assert item["preco_medio_fmt"] is None
        assert item["variacao_pct"] is None

    def test_list_items_filtra_por_busca(self, conn):
        _compra(conn, "Arroz 5kg", "28,90", "2026-10-01")
        _compra(conn, "Café 500g", "21,90", "2026-10-02")
        nomes = [i["name"] for i in catalog.list_items(conn, search="cafe")]
        assert nomes == ["Café 500g"]
        assert len(catalog.list_items(conn)) >= 2
        assert len(catalog.list_items(conn, only_used=True)) == 2

    def test_total_do_mes(self, conn):
        _compra(conn, "Arroz 5kg", "28,90", "2026-09-01")
        _compra(conn, "Arroz 5kg", "30,00", "2026-10-01")
        item = catalog.list_items(conn, search="arroz", period="2026-10")[0]
        assert item["compras_mes"] == 1
        assert item["total_mes"] == 3000


class TestSugestoes:
    def test_ordena_por_frequencia(self, conn):
        for dia in ("2026-08-01", "2026-09-01", "2026-10-01"):
            _compra(conn, "Leite integral", "5,49", dia)
        _compra(conn, "Leite condensado", "7,90", "2026-10-02")
        sugestoes = catalog.suggest(conn, "leite")
        assert sugestoes[0]["name"] == "Leite integral"
        assert sugestoes[0]["compras"] == 3
        assert sugestoes[0]["preco_medio_fmt"] == "R$ 5,49"
        assert sugestoes[0]["category_id"] is not None

    def test_busca_vazia(self, conn):
        assert catalog.suggest(conn, "") == []
        assert catalog.suggest(conn, None) == []

    def test_historico_aparece_quando_catalogo_nao_conhece(self, conn):
        ledger.create_transaction(conn, {"type": "saida", "amount": "50", "occurred_on": "2026-10-01",
                                         "description": "Conserto de bicicleta"}, create_item=False)
        sugestoes = catalog.suggest(conn, "conserto")
        assert any(s["name"] == "Conserto de bicicleta" and s["origem"] == "historico" for s in sugestoes)


class TestVariacaoDePreco:
    def test_avisa_quando_preco_foge_da_media(self, conn):
        _compra(conn, "Arroz 5kg", "28,90", "2026-08-05")
        _compra(conn, "Arroz 5kg", "30,00", "2026-09-05")
        item_id = catalog.ensure_item(conn, "Arroz 5kg")
        r = catalog.price_variation(conn, item_id, 4000)
        assert r["tem_historico"] is True
        assert r["compras"] == 2
        assert r["alerta"] is True
        assert r["diferenca"] > 0

    def test_sem_historico(self, conn):
        item_id = catalog.create_item(conn, "Item novo")
        assert catalog.price_variation(conn, item_id, 1000)["tem_historico"] is False
        assert catalog.price_variation(conn, None, 1000)["tem_historico"] is False

    def test_alertas_mensais(self, conn):
        _compra(conn, "Café 500g", "20,00", "2026-08-05")
        _compra(conn, "Café 500g", "20,50", "2026-09-05")
        _compra(conn, "Café 500g", "26,00", "2026-10-05")
        alertas = catalog.price_alerts(conn, "2026-10")
        assert any(a["name"] == "Café 500g" and a["subiu"] for a in alertas)

    def test_alertas_ignora_quem_tem_uma_compra_soh(self, conn):
        _compra(conn, "Item único", "99,00", "2026-10-05")
        assert catalog.price_alerts(conn, "2026-10") == []


class TestManutencao:
    def test_merge_move_lancamentos(self, conn):
        _compra(conn, "Arroz", "10", "2026-10-01")
        _compra(conn, "Arroz 5kg", "12", "2026-10-02")
        origem = catalog.ensure_item(conn, "Arroz")
        destino = catalog.ensure_item(conn, "Arroz 5kg")
        assert catalog.merge_items(conn, origem, destino) == 1
        item = catalog.get_item(conn, destino)
        assert item["compras"] == 2
        assert catalog.get_item(conn, origem) is None

    def test_delete_preserva_lancamentos(self, conn):
        tx = _compra(conn, "Arroz", "10", "2026-10-01")
        item_id = catalog.ensure_item(conn, "Arroz")
        catalog.delete_item(conn, item_id)
        assert ledger.get_transaction(conn, tx["id"])["item_id"] is None
        assert ledger.count_transactions(conn, period="2026-10") == 1

    def test_rename_atualiza_chave_normalizada(self, conn):
        item_id = catalog.create_item(conn, "Arroz")
        catalog.rename_item(conn, item_id, "Arroz Branco 5kg")
        assert catalog.ensure_item(conn, "arroz branco 5kg") == item_id
