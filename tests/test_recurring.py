"""Geração automática dos gastos fixos + preferência que a controla."""

from __future__ import annotations

import pytest

from app.services import ledger, settings
from app.utils import current_period, days_in_month, previous_period, shift_period


@pytest.fixture()
def fixos(conn):
    """Cenário: mês anterior com 2 contas fixas e 1 gasto variável."""
    atual = current_period()
    anterior = previous_period(atual)
    ledger.create_transaction(conn, {
        "type": "saida", "status": "realizado", "occurred_on": f"{anterior}-05",
        "amount": "1.200,00", "description": "Aluguel", "category_name": "Moradia",
        "item_name": "Aluguel", "recurring": True, "method": "Boleto",
    })
    ledger.create_transaction(conn, {
        "type": "saida", "status": "realizado", "occurred_on": f"{anterior}-15",
        "amount": "89,90", "description": "Streaming", "category_name": "Assinaturas",
        "item_name": "Streaming", "recurring": True,
    })
    ledger.create_transaction(conn, {
        "type": "saida", "status": "realizado", "occurred_on": f"{anterior}-20",
        "amount": "300,00", "description": "Mercado", "category_name": "Mercado / Alimentação",
    })
    return conn


class TestPreferencias:
    def test_auto_recurring_vem_ligado_por_padrao(self, conn):
        assert settings.get(conn, "auto_recurring") is True
        assert settings.is_auto_recurring(conn) is True

    def test_desligar_e_religar(self, conn):
        assert settings.update(conn, {"auto_recurring": False})["auto_recurring"] is False
        assert settings.is_auto_recurring(conn) is False
        # persiste entre chamadas (está gravado na tabela meta)
        assert settings.all(conn)["auto_recurring"] is False
        settings.update(conn, {"auto_recurring": True})
        assert settings.is_auto_recurring(conn) is True

    def test_aceita_valores_textuais(self, conn):
        for bruto in ("1", "true", "on", "sim", True, 1):
            settings.update(conn, {"auto_recurring": bruto})
            assert settings.is_auto_recurring(conn) is True, bruto
        for bruto in ("0", "false", "off", "nao", False, 0):
            settings.update(conn, {"auto_recurring": bruto})
            assert settings.is_auto_recurring(conn) is False, bruto

    def test_chave_desconhecida_e_rejeitada(self, conn):
        with pytest.raises(settings.SettingError):
            settings.update(conn, {"auto_recurrin": True})  # typo
        with pytest.raises(settings.SettingError):
            settings.get(conn, "modo_noturno")

    def test_descricoes_cobrem_todas_as_chaves(self):
        assert set(settings.descricoes()) == set(settings.DEFAULTS)


