# Formato de importação de planilhas

O importador foi feito para aceitar **a planilha que você já tem**, não um formato único.
Ainda assim, quanto mais explícitas as colunas, menos intervenção manual.

## Arquivos aceitos

| Extensão | Observações |
|---|---|
| `.csv` | separador detectado automaticamente (`;`, `,`, tab ou `\|`); codificação `utf-8`, `utf-8-sig`, `cp1252` ou `latin-1` |
| `.xlsx` / `.xlsm` | múltiplas abas: escolha qual importar na prévia |
| `.txt` | tratado como CSV |

Limite de tamanho: 5 MB (`FINANCAS_MAX_UPLOAD`) e 20.000 linhas por arquivo.

## Colunas reconhecidas

O cabeçalho é localizado automaticamente (mesmo que haja um título na primeira linha).
Cada coluna é comparada com estes apelidos — sem acento e sem diferenciar maiúsculas:

| Campo | Apelidos aceitos |
|---|---|
| **Data** *(obrigatória)* | `data`, `date`, `dia`, `vencimento`, `data pagamento`, `data do pagamento`, `dt`, `data da transação`, `data lançamento`, `effective date`, `posting date` |
| **Valor** *(obrigatória)* | `valor`, `amount`, `quantia`, `value`, `montante`, `total`, `valor r$`, `vlr`, `importância` |
| Tipo | `tipo`, `type`, `natureza`, `direção`, `direction`, `movimento`, `débito/crédito`, `d/c`, `entrada/saída` |
| Descrição | `descrição`, `description`, `histórico`, `lançamento`, `memo`, `título`, `complemento`, `detalhe`, `resumo`, `narrativa` |
| Categoria | `categoria`, `category`, `grupo`, `group`, `classe`, `tipo de gasto`, `segmento`, `subcategoria` |
| Status | `status`, `situação`, `state`, `pago?`, `condição` |
| Forma de pagamento | `forma`, `forma de pagamento`, `método`, `method`, `pagamento`, `cartão`, `conta`, `meio` |
| Item | `item`, `produto`, `product`, `serviço` |
| Observação | `obs`, `observação`, `note`, `notas`, `comentário` |

Se a planilha **não tiver cabeçalho**, o sistema deduz por posição: a coluna com valores
que parecem datas vira `Data`, a com números vira `Valor` e a de texto livre vira
`Descrição`. Você pode corrigir tudo na prévia, antes de confirmar.

## Regras de conversão

### Números

| Na planilha | Interpretado como |
|---|---|
| `1.234,56` | R$ 1.234,56 |
| `R$ 1.234,56` | R$ 1.234,56 |
| `1234.56` | R$ 1.234,56 |
| `1.234` ou `1,234` | R$ 1.234,00 (3 dígitos após o separador ⇒ milhar) |
| `12,34` | R$ 12,34 |
| `(85,00)` | R$ 85,00 **negativo** (notação contábil) |
| `-85,00` | R$ 85,00 negativo |
| célula vazia / texto | linha ignorada e listada como erro na prévia |

### Datas

`05/10/2026`, `2026-10-05`, `05-10-2026`, `05/10/26`, data real do Excel e
**número de série do Excel** (ex.: `45658` → 01/01/2025).

### Tipo (entrada ou saída)

Ordem de decisão:

1. **coluna de tipo** presente — `entrada`, `receita`, `crédito`, `C`, `+`, `recebimento`
   ⇒ entrada; `saída`, `despesa`, `débito`, `D`, `-`, `pagamento` ⇒ saída;
2. **valor negativo** ⇒ sempre saída (o sinal é preservado como magnitude);
3. **modo extrato bancário** ⇒ positivo é entrada. Só entra em vigor quando não há coluna
   de tipo **e** existem pelo menos 3 valores negativos representando ≥ 30% das linhas
   (uma planilha de gastos com um estorno pontual não é confundida com extrato);
4. **dica de receita** — descrição ou categoria que case com uma categoria de entrada
   cadastrada (`Salário`, `Freelance / Extra`, `Reembolso`…) ou com palavras como
   `salário`, `freelance`, `reembolso`, `13º`, `férias`, `rendimento`, `pix recebido`,
   `venda de…` ⇒ entrada;
5. **tipo padrão** escolhido no formulário (padrão: saída).

### Status

`pago`, `recebido`, `quitado`, `realizado`, `efetivado`, `concluído`, `liquidado`,
`sim`, `ok` ⇒ **realizado**.
`previsto`, `pendente`, `a pagar`, `a receber`, `agendado`, `programado`, `aberto` ⇒
**previsto**. Sem a coluna, vale o status padrão do formulário.

### Categorias e itens

* categorias que não existem são **criadas** (opção `create_categories`);
* itens novos são **cadastrados no catálogo** a partir da coluna `Item` ou, na falta dela,
  da descrição quando ela tem até 60 caracteres (opção `create_items`);
* o casamento de nomes é normalizado: `Café 500g`, `cafe 500g` e `CAFÉ 500G` são o mesmo
  item, o que evita duplicatas entre importações.

### Duplicadas

Uma linha é considerada duplicada quando já existe lançamento com a **mesma data, valor,
tipo e descrição normalizada**. Duplicatas são ignoradas por padrão (`skip_duplicates`),
inclusive dentro do próprio arquivo.

## Exemplos que funcionam de primeira

**Planilha caseira brasileira**

```csv
Data;Descrição;Categoria;Valor;Forma de pagamento;Status
05/10/2026;Salário;Salário;3.450,00;Transferência;Recebido
05/10/2026;Aluguel;Moradia;950,00;Boleto;Pago
08/10/2026;Mercado;Mercado / Alimentação;412,38;Cartão de débito;Pago
25/10/2026;Internet;Contas;89,90;Débito automático;Pendente
```

**Extrato bancário em inglês**

```csv
effective date,description,amount
2026-10-05,SALARIO EMPRESA XYZ,3450.00
2026-10-06,SUPERMERCADO BOM PRECO,-412.38
2026-10-08,UBER TRIP,-27.90
2026-10-12,PIX RECEBIDO JOAO,150.00
```

**Só data, descrição e valor** (sem categoria nem tipo)

```csv
Data,Histórico,Valor (R$)
05/10/2026,Aluguel,950.00
08/10/2026,Feira,86.40
```

## Depois de importar

* os lançamentos aparecem marcados com a origem `import:<arquivo>:<token>`;
* os meses importados entram automaticamente nos **comparativos** e na matriz
  categorias × meses — é assim que a planilha antiga vira linha de base;
* para desfazer: **Importar planilha → Importações já feitas → ↺**.

## Modelo pronto

Baixe em **Configurações → Backup em Excel** (aba `Modelo`) ou em
`GET /api/export/template`. Há também
[`exemplos/planilha-gastos-2025.csv`](../exemplos/planilha-gastos-2025.csv) no repositório.
