# Referência da API

Base: `http://localhost:8000/api` · Swagger: `/api/docs` · ReDoc: `/api/redoc` · OpenAPI: `/api/openapi.json`

Convenções:

* valores monetários de **entrada** aceitam string brasileira (`"1.234,56"`), número
  (`1234.56`) ou centavos inteiros (`amount_centavos: 123456`);
* valores monetários de **saída** (respostas) vêm em **centavos** (`amount_centavos`) e
  também já formatados (`valor_fmt`, `total_fmt`…);
* datas: `AAAA-MM-DD` (também aceita `DD/MM/AAAA` na escrita); períodos: `AAAA-MM`;
* erros retornam `{"detail": "mensagem"}` com HTTP 4xx/5xx.

---

## Saúde e metadados

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/health` | status, versão e contagens gerais |
| GET | `/healthz` | `ok` (fora do prefixo `/api`, útil para load balancer) |
| GET | `/api/periods` | mês atual, meses com lançamentos e meses com ciclo |
| GET | `/api/methods` | formas de pagamento padrão + as já usadas |

## Lançamentos

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/transactions` | lista com filtros |
| POST | `/api/transactions` | cria (201) |
| GET | `/api/transactions/{id}` | detalhe |
| PATCH | `/api/transactions/{id}` | edição parcial |
| DELETE | `/api/transactions/{id}` | remove |
| POST | `/api/transactions/{id}/toggle` | alterna previsto ⇄ realizado |

Filtros da listagem: `period`, `type`, `status`, `category_id`, `item_id`, `q`,
`date_from`, `date_to`, `order` (`asc`/`desc`), `page`, `page_size` (máx. 200).

Corpo aceito no POST/PATCH:

```json
{
  "type": "saida",
  "status": "realizado",
  "occurred_on": "2026-10-12",
  "amount": "1.234,56",
  "description": "Mercado do mês",
  "category_name": "Mercado / Alimentação",
  "item_name": "Arroz 5kg",
  "method": "Cartão de débito",
  "recurring": false,
  "note": "compra grande",
  "create_item": true
}
```

`category_id`/`item_id` têm prioridade sobre `category_name`/`item_name`. Se o nome não
existir, a categoria (e o item, quando `create_item` for `true`) é criada automaticamente.

```bash
curl -X POST http://localhost:8000/api/transactions \
  -H 'Content-Type: application/json' \
  -d '{"type":"saida","amount":"42,90","occurred_on":"2026-10-12",
       "description":"Mercado","item_name":"Café 500g","category_name":"Mercado / Alimentação"}'

curl "http://localhost:8000/api/transactions?period=2026-10&type=saida&q=cafe&page_size=10"
curl -X POST http://localhost:8000/api/transactions/42/toggle
curl -X PATCH http://localhost:8000/api/transactions/42 -H 'Content-Type: application/json' -d '{"status":"previsto"}'
curl -X DELETE http://localhost:8000/api/transactions/42
```

Validações que devolvem **422**: valor ausente/zerado/não numérico, data inválida, `type`
ou `status` fora do domínio.