class TestGeracaoAutomatica:
    def test_copia_soh_os_fixos_como_previsto(self, fixos):
        conn = fixos
        atual = current_period()
        r = ledger.auto_generate_recurring(conn, atual)

        assert r["criados"] == 2
        novos = ledger.list_transactions(conn, period=atual)
        assert {t["description"] for t in novos} == {"Aluguel", "Streaming"}
        assert all(t["status"] == "previsto" for t in novos)
        assert all(t["recurring"] == 1 for t in novos)
        # o gasto variável do mês anterior NÃO é copiado
        assert "Mercado" not in {t["description"] for t in novos}

    def test_preserva_dia_e_categoria_do_original(self, fixos):
        conn = fixos
        atual = current_period()
        ledger.auto_generate_recurring(conn, atual)
        aluguel = next(t for t in ledger.list_transactions(conn, period=atual)
                       if t["description"] == "Aluguel")
        assert aluguel["occurred_on"] == f"{atual}-05"
        assert aluguel["category_name"] == "Moradia"
        assert aluguel["method"] == "Boleto"
        assert aluguel["amount_centavos"] == 120000

    def test_e_idempotente(self, fixos):
        conn = fixos
        atual = current_period()
        assert ledger.auto_generate_recurring(conn, atual)["criados"] == 2
        assert ledger.auto_generate_recurring(conn, atual)["criados"] == 0
        assert ledger.count_auto_generated(conn, atual) == 2
        assert len(ledger.list_transactions(conn, period=atual)) == 2

    def test_nao_sobrescreve_lancamento_ja_existente(self, fixos):
        """Se o usuário já digitou o aluguel do mês, a geração não cria outro."""
        conn = fixos
        atual = current_period()
        ledger.create_transaction(conn, {
            "type": "saida", "status": "realizado", "occurred_on": f"{atual}-05",
            "amount": "1.250,00", "description": "Aluguel", "category_name": "Moradia",
        })
        r = ledger.auto_generate_recurring(conn, atual)
        assert r["criados"] == 1  # só o Streaming
        alugueis = [t for t in ledger.list_transactions(conn, period=atual)
                    if t["description"] == "Aluguel"]
        assert len(alugueis) == 1
        assert alugueis[0]["amount_centavos"] == 125000
        assert alugueis[0]["status"] == "realizado"

    def test_valor_mudou_nao_duplica(self, conn):
        """Aluguel reajustado: você lançou R$ 1.250, o fixo antigo era R$ 1.200."""
        anterior = previous_period(current_period())
        atual = current_period()
        ledger.create_transaction(conn, {
            "type": "saida", "occurred_on": f"{anterior}-05", "amount": "1.200,00",
            "description": "Aluguel", "category_name": "Moradia", "recurring": True,
        })
        ledger.create_transaction(conn, {
            "type": "saida", "occurred_on": f"{atual}-05", "amount": "1.250,00",
            "description": "Aluguel", "category_name": "Moradia",
        })
        assert ledger.auto_generate_recurring(conn, atual)["criados"] == 0
        alugueis = [t for t in ledger.list_transactions(conn, period=atual)
                    if t["description"] == "Aluguel"]
        assert len(alugueis) == 1 and alugueis[0]["amount_centavos"] == 125000

    def test_duas_contas_iguais_na_origem_nao_duplicam_o_destino(self, conn):
        """Se o mês já tem a conta, nada de criar uma segunda — mesmo com 2 na origem."""
        anterior = previous_period(current_period())
        atual = current_period()
        for dia, valor in (("05", "1.200,00"), ("20", "950,00")):
            ledger.create_transaction(conn, {
                "type": "saida", "occurred_on": f"{anterior}-{dia}", "amount": valor,
                "description": "Aluguel", "category_name": "Moradia", "recurring": True,
            })
        ledger.create_transaction(conn, {
            "type": "saida", "occurred_on": f"{atual}-05", "amount": "1.200,00",
            "description": "Aluguel", "category_name": "Moradia",
        })
        ledger.auto_generate_recurring(conn, atual)
        assert len([t for t in ledger.list_transactions(conn, period=atual)
                    if t["description"] == "Aluguel"]) == 1

    def test_contas_distintas_de_mesmo_tipo_sao_copiadas(self, conn):
        """Descrições diferentes = contas diferentes, ainda que na mesma categoria."""
        anterior = previous_period(current_period())
        atual = current_period()
        for desc, valor in (("Internet casa", "120,00"), ("Internet escritório", "200,00")):
            ledger.create_transaction(conn, {
                "type": "saida", "occurred_on": f"{anterior}-10", "amount": valor,
                "description": desc, "category_name": "Contas (água, luz, internet)", "recurring": True,
            })
        assert ledger.auto_generate_recurring(conn, atual)["criados"] == 2
        copiadas = {t["description"] for t in ledger.list_transactions(conn, period=atual)}
        assert copiadas == {"Internet casa", "Internet escritório"}

    def test_mesma_descricao_em_categoria_diferente_e_outra_conta(self, conn):
        anterior = previous_period(current_period())
        atual = current_period()
        ledger.create_transaction(conn, {
            "type": "saida", "occurred_on": f"{anterior}-10", "amount": "80,00",
            "description": "Mensalidade", "category_name": "Educação", "recurring": True,
        })
        ledger.create_transaction(conn, {
            "type": "saida", "occurred_on": f"{atual}-10", "amount": "80,00",
            "description": "Mensalidade", "category_name": "Saúde",
        })
        # a de Educação ainda não está no mês: é copiada; a de Saúde já estava digitada
        assert ledger.auto_generate_recurring(conn, atual)["criados"] == 1

    def test_copia_e_acentuada_insensivel(self, conn):
        """'AGUA' do banco antigo casa com 'Água' — normalização na identidade."""
        anterior = previous_period(current_period())
        atual = current_period()
        ledger.create_transaction(conn, {
            "type": "saida", "occurred_on": f"{anterior}-08", "amount": "65,00",
            "description": "Água", "category_name": "Contas (água, luz, internet)", "recurring": True,
        })
        ledger.create_transaction(conn, {
            "type": "saida", "occurred_on": f"{atual}-08", "amount": "71,00",
            "description": "AGUA", "category_name": "Contas (água, luz, internet)",
        })
        assert ledger.auto_generate_recurring(conn, atual)["criados"] == 0

    def test_soh_atua_no_mes_atual(self, fixos):
        conn = fixos
        passado = shift_period(current_period(), -2)
        futuro = shift_period(current_period(), 2)
        assert ledger.auto_generate_recurring(conn, passado)["motivo"] == "fora_do_mes_atual"
        assert ledger.auto_generate_recurring(conn, futuro)["motivo"] == "fora_do_mes_atual"
        assert ledger.count_auto_generated(conn, passado) == 0
        assert ledger.count_auto_generated(conn, futuro) == 0

    def test_respeita_a_preferencia_desligada(self, fixos):
        conn = fixos
        atual = current_period()
        settings.update(conn, {"auto_recurring": False})
        r = ledger.auto_generate_recurring(conn, atual)
        assert r["criados"] == 0 and r["motivo"] == "desativado"
        # force=True é o botão "gerar agora": funciona mesmo desligado
        r = ledger.auto_generate_recurring(conn, atual, force=True)
        assert r["criados"] == 2 and r["motivo"] is None

    def test_desfazer_remove_apenas_o_que_foi_automatico(self, fixos):
        conn = fixos
        atual = current_period()
        ledger.auto_generate_recurring(conn, atual)
        ledger.create_transaction(conn, {
            "type": "saida", "status": "realizado", "occurred_on": f"{atual}-10",
            "amount": "45,00", "description": "Farmácia", "category_name": "Saúde",
        })
        assert ledger.undo_auto_generated(conn, atual) == 2
        restantes = ledger.list_transactions(conn, period=atual)
        assert [t["description"] for t in restantes] == ["Farmácia"]

    def test_corrente_se_sustenta_mes_a_mes(self, conn):
        """Previsto gerado também é fixo → o mês seguinte o herda."""
        base = shift_period(current_period(), -2)
        ledger.create_transaction(conn, {
            "type": "saida", "status": "realizado", "occurred_on": f"{base}-10",
            "amount": "120,00", "description": "Internet", "category_name": "Contas (água, luz, internet)",
            "recurring": True,
        })
        mes1 = shift_period(base, 1)
        mes2 = shift_period(base, 2)
        assert ledger.duplicate_recurring(conn, mes1) == 1
        assert ledger.duplicate_recurring(conn, mes2) == 1
        assert [t["description"] for t in ledger.list_transactions(conn, period=mes2)] == ["Internet"]

    def test_cancelar_um_fixo_interrompe_a_corrente(self, conn):
        anterior = previous_period(current_period())
        atual = current_period()
        ledger.create_transaction(conn, {
            "type": "saida", "occurred_on": f"{anterior}-08", "amount": "60,00",
            "description": "Academia", "category_name": "Saúde", "recurring": True,
        })
        assert ledger.auto_generate_recurring(conn, atual)["criados"] == 1
        gerado = ledger.list_transactions(conn, period=atual)[0]
        ledger.delete_transaction(conn, gerado["id"])                  # cancelou a academia
        assert ledger.duplicate_recurring(conn, shift_period(atual, 1)) == 0

    def test_dia_31_e_ajustado_para_o_fim_do_mes(self, conn):
        ledger.create_transaction(conn, {
            "type": "saida", "occurred_on": "2026-01-31", "amount": "100,00",
            "description": "Assinatura", "category_name": "Assinaturas", "recurring": True,
        })
        ledger.duplicate_recurring(conn, "2026-02")
        tx = ledger.list_transactions(conn, period="2026-02")[0]
        assert tx["occurred_on"] == f"2026-02-{days_in_month('2026-02'):02d}"

    def test_sem_fixos_no_mes_anterior_nao_faz_nada(self, conn):
        r = ledger.auto_generate_recurring(conn, current_period())
        assert r["criados"] == 0 and r["motivo"] == "nada_novo"


