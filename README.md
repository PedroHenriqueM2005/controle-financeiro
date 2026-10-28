# Saldo — controle de entradas e saídas do seu dinheiro

Sistema web local para registrar **o dinheiro que entra e o que sai** ao longo do mês,
pensado para quem vive de salário: você informa quanto **recebeu** ou quanto **pretende
receber**, lança os gastos (de uma vez ou dia a dia), pode **acrescentar novas entradas**
quando surge um dinheiro extra no meio do mês e compara tudo com os **meses/planilhas
anteriores**.

Feito em **Python + FastAPI + SQLite**, com interface server-rendered (Jinja2) e
JavaScript puro — **sem CDN, sem build, sem npm, sem Docker obrigatório**. Clone, instale
as dependências e rode.

```bash
git clone https://github.com/PedroHenriqueM2005/controle-financeiro.git
cd controle-financeiro
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py --demo                                  # http://localhost:8000
```

> `--demo` popula 4 meses de dados realistas para você conhecer o sistema. Sem a flag,
> o banco começa vazio.

### Requisitos

* **Python 3.10 ou mais novo** (recomendado 3.11+, que é o que o CI testa). Confira com
  `python --version` — no Windows, se não responder, tente `py -3 --version`.
* **Git** (ou baixe o ZIP do repositório em *Code → Download ZIP* e descompacte).
* Nada além disso: não precisa de Node, npm, Docker nem banco de servidor. O SQLite é um
  arquivo criado automaticamente em `data/financas.db`.

No **Windows**, `make` não vem instalado — use os comandos `python`/`pip` acima (a ativação
do ambiente virtual é `.venv\Scripts\activate`, e não `source .venv/bin/activate`).
Os atalhos `make` são opcionais e funcionam em Linux/macOS.

### No dia a dia

```bash
cd controle-financeiro
.venv\Scripts\activate        # Linux/macOS: source .venv/bin/activate
python run.py                  # abre em http://localhost:8000
```

Para parar, `Ctrl+C`. Seus dados ficam em `data/financas.db` — **copie esse arquivo** para
fazer backup, e não apague a pasta `data/` (é o seu histórico inteiro).

| Situação | Comando |
|---|---|
| Outra porta (a 8000 está ocupada) | `python run.py --port 8080` |
| Banco em outro lugar | `python run.py --db D:\financas\minhas-contas.db` |
| Recomeçar do zero | `python run.py --reset` **(apaga tudo)** |
| Recarregar ao editar o código | `python run.py --reload` |

---

## O que ele resolve

| Necessidade | Como o sistema atende |
|---|---|
| "Quero registrar o salário que recebi **ou que vou receber**" | Todo lançamento tem status **previsto** ou **realizado**. O salário previsto cria a meta do mês; quando o dinheiro cai, um clique muda para realizado. |
| "Recebi um extra no meio do mês" | Basta lançar uma nova **entrada** (freelance, reembolso, 13º). Ela soma por cima do salário previsto e recalcula saldo e projeção. |
| "Lancei tudo de uma vez **ou** dia a dia" | Formulário rápido no painel (com `Ctrl+Enter`), tela de lançamentos com filtros e paginação, e importação em lote de planilha. |
| "Quero comparar com as **planilhas antigas**" | Importador de CSV/XLSX que reconhece cabeçalhos em português ou inglês; os dados entram no mesmo banco e viram comparativos mês × mês, categoria × categoria e item × item. |
| "Quero **registrar gastos novos de itens**" | Catálogo de itens com autocomplete: ao digitar, aparecem o preço médio histórico, a última compra e a quantidade de vezes. Itens novos podem ser criados no próprio lançamento (ou automaticamente na importação). |
| "O preço subiu?" | Alerta automático quando o preço médio do item no mês foge ±10% do histórico, e aviso imediato no formulário ao digitar um valor fora da média. |
| "Estou gastando rápido demais?" | Painel com % da receita comprometida × % do mês decorrido, média de gasto diário e **quanto você ainda pode gastar por dia** até o fim do mês. |
| "Teto por categoria" | Limite mensal por categoria com comparativo **informativo**: barra de progresso, quanto já saiu, quanto ainda está previsto e quanto resta. Sem alarme — aparece no painel para você acompanhar. |
| "Contas que se repetem todo mês" | Marque um lançamento como **“Todo mês (fixo)”** e ele é lançado sozinho como *previsto* no mês seguinte, ao abrir o painel. Nada de cron: a geração acontece quando você usa o sistema, nunca reescreve mês passado e dá para desfazer. |