## Resumo e relatórios

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/summary/{period}` | resumo do mês + `graficos` (SVG) + `diario` |
| GET | `/api/compare?a=2026-10&b=2026-09` | comparativo entre dois meses |
| GET | `/api/reports/matrix?months=12&period=2026-10` | matriz categorias × meses |
| GET | `/api/reports/accumulated?period=2026-10&months=12` | saldo acumulado + destaques |

`GET /api/summary/2026-10` devolve, entre outros campos:

```jsonc
{
  "period": "2026-10", "label": "outubro de 2026",
  "salario_previsto": 345000, "salario_previsto_fmt": "R$ 3.450,00",
  "entradas_realizadas": 345000, "entradas_previstas": 80000,
  "saidas_realizadas": 318262, "saidas_previstas": 15000,
  "saldo_real": 26738, "saldo_projetado": -93124,
  "comprometido_pct": 92.3, "comprometido_pct_fmt": "92,3%",
  "media_diaria_gasto": 11366, "sugestao_gasto_diario": 0,
  "dias_corridos": 28, "dias_restantes": 3,
  "categorias": [ { "name": "Moradia", "total": 95000, "budget": 100000,
                    "budget_pct": 95.0, "estourou": false, "quase_estourando": true } ],
  "top_itens": [ { "name": "Arroz 5kg", "qtd": 3, "preco_medio": 3120, "total": 9360 } ],
  "fixos_variaveis": { "fixos": 181500, "variaveis": 136762, "fixos_pct": 57.0 },
  "delta_vs_anterior": { "saidas": 8968, "saidas_pct": 2.9, "saidas_fmt": "+R$ 89,68" },
  "alertas": [ { "nivel": "perigo", "tipo": "orcamento", "titulo": "…", "texto": "…" } ],
  "serie": [ { "period": "2026-05", "entradas": 0, "saidas": 0, "saldo": 0 } ],
  "graficos": { "serie": "<svg…>", "categorias": "<svg…>", "donut": "<svg…>" }
}
```

## Categorias

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/categories?kind=saida&period=2026-10&include_archived=false` | lista com total do mês, limite e % usado |
| POST | `/api/categories` | cria (`name`, `kind`, `color`, `budget` em centavos) |
| PATCH | `/api/categories/{id}` | edita nome, tipo, cor, limite, `archived` |
| DELETE | `/api/categories/{id}` | remove e descategoriza os lançamentos |

## Itens (catálogo)

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/items?q=&category_id=&period=&only_used=&limit=` | lista com estatísticas |
| GET | `/api/items/suggest?q=cafe&limit=8` | autocomplete (catálogo + histórico) |
| GET | `/api/items/{id}` | detalhe + histórico de compras |
| POST | `/api/items` | cria (`name`, `category_id`, `unit`, `note`) |
| PATCH | `/api/items/{id}` | edita |
| DELETE | `/api/items/{id}` | remove do catálogo (lançamentos são preservados) |
| GET | `/api/items/{id}/price-check?amount=27,90` | variação frente ao preço médio |
| GET | `/api/items-price-alerts/{period}` | itens que mudaram de preço no mês |

`price-check` responde algo como:

```json
{ "tem_historico": true, "compras": 4, "media": 2890, "media_fmt": "R$ 28,90",
  "diferenca": -100, "diferenca_fmt": "-R$ 1,00", "variacao_pct": -3.5,
  "variacao_fmt": "-3,5%", "alerta": false, "ultima_compra": "2026-10-02" }
```

## Ciclos (salário previsto)

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/cycles/{period}` | ciclo do mês |
| PUT | `/api/cycles/{period}` | define `expected_income` (centavos), `payday_day`, `note`, `lock` |
| GET | `/api/cycles?limit=24` | histórico de ciclos |
| POST | `/api/cycles/{period}/repeat-recurring` | copia os gastos fixos do mês anterior como previstos |
| GET | `/api/transactions-next-recurring/{period}` | só lista o que seria copiado |

Com `lock: true` o valor fica travado (não é mais sincronizado com os lançamentos de
"Salário"). Com `lock: false` ele passa a espelhar a soma dessas entradas.

## Preferências

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/settings` | preferências efetivas + descrição de cada uma |
| PUT | `/api/settings` | grava uma ou mais preferências |

Hoje existe uma preferência: `auto_recurring` (booleana, **padrão `true`**) — controla se os
gastos fixos do mês são gerados automaticamente. As preferências vivem na tabela `meta`,
portanto acompanham o arquivo do banco (vão junto no backup).

```bash
curl http://localhost:8000/api/settings
# {"settings":{"auto_recurring":true},"descricoes":{...},"atual":"2026-10"}

curl -X PUT http://localhost:8000/api/settings \
  -H 'Content-Type: application/json' -d '{"auto_recurring": false}'
