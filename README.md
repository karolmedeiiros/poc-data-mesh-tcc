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
│   │   │   ├── dataproduct.yaml         Data Contract do produto entity publicado (output port)
│   │   │   ├── operational/             Camada de entrada (dados brutos, não publicados)
│   │   │   │   └── ap_natural.jsonl
│   │   │   └── data/                    Output Port entity publicado
│   │   │       └── ap.jsonl
│   │   └── contas-a-receber/            ← Subdomínio Contas a Receber
│   │       ├── dataproduct.yaml
│   │       ├── operational/
│   │       │   └── ar_natural.jsonl
│   │       └── data/
│   │           └── ar.jsonl
│   └── logistica/
│       ├── dataproduct.yaml
│       ├── operational/
│       │   └── logistics_natural.jsonl
│       └── data/
│           └── logistics.jsonl
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
│   │   └── build_data_catalog.py        Catálogo federado com lineage e busca
│   └── reconciliation/                  Análise sobre os output ports entity publicados
│       ├── reconcile_data_mesh.py       Orquestrador macro (intra + cross-domain)
│       ├── detect_natural_divergences.py   AP vs AR por (issue_month | status canônico)
│       └── detect_cross_domain_divergences.py  Logística vs Financeiro por mês
│
├── reports/                          ← Observability (outputs)
│   ├── governance_compliance.json
│   ├── data_quality_validation.json
│   ├── data_mesh_reconciliation.json
│   └── ...
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

---

## Domínios e Produtos de Dados

