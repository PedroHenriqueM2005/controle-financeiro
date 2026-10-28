# Arquitetura e decisões técnicas

Este documento explica **por que** o sistema é como é. Serve tanto para quem vai usar
quanto para quem vai contribuir.

## Visão geral

```
                 ┌─────────────────────────────────────────────┐
   navegador ───▶│  FastAPI                                    │
                 │  ├─ app/web/routes_pages.py  (HTML/Jinja2)  │
                 │  ├─ app/web/routes_api.py    (JSON /api)    │
                 │  └─ app/deps.py  conexão por request        │
                 └───────────────┬─────────────────────────────┘
                                 │ funções puras (sem HTTP)
                 ┌───────────────▼─────────────────────────────┐
                 │  app/services                               │
                 │  ledger · catalog · compare · importer      │
                 │  exporter · charts                          │
                 └───────────────┬─────────────────────────────┘
                                 │ SQL
                 ┌───────────────▼─────────────────────────────┐
                 │  app/db.py  →  SQLite (data/financas.db)    │
                 └─────────────────────────────────────────────┘
```

* **`app/services/` não importa FastAPI.** Toda regra de negócio recebe uma conexão
  `sqlite3.Connection` e devolve `dict`/`list`. Isso permite testar sem subir servidor e
  reaproveitar a lógica em scripts ou numa futura CLI.
* **As rotas são finas:** validam entrada (Pydantic), chamam um serviço e formatam a
  resposta. As páginas montam o contexto e renderizam; a API devolve JSON.
* **A mesma API alimenta a interface e scripts externos.** Nada de lógica duplicada entre
  formulário e endpoint.

## Por que SQLite sem ORM

* o banco inteiro é **um arquivo** (`data/financas.db`) — backup é copiar o arquivo;
* os relatórios são agregações (`GROUP BY period/category/item`) que em SQL puro ficam
  explícitas e rápidas; um ORM só acrescentaria uma camada de tradução;
* zero configuração: não há servidor de banco para instalar;
* `PRAGMA journal_mode=WAL` + `foreign_keys=ON` dão concorrência de leitura e integridade
  referencial.

A contrapartida é escrever SQL à mão — por isso ele está concentrado em
`app/services/*.py`, com as consultas grandes nomeadas (`TX_SELECT`, `_ITEM_STATS_SQL`).

### Migrações

`app/db.py` guarda `schema_version` na tabela `meta` e aplica migrações incrementais e
idempotentes (`_migrate`). Adicionar coluna não exige apagar o banco — importante porque o
banco é o dado mais valioso do usuário.

## Por que centavos inteiros

`float` não representa exatamente a maioria dos valores decimais. Somar 30 lançamentos de
`R$ 19,99` em `float` pode dar `599,6999999999`. Armazenando **centavos como inteiro** e
convertendo com `Decimal` só na exibição:

* somas, médias e percentuais são exatos;
* comparações (`estourou = total > budget`) não precisam de tolerância;
* JSON trafega inteiros — sem surpresas de arredondamento no front.

`app/money.py` é o único lugar que sabe converter. Ele também resolve a ambiguidade de
formatos (`1.234` é mil ou um inteiro e 234 centavos?) com heurísticas documentadas e
testadas.

## Previsto × realizado

É o coração do fluxo "salário". O usuário informa o que **pretende** receber e o que
**pretende** pagar; quando acontece, um clique muda o status. Daí saem os indicadores do
painel:

* `saldo_real` = entradas realizadas − saídas realizadas (o que já aconteceu);
* `saldo_projetado` = (entradas realizadas + previstas) − (saídas realizadas + previstas)
  (como o mês deve fechar);
* `comprometido_pct` = saídas realizadas ÷ base de receita (salário previsto ou entradas);
* `sugestao_gasto_diario` = saldo projetado positivo ÷ dias restantes.

O **ciclo** (`cycles`) guarda o salário previsto do mês. Se o usuário nunca o editou
(`expected_locked = 0`), ele é sincronizado automaticamente com a soma dos lançamentos de
categoria "Salário" — assim o primeiro uso já mostra a meta sem configuração. Quando ele
define o valor à mão, a sincronização para.

## Gráficos em SVG no servidor