```

Chave desconhecida → **422** (evita que um typo vire preferência fantasma). Corpo sem
nenhuma preferência conhecida → **422**.

## Recorrência automática

| Método | Rota | Descrição |
|---|---|---|
| POST | `/api/recurring/auto/{period}` | gera agora os fixos do mês como *previsto* |
| DELETE | `/api/recurring/auto/{period}` | desfaz a geração automática do mês |
| POST | `/api/cycles/{period}/repeat-recurring` | cópia manual (qualquer mês) |
| GET | `/api/transactions-next-recurring/{period}` | só lista o que seria copiado |

O `POST` responde com `criados`, `total_em_centavos`, `lancamentos` e `motivo`. `motivo` é
`null` quando algo foi criado; caso contrário explica por que não:

| `motivo` | Significado |
|---|---|
| `fora_do_mes_atual` | só o mês em curso recebe geração automática |
| `desativado` | preferência `auto_recurring` desligada (não vale para `force`, usado pela interface) |
| `nada_novo` | o mês anterior não tem fixos, ou eles já estão lançados |

O `DELETE` remove apenas os lançamentos com `source = "recorrente-auto"` daquele mês — o que
você digitou à mão, importou ou copiou pelo botão manual permanece intacto.

```bash
curl -X POST http://localhost:8000/api/recurring/auto/2026-10
# {"period":"2026-10","criados":3,"motivo":null,"total_em_centavos":145990,"lancamentos":[...]}

curl -X DELETE http://localhost:8000/api/recurring/auto/2026-10
# {"ok":true,"period":"2026-10","removidos":3}
```

Período inválido (`2026-13`, `abc`) → **422**.

## Orçamento por categoria

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/budget/{period}` | limite × gasto por categoria no mês |
| POST/PATCH | `/api/categories` | `budget` (centavos) define/remove o limite da categoria |

A resposta traz os totais do mês (`orcado`, `gasto`, `previsto`, `disponivel`, `pct`,
`acima`) e a lista `categorias`, cada uma com `budget`, `gasto` (só realizado), `previsto`,
`disponivel`, `pct`, `acima` e `perto` (≥ 80% do limite). Categorias **sem** limite não
aparecem; categorias com limite e sem gasto aparecem com `gasto: 0`.

É informação pura: nenhum endpoint gera alerta de orçamento (o mesmo conteúdo vem embutido
em `/api/summary/{period}` no campo `orcamento`).

```bash
curl -X PATCH http://localhost:8000/api/categories/9 \
  -H 'Content-Type: application/json' -d '{"budget": 80000}'   # R$ 800,00
curl http://localhost:8000/api/budget/2026-10
```

## Importação

| Método | Rota | Descrição |
|---|---|---|
| POST | `/api/import/upload` | `multipart/form-data` — devolve a prévia |
| POST | `/api/import/preview` | recalcula a prévia com mapeamento/opções diferentes |
| POST | `/api/import/commit` | grava os lançamentos e cria o lote |
| GET | `/api/imports` | lotes já importados |
| DELETE | `/api/imports/{id}` | desfaz o lote inteiro |

Campos do upload: `file` (obrigatório), `default_type`, `default_status`,
`default_category`, `create_categories`, `create_items`, `skip_duplicates`, `sheet`,
`header_row`. O `commit` aceita os mesmos campos mais `token`, `filename` e `mapping`
(`{"date": 0, "amount": 3, …}` devolvido pela prévia).

```bash
curl -X POST http://localhost:8000/api/import/upload \
  -F "file=@exemplos/planilha-gastos-2025.csv" -F "default_type=saida"

curl -X POST http://localhost:8000/api/import/commit \
  -H 'Content-Type: application/json' \
  -d '{"token":"a1b2c3d4e5f60718","filename":"planilha-gastos-2025.csv",
       "mapping":{"date":0,"description":1,"category":2,"amount":3},"default_type":"saida"}'
```

## Exportação

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/export/csv?period=&type=` | lançamentos em CSV (`;`, BOM UTF-8) |
| GET | `/api/export/resumo-csv?months=12` | matriz categorias × meses em CSV |
| GET | `/api/export/xlsx?period=&months=12` | pasta com 5 abas formatadas |
| GET | `/api/export/template` | modelo XLSX em branco (reimportável) |

## Demonstração

| Método | Rota | Descrição |
|---|---|---|
| POST | `/api/demo?months=4` | gera dados de exemplo (útil para conhecer o sistema) |
