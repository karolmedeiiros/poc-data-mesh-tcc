# Data Mesh PoC — Inconsistências entre Produtos de Dados

Implementação dos quatro princípios do Data Mesh (Dehghani, 2022) com foco em **demonstrar como inconsistências surgem naturalmente** entre produtos de dados autônomos, mesmo com governança federada e QoS avançado.

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
│   │   │   ├── dataproduct.yaml         Data Contract do produto ANALÍTICO publicado (output port)
│   │   │   ├── operational/             Camada de entrada (dados brutos, não publicados)
│   │   │   │   └── ap_natural.jsonl
│   │   │   └── data/                    Output Port analítico publicado
│   │   │       └── ap_analytical.jsonl
│   │   └── contas-a-receber/            ← Subdomínio Contas a Receber
│   │       ├── dataproduct.yaml
│   │       ├── operational/
│   │       │   └── ar_natural.jsonl
│   │       └── data/
│   │           └── ar_analytical.jsonl
│   └── logistica/
│       ├── dataproduct.yaml
│       ├── operational/
│       │   └── logistics_natural.jsonl
│       └── data/
│           └── logistics_analytical.jsonl
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
│   │   └── generate_data_analytical.py  Deriva output ports analíticos (data/) a partir do operacional
│   ├── quality/                         Validação de qualidade e QoS
│   │   ├── validate_data_quality.py     Runtime validation contra regras do contrato
│   │   └── validate_qos.py             Observability, Error Budgets, Reliability, Performance
│   ├── catalog/                         Data Discovery
│   │   └── build_data_catalog.py        Catálogo federado com lineage e busca
│   └── reconciliation/                  Análise sobre a camada analítica publicada
│       ├── reconcile_data_mesh.py       Orquestrador macro (intra + cross-domain)
│       ├── detect_natural_divergences.py   AP vs AR por (issue_month | status canônico)
│       └── detect_cross_domain_divergences.py  Logística vs Financeiro por mês
│
├── reports/                          ← Observability (outputs)
│   ├── governance_compliance.json
│   ├── qos_validation_report.json
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
| `reports/` | Observability / Monitoring | Dehghani cap. 12 (QoS); datamesh-architecture.com §Data Product |

---

## Domínios e Produtos de Dados

