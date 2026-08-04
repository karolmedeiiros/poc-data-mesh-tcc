# Data Mesh PoC — Inconsistências entre Produtos de Dados

Implementação dos quatro princípios do Data Mesh (Dehghani, 2022) com foco em **demonstrar como inconsistências surgem naturalmente** entre produtos de dados autônomos, mesmo com governança federada.

> Referências: *Data Mesh — Delivering Data-Driven Value at Scale* (Zhamak Dehghani, O'Reilly 2022) e [datamesh-architecture.com](https://www.datamesh-architecture.com/).

---

## Estrutura do Repositório

A organização espelha os quatro princípios fundamentais do Data Mesh:

```
tcc-data-mesh/
│
├── domains/                          ← Princípio 1 · Domain Ownership
│   ├── financeiro/                    ← Domínio Financeiro
│   │   ├── contas-a-pagar/              ← Subdomínio Contas a Pagar
│   │   │   ├── data_contract.yaml       Data Contract do produto entity publicado (output port)
│   │   │   └── data/                    Output Port entity publicado
│   │   │       └── contas_a_pagar.jsonl
│   │   └── contas-a-receber/            ← Subdomínio Contas a Receber
│   │       ├── data_contract.yaml
│   │       └── data/
│   │           └── contas_a_receber.jsonl
│   └── logistica/
│       ├── data_contract.yaml
│       └── data/
│           └── logistics.jsonl
│
├── operational/                      ← Camada de entrada bruta (não publicada como produto)
│   ├── financeiro/
│   │   ├── contas-a-pagar/ap_natural.jsonl
│   │   └── contas-a-receber/ar_natural.jsonl
│   └── logistica/logistics_natural.jsonl
│
├── governance/                       ← Princípio 4 · Federated Governance
│   ├── policies.yaml                    Políticas globais (SLAs, quality, security, QoS)
│   ├── validate_governance.py           Validação de compliance dos contratos
│   └── validate_contracts.py            Validação estrutural dos contratos
│
├── platform/                         ← Princípio 3 · Self-Serve Data Platform
│   ├── generators/                      Geração de dados sintéticos por domínio
│   │   ├── generate_data_natural.py     Gera operacional AP e AR com regras de domínio
│   │   ├── generate_logistics.py        Gera operacional Logística com cross-domain linkage
│   │   └── generate_data_analytical.py  Deriva output ports entity (data/) a partir do operacional
│   ├── quality/                         Validação de qualidade
│   │   └── validate_data_quality.py     Runtime validation contra regras do contrato
│   ├── catalog/                         Data Discovery
│   │   ├── build_data_catalog.py        Catálogo federado com lineage e busca
│   │   └── search.py                    Busca sobre o catálogo publicado
│   └── reconciliation/               ← ⚠️ NÃO é componente da arquitetura
│       │                                Camada de análise — instrumento de investigação
│       │                                sobre os produtos publicados (ver seção abaixo)
│       ├── reconcile_by_invoice.py      Reconciliação fina por master entity invoice_id
│       └── detect_cross_domain_divergences.py  Logística vs Financeiro por mês
│
├── odcs_adapter.py                   Adaptador ODCS v3 → visão interna metadata/spec
├── reports/                          ← Observability (outputs)
│   ├── governance_compliance.json
│   ├── data_quality_validation.json
│   └── ...
│
├── baseline/                         ← Snapshot congelado do estado atual (ver "Baseline")
│   ├── BASELINE.md                      Metadados do snapshot
│   ├── restore.sh                       Restaura a arquitetura para este estado
│   └── ...                              Cópia de domains/, platform/, governance/, etc.
│
├── requirements.txt
└── README.md
```

### Por que essa estrutura?

| Pasta | Princípio Data Mesh | Referência |
|---|---|---|
| `domains/` | Domain Ownership + Data as a Product | Dehghani cap. 8-9; datamesh-architecture.com §Domain |
| `governance/` | Federated Computational Governance | Dehghani cap. 15; datamesh-architecture.com §Governance |
| `platform/` | Self-Serve Data Platform | Dehghani cap. 14; datamesh-architecture.com §Platform |
| `reports/` | Observability / Monitoring | Dehghani cap. 12; datamesh-architecture.com §Data Product |
| `platform/reconciliation/` | **Nenhum** — camada de análise, não de arquitetura | ver seção abaixo |

### `platform/reconciliation/` — camada de análise, não de arquitetura

Reconciliação **não é um componente da arquitetura Data Mesh**. Não corresponde a nenhum
dos quatro princípios, não é serviço da self-serve platform e não seria implantada num
mesh em produção. Está fisicamente sob `platform/` por conveniência histórica.

O que ela é: **um instrumento de investigação**, construído para responder à pergunta que
motiva este trabalho — *existem divergências entre produtos de dados que a validação de
qualidade e a governança federada não capturam?*

A distinção importa porque as três camadas olham para coisas diferentes:

| Camada | O que compara | Escopo |
|---|---|---|
| `platform/quality/` | dado × contrato do próprio produto | **dentro** de um produto |
| `governance/` | contrato × política federada; contrato × dado | **dentro** de um produto |
| `platform/reconciliation/` | produto × produto | **entre** produtos |

Nenhuma das duas primeiras cruza a fronteira do domínio — por desenho, já que autonomia
de domínio é o Princípio 1. Cada produto pode estar 100 % correto contra o próprio
contrato e ainda assim divergir dos demais.

É exatamente o que se observa no baseline: **Data Quality 100 %, Governance Compliance
100 % — e ainda assim a reconciliação acusa 321
divergências** entre os produtos publicados (160 de valor AP↔AR, 161 de granularidade 1:N
entre Logística e Financeiro).

Esse contraste é o achado empírico do trabalho, não um defeito a corrigir: as divergências
são corretas por desenho de domínio (retenções fiscais, descontos, granularidade 1:N). O
ponto é que **a arquitetura não as torna visíveis** — é preciso um instrumento externo
para enxergá-las.

#### Critério: o que conta como divergência

O instrumento só é útil se distinguir inconsistência real de diferença esperada. Três
categorias, com tratamentos distintos:

| Categoria | Exemplo | Tratamento |
|---|---|---|
| **Violação** | operação logística apontando para fatura inexistente | divergência — exige ação |
| **Divergência por desenho** | valor AP ≠ AR por retenção fiscal; granularidade 1:N | divergência — documentada, esperada |
| **Não comparável** | `valor_total` logístico vs valor da fatura | achado informacional — sem regra, nada a validar |

A terceira categoria é a mais traiçoeira. Comparar grandezas que nenhum contrato vincula
gera números grandes que parecem achados relevantes e não são. Correções aplicadas para
eliminar esse tipo de falso positivo:

- **Faturas sem operação logística (1.061)** eram contadas como "registros órfãos" — e em
  dobro, uma vez por AP e outra por AR, chegando a 2.122. Não são órfãs: nem toda fatura
  gera frete, e o financeiro não referencia a logística. Reclassificadas como cobertura
  parcial, contadas em faturas. Integridade referencial passou de 46,9 % para **100 %**.
- **Valor logístico vs valor da fatura** era comparado com tolerância de 5 %, acusando
  912 de 939 faturas. São grandezas distintas (mercadoria + frete + seguro + imposto vs
  valor da fatura) e nenhum contrato declara a relação esperada. Virou estatística
  descritiva (mediana ≈ 1,16). Convergência cross-domain passou de 2,8 % para **100 %**.
- **Taxa de convergência** dividia pelas 2.000 faturas, incluindo as 1.061 sem logística
  — que não podem convergir nem divergir. Passou a usar só o universo comparável.

Antes das correções, os três scripts discordavam sobre o mesmo fato: o
a governança classificava as 1.061 faturas como "esperado/não
violação", o `reconcile_by_invoice.py` reportava 0 órfãos e o
`detect_cross_domain_divergences.py` reportava 2.122. Agora convergem.

> **Lacuna que permanece (proposital).** A comparação de valor cross-domain só se tornaria
> validável se a governança federada declarasse a relação esperada — p.ex. `frete ≤ 30 %
> do valor da fatura`. Enquanto essa política não existir, não há o que validar. É um
> limite da governança federada atual, não do instrumento.

---

## Domínios e Produtos de Dados

Cada domínio publica **um único produto de dados analítico** chaveado pela *master entity* `invoice_id` (output port *entity*), seguindo o padrão [datamesh-architecture.com](https://www.datamesh-architecture.com/). A pasta `operational/` (na raiz) contém apenas a **camada de entrada bruta** (não publicada como produto); a pasta `data/` de cada domínio contém o **output port** descrito por `data_contract.yaml`.

### financeiro/contas-a-pagar — Contas a Pagar (entity)
- **Owner**: finance-ap@empresa.com
- **Contrato**: `domains/financeiro/contas-a-pagar/data_contract.yaml` (`product_type: analytical`, `output_port_kind: entity_keyed`)
- **Output port**: `domains/financeiro/contas-a-pagar/data/contas_a_pagar.jsonl`
- **Grão**: `invoice_id` (1 linha por fatura — master entity)
- **Campos**: `amount`, `base_amount`, `status`, `invoice_type`, `supplier_id`, `issue_month`
- **Entrada (não publicada)**: `operational/financeiro/contas-a-pagar/ap_natural.jsonl`

### financeiro/contas-a-receber — Contas a Receber (entity)
- **Owner**: finance-ar@empresa.com
- **Contrato**: `domains/financeiro/contas-a-receber/data_contract.yaml` (`product_type: analytical`, `output_port_kind: entity_keyed`)
- **Output port**: `domains/financeiro/contas-a-receber/data/contas_a_receber.jsonl`
- **Grão**: `invoice_id` (1 linha por fatura — master entity)
- **Campos**: `gross_amount`, `base_amount`, `status`, `customer_type`, `customer_id`, `issue_month`
- **Entrada (não publicada)**: `operational/financeiro/contas-a-receber/ar_natural.jsonl`

### logistica — Operações Logísticas (entity)
- **Owner**: logistics-team@empresa.com
- **Contrato**: `domains/logistica/data_contract.yaml` (`product_type: analytical`, `output_port_kind: entity_keyed`)
- **Output port**: `domains/logistica/data/logistics.jsonl`
- **Grão**: `invoice_id` (1 linha por fatura, agregando N operações vinculadas)
- **Campos**: `operation_count`, `total_value`, `operation_types`, `statuses`, `operation_months`
- **Entrada (não publicada)**: `operational/logistica/logistics_natural.jsonl` (referência faturas via `related_invoice_id`)

---

## Output Ports entity (Master Entity `invoice`)

O output port de cada domínio é chaveado pela master entity federada `invoice_id`, governada por `governance/policies.yaml > master_entities`. Esses produtos viabilizam reconciliação fina (fatura-a-fatura) **sem violar autonomia de domínio**: cada produto mantém vocabulário e regras próprias.

| Produto | Contrato | Dataset | Linhas |
|---|---|---|---|
| `contas-a-pagar` | `data_contract.yaml` | `data/contas_a_pagar.jsonl` | 1 por fatura |
| `contas-a-receber` | `data_contract.yaml` | `data/contas_a_receber.jsonl` | 1 por fatura |
| `operacoes-logistica` | `data_contract.yaml` | `data/logistics.jsonl` | 1 por fatura (agrega N operações) |

**Tese evidenciada por `platform/reconciliation/reconcile_by_invoice.py`** (instrumento de
análise, não componente da arquitetura — ver "camada de análise" acima):
compartilhar a chave é *necessário* para reconciliação fina, mas *insuficiente* para
alinhamento. Ver tabela em "Resultados Esperados".

---

## Data Contracts (ODCS v3 — Bitol)

Cada `data_contract.yaml` é escrito no padrão **Open Data Contract Standard (ODCS) v3**, liderado pela Bitol (https://bitol-io.github.io/open-data-contract-standard/). O repositório inclui um adaptador (`odcs_adapter.py`) que normaliza o ODCS para a visão interna `metadata/spec` consumida pelas ferramentas de governança, catálogo e qualidade.

Estrutura ODCS vs visão interna:

| ODCS (arquivo) | Visão interna (ferramentas) | Descrição |
|---|---|---|
| `name`, `domain`, `team[].username` | `metadata.name`, `metadata.domain`, `metadata.owner` | Metadados básicos |
| `slaProperties[]` | `spec.product.sla` | SLAs (freshness, availability, latency, throughput) |
| `customProperties.schema_registry` | `spec.schema` | Registry, subject, formato, política de evolução |
| `schema[].properties[]` | `spec.dataset.fields[]` | Campos, tipos, constraints |
| `schema[].quality[]` | `spec.quality.rules[]` | Regras de validação com severity |
| `customProperties.tests` | `spec.tests` | Unit e integration tests declarativos |
| `customProperties.consumers` | `spec.consumers` | Expectativas dos consumidores |
| `customProperties.monitoring` | `spec.monitoring` | Métricas e alertas |

---

## Baseline — Restaurar o Estado da Arquitetura

A pasta `baseline/` guarda um snapshot congelado da arquitetura em estado válido (verde). Serve como ponto de retorno seguro para experimentar mudanças sem medo de quebrar a PoC.

### Restaurar

```bash
bash baseline/restore.sh
```

O comando pede confirmação antes de sobrescrever. Opções:

| Comando | Efeito |
|---|---|
| `bash baseline/restore.sh` | Restaura, pedindo confirmação |
| `bash baseline/restore.sh --dry-run` | Mostra o que mudaria, **sem escrever nada** |
| `bash baseline/restore.sh --force` | Restaura sem perguntar |

A restauração sobrescreve `domains/`, `operational/`, `platform/`, `governance/`, `reports/`, `odcs_adapter.py`, `requirements.txt`, `README.md` e `.gitignore`, e **remove** arquivos criados depois do snapshot. Não toca em `.git/`, `.venv/`, `__pycache__/` nem no próprio `baseline/`.

> Rode `--dry-run` primeiro se estiver em dúvida. Alterações não commitadas são perdidas na restauração.

### Ciclo de experimentação

```bash
# 1. faça sua alteração (dados, contrato, política…)
# 2. rode os validators e compare com os valores da tabela "Resultados Esperados"
python3 governance/validate_governance.py
python3 platform/quality/validate_data_quality.py
# 3. volta ao controle
bash baseline/restore.sh --force
```

### Autoteste do motor de regras

```bash
python3 platform/quality/validate_data_quality.py --self-test
```

Verifica que as expressões dos contratos são realmente avaliadas — que dados bons passam,
dados ruins reprovam, campo ausente não vira PASS silencioso e expressões perigosas são
rejeitadas. Guarda contra a volta do bug do falso 100 %.

### Atualizar o baseline

Depois de validar um novo estado como bom, congele-o como o novo ponto de retorno:

```bash
rsync -a --delete \
  --exclude='.git/' --exclude='.venv/' --exclude='__pycache__/' \
  --exclude='*.pyc' --exclude='baseline/' \
  --exclude='BASELINE.md' --exclude='restore.sh' \
  ./ baseline/
```

Os dois últimos `--exclude` são obrigatórios: sem eles o `--delete` apagaria o próprio `restore.sh` e o `BASELINE.md`. Depois de atualizar, ajuste a data e o commit de referência em `baseline/BASELINE.md`.

---

## Como Executar

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 1. Gerar dados operacionais (financeiro)
python3 platform/generators/generate_data_natural.py

# 2. Gerar dados operacionais (logística, lê AP/AR para cross-domain linkage)
python3 platform/generators/generate_logistics.py

# 2.1 Derivar output ports entity (data/) a partir do operacional
python3 platform/generators/generate_data_analytical.py

# 3. Governança Federada
python3 governance/validate_governance.py
python3 governance/validate_contracts.py

# 4. Qualidade de Dados
python3 platform/quality/validate_data_quality.py

# 5. Catálogo Federado
python3 platform/catalog/build_data_catalog.py

# ─────────────────────────────────────────────────────────────────────────
# Passos 6 e 7: ANÁLISE, não arquitetura. Não fazem parte do pipeline do
# mesh — são o instrumento que investiga o que a arquitetura não revela.
# ─────────────────────────────────────────────────────────────────────────

# 6. Reconciliação cross-domain (Logística vs Financeiro)
python3 platform/reconciliation/detect_cross_domain_divergences.py

# 7. Reconciliação fina por master entity invoice (output ports entity)
python3 platform/reconciliation/reconcile_by_invoice.py
```

---

## Resultados Esperados

Valores de referência do **baseline** (estado de controle, tudo verde). São estes os números que devem mudar quando você introduzir alterações no experimento:

| Validação | Resultado no baseline |
|---|---|
| Governance Compliance | 100 % (3/3 contratos) |
| Contract Validation | 3/3 válidos |
| Data Quality | 100 % válidos (4 939 registros pelos 3 datasets entity) |

> Os SLAs (*freshness* e *availability*) são verificados por `validate_governance.py`,
> em `check_slas()`, contra os limites globais de `policies.yaml`.

> ✅ **Ponto cego corrigido em `validate_data_quality.py`.** O `apply_rule` comparava
> `rule_id` contra IDs hardcoded (`ap-amount-positive`, `ap-currency-valid`…) que nunca
> casavam com os IDs reais dos contratos (`ap-k-positive-amount`, `ap-k-currency-brl`…).
> Nenhum ramo casava, toda regra caía no `PASS` default e o relatório mostrava 100 %
> mesmo com dados inválidos. Havia ainda um segundo bug: a regra de moeda lia
> `record["moeda"]`, mas o campo real é `dsc_moeda`.
>
> Agora as expressões declaradas no `data_contract.yaml` são de fato avaliadas contra os
> dados, por um interpretador embutido no próprio validator (autoteste: `--self-test`).
> Validado: injetando 9 registros ruins em
> contas-a-pagar, o validator acusa exatamente 9 e atribui cada violação à sua regra.

### Reconciliação por bucket canônico (sobre os output ports entity)

| Métrica | Resultado no baseline |
|---|---|
| Divergência Intra-Domain (AP vs AR, por bucket canônico) | 0 % — convergência e cobertura 100 % |
| Divergência Cross-Domain (Logística vs Financeiro) | 0 % — convergência 100 %, integridade referencial 100 % |
| Cobertura Financeiro→Logística | 46,9 % (1.061 faturas sem frete — esperado, não violação) |

Ambas zeradas **por construção**: o baseline é o estado de controle. A análise por bucket
canônico agrega por `(mês | status)`, então divergências finas de valor não aparecem aqui —
elas surgem na reconciliação por `invoice_id` (tabela abaixo).

### Reconciliação fina (output ports entity por `invoice_id`)

**Tese: compartilhar a chave é necessário mas insuficiente.**

| Categoria de divergência | Persistente com chave casada? | Faturas afetadas |
|---|---|---|
| Valor por regras de domínio (AP retenções vs AR descontos, mesmo invoice_id) | ✅ Persiste | **160** |
| Granularidade 1:N (Logística vs Financeiro, mesmo invoice_id) | ✅ Persiste | **161** |
| Vocabulário de status (PAID vs SETTLED, mesmo invoice_id) | ✅ Persistiria | 0 no baseline — status já canonizado na geração |
| Integridade referencial (Log apontando para fatura inexistente) | ⚠️ Categoria nova introduzida | 0 (backbone disciplinado) |
| Valor cross-domain (Log vs valor de fatura) | ➖ Não comparável | — (ver "Critério" acima) |
| Match ambíguo no analítico agregado | ❌ Some com chave compartilhada | — |

**Conclusão**: a chave compartilhada elimina apenas 1 tipo de divergência (ambiguidade de match) e *introduz* uma nova categoria (integridade referencial federada). Divergências que decorrem da autonomia de domínio — regras de negócio e granularidade — **persistem** em 321 faturas, justificando a necessidade de governança federada (canonicalização de status, MDM, contratos compartilhados).

> Duas categorias estão zeradas no baseline **por construção dos dados**, não por ausência
> de mecanismo: os geradores já emitem status canônico e vinculam toda operação logística a
> uma fatura existente. São os pontos naturais para injetar cenários de teste — trocar
> `PAGO` por `SETTLED` só em AR, ou apontar uma operação para fatura inexistente, faz cada
> categoria disparar.

---

## Alinhamento com datamesh-architecture.com

O site descreve uma jornada de maturidade em 5 níveis. Esta PoC atinge **Level 4 — Publish Data Contracts**:

| Nível | Descrição (site) | Implementado? |
|---|---|---|
| Level 0 | No Data Analytics | — |
| Level 1 | Operational Database Queries | — |
| Level 2 | Analyze Own Data | ✅ cada subdomínio analisa seus dados |
| Level 3 | Analyze Cross-domain Data | ✅ reconciliação Logística↔Financeiro |
| Level 4 | Publish Data Contracts | ✅ contratos publicados com compliance federado |

> *"Published data products must comply with the global policies defined by the federated governance group."* — datamesh-architecture.com

---

## Referências

- Dehghani, Z. (2022). *Data Mesh: Delivering Data-Driven Value at Scale*. O'Reilly.
- [datamesh-architecture.com](https://www.datamesh-architecture.com/) — Data Mesh From an Engineering Perspective.
- [Data Mesh Principles](https://martinfowler.com/articles/data-mesh-principles.html) — Martin Fowler.
- [Data Contract Specification](https://datacontract.com/) — Formato YAML para contratos.