Cada domínio publica **um único produto de dados analítico** chaveado pela *master entity* `invoice_id` (output port *entity*), seguindo o padrão [datamesh-architecture.com](https://www.datamesh-architecture.com/). A pasta `operational/` contém apenas a **camada de entrada bruta** (não publicada como produto); a pasta `data/` contém o **output port** descrito por `dataproduct.yaml`.

### financeiro/contas-a-pagar — Contas a Pagar (entity)
- **Owner**: finance-ap@empresa.com
- **Contrato**: `domains/financeiro/contas-a-pagar/dataproduct.yaml` (`product_type: analytical`, `output_port_kind: entity_keyed`)
- **Output port**: `domains/financeiro/contas-a-pagar/data/ap.jsonl`
- **Grão**: `invoice_id` (1 linha por fatura — master entity)
- **Campos**: `amount`, `base_amount`, `status`, `invoice_type`, `supplier_id`, `issue_month`
- **Entrada (não publicada)**: `operational/ap_natural.jsonl`

### financeiro/contas-a-receber — Contas a Receber (entity)
- **Owner**: finance-ar@empresa.com
- **Contrato**: `domains/financeiro/contas-a-receber/dataproduct.yaml` (`product_type: analytical`, `output_port_kind: entity_keyed`)
- **Output port**: `domains/financeiro/contas-a-receber/data/ar.jsonl`
- **Grão**: `invoice_id` (1 linha por fatura — master entity)
- **Campos**: `gross_amount`, `base_amount`, `status`, `customer_type`, `customer_id`, `issue_month`
- **Entrada (não publicada)**: `operational/ar_natural.jsonl`

### logistica — Operações Logísticas (entity)
- **Owner**: logistics-team@empresa.com
- **Contrato**: `domains/logistica/dataproduct.yaml` (`product_type: analytical`, `output_port_kind: entity_keyed`)
- **Output port**: `domains/logistica/data/logistics.jsonl`
- **Grão**: `invoice_id` (1 linha por fatura, agregando N operações vinculadas)
- **Campos**: `operation_count`, `total_value`, `operation_types`, `statuses`, `operation_months`
- **Entrada (não publicada)**: `operational/logistics_natural.jsonl` (referência faturas via `related_invoice_id`)

---

## Output Ports entity (Master Entity `invoice`)

O output port de cada domínio é chaveado pela master entity federada `invoice_id`, governada por `governance/policies.yaml > master_entities`. Esses produtos viabilizam reconciliação fina (fatura-a-fatura) **sem violar autonomia de domínio**: cada produto mantém vocabulário e regras próprias.

| Produto | Contrato | Dataset | Linhas |
|---|---|---|---|
| `contas-a-pagar` | `dataproduct.yaml` | `data/ap.jsonl` | 1 por fatura |
| `contas-a-receber` | `dataproduct.yaml` | `data/ar.jsonl` | 1 por fatura |
| `operacoes-logistica` | `dataproduct.yaml` | `data/logistics.jsonl` | 1 por fatura (agrega N operações) |

**Tese provada por `platform/reconciliation/reconcile_by_invoice.py`**:
Compartilhar a chave é *necessário* para reconciliação fina, mas *insuficiente* para alinhamento. Ver tabela em "Resultados Esperados".

---

## Data Contracts (ODCS v3 — Bitol)

Cada `dataproduct.yaml` é escrito no padrão **Open Data Contract Standard (ODCS) v3**, liderado pela Bitol (https://bitol-io.github.io/open-data-contract-standard/). O repositório inclui um adaptador (`odcs_adapter.py`) que normaliza o ODCS para a visão interna `metadata/spec` consumida pelas ferramentas de governança, catálogo e qualidade.

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

# 6. Reconciliação intra e cross-domain (sobre output ports entity por invoice_id)
python3 platform/reconciliation/reconcile_data_mesh.py
python3 platform/reconciliation/detect_natural_divergences.py
python3 platform/reconciliation/detect_cross_domain_divergences.py

# 7. Reconciliação fina por master entity invoice (output ports entity)
python3 platform/reconciliation/reconcile_by_invoice.py

# 8. Governança Computacional (valida inconsistências reais entre contratos e dados)
python3 governance/validate_computational_governance.py
```

---

## Resultados Esperados

| Validação | Resultado |
|---|---|
| Governance Compliance | 100 % (3/3 produtos entity) |
| Data Quality | 100 % válidos (~4 940 registros pelos 3 datasets entity) |
| Computational Governance | FAIL (detecta inconsistências cross-domain e schema drift) |

### Reconciliação por bucket canônico (sobre os output ports entity)

| Métrica | Resultado |
|---|---|
| Divergência Intra-Domain (AP vs AR, por bucket canônico) | ~33 % (vocabulário de status PAID vs SETTLED) |
| Divergência Cross-Domain (Logística vs Financeiro, por mês) | ~100 % (cobertura parcial de vínculo + regras próprias) |

### Reconciliação fina (output ports entity por `invoice_id`)

**Tese: compartilhar a chave é necessário mas insuficiente.**

| Categoria de divergência | Persistente com chave casada? | Faturas afetadas |
|---|---|---|
| Vocabulário de status (PAID vs SETTLED, mesmo invoice_id) | ✅ Persiste | **441** |
| Valor por regras de domínio (AP retenda vs AR descontos, mesmo invoice_id) | ✅ Persiste | **159** |
| Granularidade 1:N (Logística vs Financeiro, mesmo invoice_id) | ✅ Persiste | **155** |
| Valor cross-domain (frete/manuseio Log vs valor de fatura) | ✅ Persiste | **909** |
| Integridade referencial (Log apontando para fatura inexistente) | ⚠️ Categoria nova introduzida | 0 (backbone disciplinado) |
| Match ambigüo no analítico agregado | ❌ Some com chave compartilhada | — |

**Conclusão**: a chave compartilhada elimina apenas 1 tipo de divergência (ambiguidade de match) e *introduz* uma nova categoria (integridade referencial federada). Divergências que decorrem da autonomia de domínio — vocabulário, regras de negócio, granularidade, janela temporal — **persistem**, justificando a necessidade de governança federada (canonicalização de status, MDM, contratos compartilhados).

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