Cada domínio publica **um único produto de dados analítico** (output port agregado), seguindo o padrão [datamesh-architecture.com](https://www.datamesh-architecture.com/). A pasta `operational/` contém apenas a **camada de entrada bruta** (não publicada como produto); a pasta `data/` contém o **output port analítico** descrito por `dataproduct.yaml`.

### financeiro/contas-a-pagar — Contas a Pagar (Analytical)
- **Owner**: finance-ap@empresa.com
- **Contrato**: `domains/financeiro/contas-a-pagar/dataproduct.yaml` (`product_type: analytical`)
- **Output port**: `domains/financeiro/contas-a-pagar/data/ap_analytical.jsonl`
- **Grão**: `issue_month | status | invoice_type`
- **Medidas**: `invoice_count`, `supplier_count`, `total_amount`, `avg_amount`
- **Entrada (não publicada)**: `operational/ap_natural.jsonl`

### financeiro/contas-a-receber — Contas a Receber (Analytical)
- **Owner**: finance-ar@empresa.com
- **Contrato**: `domains/financeiro/contas-a-receber/dataproduct.yaml` (`product_type: analytical`)
- **Output port**: `domains/financeiro/contas-a-receber/data/ar_analytical.jsonl`
- **Grão**: `issue_month | status | customer_type`
- **Medidas**: `invoice_count`, `customer_count`, `total_gross_amount`, `avg_gross_amount`
- **Entrada (não publicada)**: `operational/ar_natural.jsonl`

### logistica — Operações Logísticas (Analytical)
- **Owner**: logistics-team@empresa.com
- **Contrato**: `domains/logistica/dataproduct.yaml` (`product_type: analytical`)
- **Output port**: `domains/logistica/data/logistics_analytical.jsonl`
- **Grão**: `operation_month | operation_type | status`
- **Medidas**: `operation_count`, `party_count`, `total_value`, `linked_to_invoice_rate`
- **Entrada (não publicada)**: `operational/logistics_natural.jsonl` (referência faturas via `related_invoice_id`)

---

## Output Ports Entity-Keyed (Master Entity `invoice`)

Cada domínio publica **um segundo output port** chaveado pela master entity federada `invoice_id`, governada por `governance/policies.yaml > master_entities`. Esses produtos viabilizam reconciliação fina (fatura-a-fatura) **sem violar autonomia de domínio**: cada produto mantém vocabulário e regras próprias.

| Produto | Contrato | Dataset | Linhas |
|---|---|---|---|
| `contas-a-pagar-invoice-keyed` | `dataproduct_invoice_keyed.yaml` | `data/ap_invoice_keyed.jsonl` | 1 por fatura |
| `contas-a-receber-invoice-keyed` | `dataproduct_invoice_keyed.yaml` | `data/ar_invoice_keyed.jsonl` | 1 por fatura |
| `operacoes-logistica-invoice-keyed` | `dataproduct_invoice_keyed.yaml` | `data/logistics_invoice_keyed.jsonl` | 1 por fatura (agrega N operações) |

**Tese provada por `platform/reconciliation/reconcile_by_invoice.py`**:
Compartilhar a chave é *necessário* para reconciliação fina, mas *insuficiente* para alinhamento. Ver tabela em "Resultados Esperados".

---

## Data Contracts

Cada `dataproduct.yaml` contém:

| Seção | Descrição |
|---|---|
| `metadata` | Nome, domínio, owner, versão, tags |
| `spec.product.sla` | Freshness, Availability, Latency, Throughput |
| `spec.schema` | Registry, subject, formato, política de evolução |
| `spec.dataset` | Campos, tipos, constraints |
| `spec.observability` | Freshness monitoring, schema drift, volume anomalies |
| `spec.error_budgets` | Monthly/weekly/daily budgets, burn rate alerts |
| `spec.reliability` | MTTR, MTBF, RTO, RPO, backup strategy |
| `spec.performance` | Query P50/P95/P99, batch, streaming, scalability |
| `spec.quality` | Regras de validação com severity |
| `spec.tests` | Unit e integration tests declarativos |
| `spec.consumers` | Expectativas dos consumidores |
| `spec.monitoring` | Métricas e alertas |

---

## Como Executar

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 1. Gerar dados operacionais (financeiro)
python platform/generators/generate_data_natural.py

# 2. Gerar dados operacionais (logística, lê AP/AR para cross-domain linkage)
python platform/generators/generate_logistics.py

# 2.1 Derivar output ports analíticos (data/) a partir do operacional
python platform/generators/generate_data_analytical.py

# 3. Governança Federada
python governance/validate_governance.py
python governance/validate_contracts.py

# 4. QoS Avançado
python platform/quality/validate_qos.py

# 5. Qualidade de Dados
python platform/quality/validate_data_quality.py

# 6. Catálogo Federado
python platform/catalog/build_data_catalog.py

# 7. Reconciliação macro (sobre output ports analytical agregados)
python platform/reconciliation/reconcile_data_mesh.py
python platform/reconciliation/detect_natural_divergences.py
python platform/reconciliation/detect_cross_domain_divergences.py

# 8. Reconciliação fina por master entity invoice (output ports entity-keyed)
python platform/reconciliation/reconcile_by_invoice.py
```

---

## Resultados Esperados

| Validação | Resultado |
|---|---|
| Governance Compliance | 100 % (6/6 produtos analytical + entity-keyed) |
| QoS Advanced | 100 % (17/17 checks por produto) |
| Data Quality | 100 % válidos (~9 360 registros pelos 6 datasets) |

### Reconciliação macro (output ports agregados por bucket)

| Métrica | Resultado |
|---|---|
| Divergência Intra-Domain (AP vs AR, por bucket canônico) | ~33 % (vocabulário de status PAID vs SETTLED) |
| Divergência Cross-Domain (Logística vs Financeiro, por mês) | ~100 % (cobertura parcial de vínculo + regras próprias) |

### Reconciliação fina (output ports entity-keyed por `invoice_id`)

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