---

## Telas

* **Painel** (`/`) — cartões de salário previsto, recebido, gasto e saldo; barras de
  progresso; alertas; formulário rápido com autocomplete; gráfico de 6 meses; gastos por
  categoria; orçamentos; itens mais caros e preços em movimento; últimos lançamentos.
* **Lançamentos** (`/lancamentos`) — tabela com filtros por mês, tipo, situação, categoria
  e busca textual; edição em modal; alternar previsto/realizado com um clique; paginação.
* **Itens** (`/itens`) — catálogo com compras, preço médio, faixa mín–máx, último preço,
  variação e total no mês; cadastro, edição e remoção (preservando o histórico).
* **Relatórios** (`/relatorios`) — comparativo A × B (categorias, itens com preço médio,
  formas de pagamento, origem das entradas), matriz **categorias × meses**, evolução em
  12 meses, saldo acumulado, melhor/pior mês e taxa de poupança.
* **Importar planilha** (`/importar`) — upload, prévia com mapeamento de colunas
  ajustável, contagem de linhas válidas/duplicadas/inválidas, meses detectados,
  confirmação e **desfazer** importação por lote.
* **Configurações** (`/configuracoes`) — salário previsto e dia de pagamento de cada mês,
  **preferência da geração automática dos fixos** (com a lista deles e botões de gerar/desfazer),
  categorias com limite de gasto, cores, arquivamento, estatísticas do banco e backups.

---

## Conceitos do modelo de dados

```
cycles (mês)            1 ── n   transactions
categories 1 ── n       transactions        n ── 1 items
import_batches 1 ── n   transactions
```

* **transaction** — `type` (`entrada`/`saida`), `status` (`previsto`/`realizado`),
  `occurred_on` (data), `period` (`YYYY-MM`, derivado e indexado), `amount_centavos`
  (**inteiro**), `description`, `category_id`, `item_id`, `method`, `recurring`,
  `source` (`manual`, `import:arquivo`, `demo`, `recorrente:mês`, `recorrente-auto`) e
  `import_id`. O `source` é o que permite desfazer em bloco uma importação ou uma geração
  automática sem tocar nos lançamentos feitos à mão.
* **cycle** — salário previsto do mês, dia de pagamento e observação. Se você não definir
  manualmente, o sistema sincroniza com os lançamentos da categoria "Salário".
* **category** — nome, tipo, cor e `budget_centavos` (limite mensal opcional).
* **item** — nome + `normalized_name` único (sem acento e em minúsculas), categoria,
  unidade e observação. É o que permite casar "Café 500g", "cafe 500g" e "CAFÉ 500G".
* **import_batch** — cada importação vira um lote rastreável e reversível.
* **meta** — chave/valor com as preferências do sistema (hoje, `auto_recurring`) e o
  `schema_version` das migrações.

**Dinheiro nunca é `float`:** tudo é armazenado e somado em **centavos (inteiro)** e
convertido em `Decimal` apenas para exibir. Somatórios de extrato não acumulam erro de
ponto flutuante.

---

## Estrutura do projeto