class TestResumoDosFixos:
    def test_totais_separam_pago_e_previsto(self, fixos):
        conn = fixos
        atual = current_period()
        ledger.auto_generate_recurring(conn, atual)
        resumo = ledger.recurring_summary(conn, atual)

        assert resumo["qtd"] == 2
        assert resumo["total"] == 120000 + 8990
        assert resumo["previsto"] == resumo["total"]
        assert resumo["realizado"] == 0
        assert resumo["gerados_auto"] == 2

        # pagando o aluguel, o realizado sobe e o previsto cai
        aluguel = next(t for t in resumo["lancamentos"] if t["description"] == "Aluguel")
        ledger.toggle_status(conn, aluguel["id"])
        resumo = ledger.recurring_summary(conn, atual)
        assert resumo["realizado"] == 120000
        assert resumo["previsto"] == 8990
        assert resumo["qtd_realizadas"] == 1 and resumo["qtd_previstas"] == 1

    def test_pendentes_aponta_o_que_ainda_falta_copiar(self, fixos):
        conn = fixos
        atual = current_period()
        assert ledger.recurring_summary(conn, atual)["pendentes"] == 2
        ledger.auto_generate_recurring(conn, atual)
        assert ledger.recurring_summary(conn, atual)["pendentes"] == 0

    def test_lista_vazia_tem_totais_zerados(self, conn):
        r = ledger.recurring_summary(conn, current_period())
        assert r["lancamentos"] == [] and r["qtd"] == 0 and r["total"] == 0
        assert r["total_fmt"] == "R$ 0,00"