`app/services/charts.py` gera SVG puro (barras agrupadas, barras horizontais, rosca e
linha). Motivos:

* **sem CDN** — o sistema funciona offline e em rede corporativa bloqueada;
* **sem build de front-end** — não há `npm install`, webpack ou bundling;
* o HTML chega pronto: a página renderiza mesmo com JavaScript desabilitado;
* é testável como string (`assert "<svg" in …`, escape de HTML).

O JavaScript (`app/web/static/app.js`) só assume as **mutações** (criar/editar/excluir,
autocomplete, importação) e o enriquecimento progressivo.

## Importação em duas etapas

`preview()` não grava nada: lê o arquivo, detecta cabeçalho/colunas, aplica as heurísticas
de tipo, status, data e valor, conta duplicadas e devolve uma amostra. Só o `commit()`
grava — e cria um **lote** (`import_batches`) com `source_tag`, permitindo desfazer tudo
depois (`DELETE /api/imports/{id}`).

Heurísticas importantes (todas testadas):

* **modo extrato bancário** exige ≥ 3 negativos e ≥ 30% das linhas — evita que um estorno
  isolado inverta o sentido da planilha inteira;
* **dica de receita** por descrição/categoria recupera entradas em planilhas que só têm
  coluna de valor;
* **deduplicação** por (data, valor, tipo, descrição normalizada) permite reimportar o
  mesmo arquivo sem duplicar o histórico.

Arquivos enviados ficam temporariamente em `data/imports/<token>.<ext>` entre a prévia e o
commit, e são apagados ao concluir.

## Catálogo de itens

`items.normalized_name` (minúsculo, sem acento, espaços colapsados, `UNIQUE`) é a chave de
identidade. Isso significa que importar "CAFE 500G" e lançar "Café 500g" alimenta o mesmo
registro — pré-requisito para comparar preço médio entre meses.

O autocomplete combina duas fontes: itens do catálogo (ordenados por frequência) e
descrições de lançamentos antigos que ainda não viraram item (`origem: "historico"`), o que
torna o sistema útil desde a primeira semana de uso.

## Segurança e escopo

* **uso local, monousuário**: não há autenticação porque o banco é seu e o servidor escuta
  na sua máquina. Para expor na internet, coloque atrás de um proxy com auth
  (Caddy/Traefik/basic auth) — o código não assume usuário logado;
* todo SQL é **parametrizado** (nada de string interpolation com dado do usuário);
* uploads têm limite de tamanho, whitelist de extensão e vão para pasta própria;
* `<dialog>`, `fetch` e SVG são usados com escape de HTML (`charts.esc`, `esc()` no JS);
* nada é enviado para fora: sem telemetria, sem CDN, sem serviços de terceiros.

## Concorrência

Uma conexão SQLite por request (`app/deps.py::get_db`), com commit no sucesso e rollback na
exceção. `check_same_thread=False` é necessário porque endpoints `async` (upload) rodam no
loop enquanto as dependências sync rodam no threadpool. Para uso simultâneo intenso, o
caminho natural é migrar para PostgreSQL — a camada de serviços já isola o SQL o suficiente
para tornar essa troca localizada.

## Testes

238 testes em `tests/`, organizados por camada:

| Arquivo | O que cobre |
|---|---|
| `test_money.py` | parsing/formatação monetária e de datas |
| `test_ledger.py` | lançamentos, ciclos, resumos, orçamentos, recorrentes, filtros |
| `test_catalog.py` | itens, autocomplete, preço médio, alertas, merge |
| `test_compare.py` | comparativos, matriz, acumulado, destaques |
| `test_importer.py` | CSV/XLSX, heurísticas, duplicatas, lotes, desfaazer |
| `test_charts_export.py` | SVG, CSV, XLSX e round-trip do modelo |
| `test_api.py` | todos os endpoints e páginas, com `TestClient` |

Cada teste usa banco em `tmp_path` (fixture `db_path`), então nada toca os seus dados.

## O que ficaria melhor com mais tempo

Ver o **Roadmap** no README. Em resumo: multiusuário, quantidade por item (preço unitário
real), contas/carteiras, agendamento automático de recorrentes e exportação em PDF.