```
controle-financeiro/
├── run.py                     # atalho para subir o servidor (--demo, --port, --reload, --reset)
├── requirements.txt           # fastapi, uvicorn, jinja2, python-multipart, openpyxl
├── requirements-dev.txt       # + pytest, httpx
├── pytest.ini
├── Makefile                   # make install / run / demo / test / clean
├── app/
│   ├── main.py                # create_app(): lifespan, static, routers, handlers de erro
│   ├── config.py              # tudo sobrescrevível por variáveis de ambiente
│   ├── db.py                  # esquema SQL, migrações, categorias padrão, helpers
│   ├── deps.py                # conexão por request (commit/rollback automático)
│   ├── money.py               # parse/format de valores em centavos (pt-BR e internacional)
│   ├── utils.py               # datas, períodos, normalização de texto
│   ├── seed.py                # base de demonstração
│   ├── services/
│   │   ├── ledger.py          # lançamentos, categorias, ciclos, resumos, orçamento, fixos
│   │   ├── settings.py        # preferências (chave/valor na tabela meta)
│   │   ├── catalog.py         # itens, autocomplete, preço médio, alertas de preço
│   │   ├── compare.py         # mês × mês, matriz categorias × meses, acumulado
│   │   ├── importer.py        # CSV/XLSX: detecção de colunas, heurísticas, lotes
│   │   ├── exporter.py        # CSV (BOM + ;) e XLSX com 5 abas, incluindo modelo
│   │   └── charts.py          # gráficos SVG gerados no servidor (sem biblioteca externa)
│   └── web/
│       ├── routes_pages.py    # páginas HTML
│       ├── routes_api.py      # API JSON (/api)
│       ├── templates/         # base, macros, 6 páginas
│       └── static/            # app.css e app.js (JS puro, sem dependências)
├── docs/
│   ├── API.md                 # referência de endpoints com exemplos curl
│   ├── FORMATO_IMPORTACAO.md  # como preparar a planilha e o que é reconhecido
│   └── ARQUITETURA.md         # decisões técnicas e porquês
├── exemplos/
│   └── planilha-gastos-2025.csv   # planilha de exemplo para testar a importação
└── tests/                     # 295 testes (unidades + API + import/export)
```

---

## Importação de planilhas antigas

Aceita `.csv`, `.xlsx` e `.xlsm` (até 5 MB). O reconhecimento é por apelidos de coluna,
então estas planilhas funcionam sem ajuste:

```
Data;Descrição;Categoria;Valor;Forma de pagamento;Status
date,description,amount                       (extrato em inglês)
Data | Histórico | Valor (R$)                 (extrato bancário brasileiro)
Data,Item,Valor                               (planilha caseira sem categoria)
```

* **Números:** `1.234,56`, `R$ 1.234,56`, `1234.56`, `(150,00)` (negativo contábil).
* **Datas:** `05/10/2026`, `2026-10-05`, `05-10-2026` e número de série do Excel.
* **Tipo:** se houver coluna `Tipo`/`D/C`/`Natureza`, ela manda. Sem ela: valor negativo é
  saída; se o arquivo parecer **extrato bancário** (≥ 3 valores negativos e ≥ 30% das
  linhas), positivo vira entrada; caso contrário vale o **tipo padrão** do formulário.
  Descrição/categoria que combine com receita conhecida ("Salário", "Freelance",
  "Reembolso"…) também é classificada como entrada.
* **Status:** `Pago`/`Recebido`/`Quitado` → realizado; `Pendente`/`A pagar`/`Agendado` →
  previsto.
* **Duplicadas:** linhas com mesma data, valor, tipo e descrição já existentes são
  ignoradas (dá para desligar).
* **Categorias e itens novos** são criados automaticamente (dá para desligar).
* **Reversível:** cada importação é um lote; o botão ↺ remove todos os lançamentos dele.

Detalhes e exemplos em [`docs/FORMATO_IMPORTACAO.md`](docs/FORMATO_IMPORTACAO.md).
Teste agora com [`exemplos/planilha-gastos-2025.csv`](exemplos/planilha-gastos-2025.csv).