class TestApiRecorrentes:
    def test_settings_get_put(self, client):
        r = client.get("/api/settings")
        assert r.status_code == 200
        corpo = r.json()
        assert corpo["settings"]["auto_recurring"] is True
        assert "auto_recurring" in corpo["descricoes"]

        r = client.put("/api/settings", json={"auto_recurring": False})
        assert r.status_code == 200 and r.json()["settings"]["auto_recurring"] is False
        assert client.get("/api/settings").json()["settings"]["auto_recurring"] is False

    def test_settings_rejeita_corpo_vazio_e_chave_invalida(self, client):
        assert client.put("/api/settings", json={}).status_code == 422
        assert client.put("/api/settings", json={"nao_existe": True}).status_code == 422

    def test_gerar_e_desfazer_pela_api(self, client):
        anterior = previous_period(current_period())
        client.post("/api/transactions", json={
            "type": "saida", "occurred_on": f"{anterior}-05", "amount": "1.200,00",
            "description": "Aluguel", "category_name": "Moradia", "recurring": True,
        })
        atual = current_period()
        r = client.post(f"/api/recurring/auto/{atual}")
        assert r.status_code == 200
        corpo = r.json()
        assert corpo["criados"] == 1 and corpo["total_em_centavos"] == 120000

        # segunda chamada não duplica
        assert client.post(f"/api/recurring/auto/{atual}").json()["criados"] == 0

        r = client.delete(f"/api/recurring/auto/{atual}")
        assert r.status_code == 200 and r.json()["removidos"] == 1
        assert client.get(f"/api/transactions?period={atual}").json()["total"] == 0

    def test_gerar_para_mes_passado_explica_o_motivo(self, client):
        r = client.post(f"/api/recurring/auto/{shift_period(current_period(), -3)}")
        assert r.status_code == 200
        assert r.json() == {"period": shift_period(current_period(), -3), "criados": 0,
                            "motivo": "fora_do_mes_atual", "total_em_centavos": 0,
                            "lancamentos": []}

    def test_periodo_invalido_da_422(self, client):
        assert client.post("/api/recurring/auto/2026-13").status_code == 422
        assert client.delete("/api/recurring/auto/abc").status_code == 422

    def test_painel_dispara_a_geracao(self, client):
        """Abrir o painel já deixa os fixos do mês lançados — é o 'todo mês'."""
        anterior = previous_period(current_period())
        client.post("/api/transactions", json={
            "type": "saida", "occurred_on": f"{anterior}-10", "amount": "89,90",
            "description": "Streaming", "category_name": "Assinaturas", "recurring": True,
        })
        pagina = client.get("/")
        assert pagina.status_code == 200
        assert "conta(s) fixa(s) lançada(s) automaticamente" in pagina.text
        assert "Streaming" in pagina.text

        r = client.get(f"/api/transactions?period={current_period()}").json()
        assert r["total"] == 1 and r["items"][0]["status"] == "previsto"
        assert r["items"][0]["source"] == ledger.SOURCE_AUTO_RECORRENTE

    def test_painel_nao_gera_quando_a_preferencia_esta_desligada(self, client):
        anterior = previous_period(current_period())
        client.post("/api/transactions", json={
            "type": "saida", "occurred_on": f"{anterior}-10", "amount": "89,90",
            "description": "Streaming", "category_name": "Assinaturas", "recurring": True,
        })
        client.put("/api/settings", json={"auto_recurring": False})
        pagina = client.get("/")
        assert pagina.status_code == 200
        assert "lançada(s) automaticamente" not in pagina.text
        assert client.get(f"/api/transactions?period={current_period()}").json()["total"] == 0

    def test_configuracoes_mostra_preferencia_e_fixos(self, client):
        pagina = client.get("/configuracoes")
        assert pagina.status_code == 200
        assert 'name="auto_recurring"' in pagina.text
        assert "Lançamentos fixos automáticos" in pagina.text
        assert "Gerar fixos de" in pagina.text