---

## Contas fixas automáticas

Marque a caixa **“Todo mês (fixo)”** ao lançar aluguel, internet, streaming, academia…
No mês seguinte, ao abrir o painel, essas contas já estão lançadas como **previsto**:

1. a geração olha só para o **mês em curso** — meses fechados nunca são alterados e nada é
   criado para o futuro;
2. ela compara pela **identidade da conta** (descrição normalizada + categoria), não pelo
   valor: se o aluguel subiu de R$ 1.200 para R$ 1.250 e você já lançou o novo, não aparece
   um segundo aluguel;
3. cada geração é **idempotente** (abrir o painel dez vezes não cria dez cópias) e marcada
   com `source = recorrente-auto`, então o botão **Desfazer** remove exatamente o que foi
   criado automaticamente, sem tocar no que você digitou;
4. se você cancelar uma conta, é só excluí-la: a corrente para de copiá-la nos meses
   seguintes.

Liga/desliga em **Configurações → Lançamentos fixos automáticos** (preferência
`auto_recurring`, gravada no próprio banco). O botão **“Gerar fixos de {mês} agora”** força
a geração mesmo com a preferência desligada.

> Entradas recorrentes não são copiadas de propósito: o salário vive no campo
> *salário previsto* do ciclo mensal, que é o lugar certo para ajustá-lo.

## Orçamento por categoria (informativo)

Em **Configurações → Categorias de saída** você informa o limite mensal de cada categoria.
O painel mostra, sem alarmes:

* total **orçado × gasto** do mês e quanto ainda está disponível;
* por categoria: o que já saiu (**realizado**), o que ainda vai sair (**previsto**),
  percentual do limite e saldo restante — uma categoria orçada mas sem gasto aparece com
  R$ 0,00 em vez de sumir;
* ordenação pelo percentual mais comprometido primeiro.

A barra usa apenas o que já foi **realizado** (dinheiro que efetivamente saiu); o previsto
aparece como texto ao lado, para não parecer que você já gastou o que ainda vai gastar.

---

## API

Documentação interativa (Swagger) em **`/api/docs`** e ReDoc em `/api/redoc`.
Resumo dos principais endpoints — detalhes e exemplos `curl` em [`docs/API.md`](docs/API.md):

```
GET    /api/summary/{period}        resumo do mês (com gráficos SVG)
GET    /api/compare?a=&b=           comparativo entre dois meses
GET    /api/reports/matrix          matriz categorias × meses
GET    /api/transactions            lista com filtros e paginação
POST   /api/transactions            cria lançamento
PATCH  /api/transactions/{id}       edita
DELETE /api/transactions/{id}       remove
POST   /api/transactions/{id}/toggle  previsto ⇄ realizado
GET    /api/items/suggest?q=        autocomplete do catálogo
GET    /api/items/{id}/price-check?amount=   variação frente ao preço médio
GET    /api/categories · POST · PATCH · DELETE
PUT    /api/cycles/{period}         salário previsto do mês
POST   /api/cycles/{period}/repeat-recurring   copia gastos fixos do mês anterior
GET    /api/settings · PUT /api/settings   preferências (geração automática)
POST   /api/recurring/auto/{period}    gera agora os fixos do mês
DELETE /api/recurring/auto/{period}    desfaz a geração automática do mês
GET    /api/budget/{period}            limite × gasto por categoria
POST   /api/import/upload           prévia da planilha
POST   /api/import/commit           confirma a importação
DELETE /api/imports/{id}            desfaz um lote
GET    /api/export/csv · /api/export/xlsx · /api/export/resumo-csv · /api/export/template
```

Exemplo:

```bash
# lança um salário previsto
curl -X POST http://localhost:8000/api/transactions \
  -H 'Content-Type: application/json' \
  -d '{"type":"entrada","status":"previsto","amount":"3.450,00",
       "occurred_on":"2026-11-05","description":"Salário","category_name":"Salário"}'

# resumo do mês
curl http://localhost:8000/api/summary/2026-11
```

---

## Testes

```bash
pip install -r requirements-dev.txt
pytest                     # 295 testes
pytest -k importer         # só o importador
pytest --cov=app           # se você instalar pytest-cov
```

Cobrem: parsing monetário (pt-BR, internacional, contábil), utilitários de data/período,
CRUD e validações de lançamentos, ciclos e sincronização de salário, resumo mensal e
alertas, orçamentos, catálogo/autocomplete/preço médio, comparativos e matriz,
importador (CSV, XLSX, extrato, duplicadas, mapeamento manual, desfazer), exportações
(inclusive *round-trip*: o modelo XLSX exportado é reimportado com sucesso), gráficos SVG
e todos os endpoints da API e páginas.

---

## Comandos úteis

```bash
make install      # cria venv e instala dependências
make demo         # sobe o servidor com dados de exemplo
make run          # sobe com o banco vazio
make test         # roda os testes
make clean        # apaga o banco e os caches
```

Variáveis de ambiente:

| Variável | Padrão | O que faz |
|---|---|---|
| `FINANCAS_DB` | `data/financas.db` | caminho do banco SQLite |
| `FINANCAS_DATA_DIR` | `data/` | pasta de dados (banco + uploads temporários) |
| `FINANCAS_HOST` / `FINANCAS_PORT` | `0.0.0.0` / `8000` | onde o servidor escuta |
| `FINANCAS_PAGE_SIZE` | `25` | linhas por página na tabela de lançamentos |
| `FINANCAS_MAX_UPLOAD` | `5242880` | tamanho máximo de upload (bytes) |

---

## Decisões técnicas (resumo)

* **SQLite puro, sem ORM** — banco em arquivo único, fácil de copiar como backup; as
  consultas de relatório são SQL direto e legível.
* **Centavos como inteiro** — precisão monetária de verdade.
* **SVG gerado no servidor** — zero JavaScript de gráfico, zero CDN, funciona offline.
* **Server-rendered + `fetch` para mutações** — páginas carregam prontas (funcionam sem
  JS para leitura) e a API JSON é a mesma usada pela interface e por scripts.
* **Camada `services/` independente do FastAPI** — regras de negócio testáveis sem HTTP.
* **`check_same_thread=False` + conexão por request** — compatível com endpoints `async`
  (upload) e sync (threadpool) do FastAPI.
* **Migrações incrementais** (`app/db.py::_migrate`) — adicionar coluna não perde dados.
* **Geração de fixos disparada pelo uso, não por cron** — o app é local e nem sempre está
  no ar; gerar ao abrir o painel garante que o mês novo já amanhece lançado, sem serviço
  em segundo plano (detalhes em [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md)).
* **Orçamento informa, não alerta** — decisão de produto: o comparativo limite × gasto fica
  sempre visível no painel, mas não entra na lista de alertas.

Mais detalhes em [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).

---

## Roadmap (ideias bem-vindas)

- [ ] Múltiplos usuários com login (hoje o uso é local/monousuário)
- [ ] Quantidade por item (kg, un) para preço unitário real
- [ ] Contas/carteiras separadas (dinheiro, banco, cartão) com transferência entre elas
- [ ] Metas de economia e projeção de reserva de emergência
- [x] Agendamento automático de recorrentes — feito: gera *previstos* ao abrir o mês, com preferência e desfazer
- [ ] Exportar PDF do resumo mensal
- [ ] Alertas opcionais de orçamento (hoje o comparativo é apenas informativo)
- [ ] Regras de recorrência com periodicidade própria (semanal, trimestral, anual)
- [ ] Reconhecimento de extrato OFX/QIF
- [ ] Empacotar como executável (PyInstaller) e como container Docker

## Licença

[MIT](LICENSE) — use, modifique e distribua.
