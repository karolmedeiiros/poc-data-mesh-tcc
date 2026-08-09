# Data Mesh: Desafios para Garantir a Consistência de Dados Entre Domínios

Este repositório contém a prova de conceito desenvolvida para o Trabalho de
Conclusão de Curso em Ciência da Computação pela Universidade Federal do ABC,
intitulado:

> **"Data Mesh: Desafios para Garantir a Consistência de Dados Entre Domínios"**
> Karoline Novaes Medeiros · Centro de Matemática, Computação e Cognição · UFABC ·
> Santo André, 2026

Os cenários experimentais e as métricas coletadas encontram-se em
[`experimentos/`](experimentos/).

 [Leia o trabalho completo aqui.](docs/)
 [Assista ao Vídeo de Apresentação da PoC aqui](https://drive.google.com/file/d/1tB4Qk5b9eOMJnXebGpg7HcrnSNxyLZe0/view?usp=drive_link)


---

## Sumário

- [O problema investigado](#o-problema-investigado)
- [Conceitos necessários](#conceitos-necessários)
- [O que esta prova de conceito faz](#o-que-esta-prova-de-conceito-faz)
- [Estrutura do repositório](#estrutura-do-repositório)
- [Como executar](#como-executar)
- [Os três produtos de dados](#os-três-produtos-de-dados)
- [As três camadas de verificação](#as-três-camadas-de-verificação)
- [Método experimental](#método-experimental)
- [Cenários executados](#cenários-executados)
- [Métricas coletadas](#métricas-coletadas)
- [Limitações](#limitações)
- [Requisitos](#requisitos)

---

## O problema investigado

Durante décadas, organizações centralizaram seus dados analíticos em uma única
estrutura — primeiro *data warehouses*, depois *data lakes* — mantida por uma
equipe especializada. Esse modelo cria um gargalo: quem entende o significado dos
dados está nas áreas de negócio, mas quem tem acesso e ferramenta para publicá-los
está na equipe central.

O **Data Mesh**, formulado por Zhamak Dehghani em 2019, propõe inverter esse
arranjo. Cada área de negócio — cada *domínio* — passa a ser responsável por
publicar seus próprios dados como um **produto**, com contrato, qualidade e
compromisso de serviço declarados. A arquitetura repousa em quatro princípios:

| Princípio | O que significa |
|---|---|
| **Domain Ownership** | cada domínio é dono dos dados que produz |
| **Data as a Product** | dados são publicados como produto, com contrato e responsável |
| **Self-Serve Platform** | a plataforma oferece as capacidades técnicas comuns |
| **Federated Computational Governance** | políticas globais são codificadas e verificadas automaticamente |

A descentralização resolve o gargalo, mas cria um problema novo, que é o objeto
deste trabalho. Se cada domínio publica de forma autônoma, **quem garante que dois
domínios não afirmem coisas incompatíveis sobre a mesma entidade do mundo real?**

Considere uma fatura. O domínio Financeiro registra que ela foi cancelada. O
domínio Logística, autônomo, registra que a entrega correspondente foi concluída.
Cada produto está internamente correto — cada um respeita seu próprio contrato —,
mas juntos afirmam algo impossível: entregou-se uma mercadoria cuja obrigação
financeira foi cancelada. Nenhum dos dois domínios errou. A inconsistência existe
apenas **na relação entre eles**, e é exatamente aí que nenhum dos dois tem
autoridade.

A pergunta de pesquisa é, portanto: **a consistência de dados entre domínios é
mantida pelos mecanismos previstos pelo Data Mesh, ou depende de mecanismos
complementares de coordenação e validação?**

## Conceitos necessários

Quem não conhece o tema precisa de cinco definições para acompanhar o repositório.

**Produto de dados** (*data product*). Conjunto de dados publicado por um domínio
para consumo por outros, acompanhado de contrato, metadados e compromisso de
serviço. Aqui, cada produto é um arquivo JSONL — uma linha por registro — mais o
contrato que o descreve.

**Output port.** A interface pela qual o produto é consumido. Nesta implementação,
o arquivo publicado em `domains/<domínio>/data/`. É distinto dos dados
operacionais brutos, que ficam em `operational/` e não são publicados.

**Contrato de dados** (*data contract*). Documento declarativo que especifica o que
o produto publica: atributos, tipos, obrigatoriedade, regras de qualidade, SLA e
consumidores esperados. Aqui os contratos seguem o **ODCS** (*Open Data Contract
Standard*, projeto Bitol), escritos em YAML. O contrato é a fonte da verdade:
acrescentar uma regra no YAML passa a valer sem alterar nenhum script.

**Governança computacional federada.** As políticas globais da organização são
escritas como código (`governance/policies.yaml`) e verificadas automaticamente
contra os contratos, em vez de dependerem de revisão manual. É o quarto princípio
do Data Mesh e o mecanismo cuja eficácia este trabalho põe à prova.

**Entidade-mestre** (*master entity*). Identificador de um objeto de negócio
compartilhado entre domínios, que permite correlacionar registros de produtos
diferentes. Aqui é o `invoice_id`: os três produtos o publicam, e é ele que torna
possível — e necessário — perguntar se os domínios concordam.

## O que esta prova de conceito faz

A implementação constrói uma malha de dados mínima, porém completa nos quatro
princípios, e submete seus mecanismos de verificação a **inconsistências
introduzidas deliberadamente**, medindo o que cada camada detecta e o que deixa
passar.

O desenho experimental segue a lógica de grupo de controle: um estado da
arquitetura é congelado em `baseline/` e serve de referência. Cada cenário aplica
uma intervenção única sobre esse estado, coleta as mesmas métricas e restaura o
controle. Diferenças observadas são, assim, atribuíveis à intervenção.

## Estrutura do repositório

```
.
├── domains/                         Produtos de dados publicados (Princípios 1 e 2)
│   ├── financeiro/
│   │   ├── contas-a-pagar/
│   │   │   ├── data_contract.yaml   Contrato ODCS v3
│   │   │   └── data/                Output port publicado (JSONL)
│   │   └── contas-a-receber/        Idem
│   └── logistica/                   Idem
│
├── operational/                     Dados operacionais brutos (não publicados)
│   ├── financeiro/
│   └── logistica/
│
├── platform/                        Plataforma de autoatendimento (Princípio 3)
│   ├── generators/                  Geração dos dados sintéticos
│   ├── quality/                     Validação de qualidade (dado × contrato)
│   ├── catalog/                     Catálogo federado e busca
│   └── reconciliation/              Instrumento de análise (ver nota abaixo)
│
├── governance/                      Governança computacional federada (Princípio 4)
│   ├── policies.yaml                Políticas globais como código
│   └── validate_governance.py       Verificação contrato × políticas
│
├── reports/                         Saídas das verificações (JSON)
│
├── baseline/                        Estado de controle congelado
│   ├── restore.sh                   Restaura a arquitetura para o controle
│   ├── CHECKSUM · MANIFEST          Proteção de integridade do snapshot
│   └── BASELINE.md                  Documentação do snapshot
│
├── experimentos/                    Cenários executados e métricas coletadas
│   ├── cenario1/ … cenario5/        Dados, contratos, relatórios e registro
│   └── cenario4b/                   Análise de cobertura das políticas
│
│
├── odcs_adapter.py                  Normalização dos contratos ODCS
└── requirements.txt                 Dependência única: PyYAML
```

> **Nota importante.** `platform/reconciliation/` **não integra o pipeline da
> malha**. É o instrumento construído para investigar o que os mecanismos da
> arquitetura não revelam. Divergências que apenas ele detecta são evidência do
> que a arquitetura deixa passar — não da sua capacidade. A distinção é essencial
> para a leitura dos resultados.

## Como executar

O pipeline tem duas fases: gerar os produtos e verificá-los. Os comandos devem ser
executados a partir da raiz do repositório.

```bash
# Dependências
pip install -r requirements.txt

# ── Fase 1 · Geração dos produtos de dados ────────────────────────────────
python3 platform/generators/generate_data_natural.py      # operacional financeiro
python3 platform/generators/generate_logistics.py         # operacional logística
python3 platform/generators/generate_data_analytical.py   # output ports publicados

# ── Fase 2 · Verificação ──────────────────────────────────────────────────
python3 governance/validate_governance.py                 # contrato × políticas
python3 platform/quality/validate_data_quality.py         # dado × contrato
python3 platform/catalog/build_data_catalog.py            # catálogo federado
python3 platform/catalog/search.py                        # busca no catálogo

# ── Fase 3 · Análise (não é parte da arquitetura) ──────────────────────────
python3 platform/reconciliation/detect_cross_domain_divergences.py
python3 platform/reconciliation/reconcile_by_invoice.py
```

Cada script grava seu relatório em `reports/`. Nenhum depende de banco de dados,
serviço externo ou credencial.

### Autoteste da camada de qualidade

O validador de qualidade traz um autoteste que exige que **toda regra declarada
nos contratos seja avaliável** — proteção contra a classe de defeito descrita em
[Método experimental](#método-experimental):

```bash
python3 platform/quality/validate_data_quality.py --self-test
```

### Restaurar o estado de controle

```bash
bash baseline/restore.sh              # pede confirmação
bash baseline/restore.sh --dry-run    # mostra o que mudaria, sem escrever
bash baseline/restore.sh --force      # sem perguntar
```

O restore sobrescreve a arquitetura com o snapshot e remove arquivos criados
depois dele. **Preserva** `experimentos/`, que contêm o material de
análise, e verifica a integridade do próprio snapshot antes de agir: se
`baseline/` tiver sido alterado, o comando informa exatamente quais arquivos
divergem do `MANIFEST` e pede confirmação.

## Os três produtos de dados

| Produto | Domínio | Grão | Atributos característicos |
|---|---|---|---|
| `contas-a-pagar` | financeiro | 1 linha por fatura | `valor_liquido` (após retenções), `id_fornecedor` |
| `contas-a-receber` | financeiro | 1 linha por fatura | `valor_bruto` (após descontos e juros), `id_cliente` |
| `operacoes-logistica` | logística | 1 linha por fatura, agregando N operações | `valor_total` decomposto em base, frete, seguro e imposto |

Os três publicam `invoice_id`, `dsc_moeda` e os atributos de linhagem
(`dsc_dominio`, `dsc_produto`, `dt_versao`). Duas assimetrias são **intencionais**,
porque reproduzem a realidade que o Data Mesh assume:

- **Vocabulários distintos.** O financeiro usa `ABERTO`, `PAGO`, `CANCELADO`; a
  logística usa `PENDENTE`, `EM_PROCESSAMENTO`, `CONCLUIDO`, `CANCELADO`.
- **Grandezas não comparáveis.** O `valor_total` logístico e o valor da fatura
  respondem a regras de negócio diferentes e não devem coincidir.

## As três camadas de verificação

Compreender **o que cada camada compara** é o que permite interpretar os
resultados.

| Camada | Compara | Detecta | Não detecta |
|---|---|---|---|
| **Governança computacional** | contrato × políticas globais | contrato incompleto, metadado ausente, SLA abaixo do mínimo federado, alerta incoerente com o SLA | qualquer propriedade do dado |
| **Qualidade de dados** | dado × contrato do próprio produto | campo obrigatório ausente, tipo incompatível, regra de negócio violada, chave duplicada | qualquer coisa em outro produto |
| **Reconciliação** (análise) | produto × produto | integridade referencial, contradição de estado, divergência de atributo comum, colisão de chave | o que nenhum contrato declara |

A camada de qualidade organiza-se em cinco dimensões — integridade, validade,
unicidade, atualidade e consistência — apuradas em três etapas: validação de
esquema, perfilamento estatístico e regras de negócio declaradas no contrato.

## Método experimental

Três decisões metodológicas merecem registro.

**Estado de controle imutável.** O `baseline/` é o grupo de controle. Se fosse
sobrescrito, comparações antes/depois perderiam sentido — por isso sua integridade
é protegida por soma de verificação agregada (`CHECKSUM`) e manifesto de hashes
por arquivo (`MANIFEST`), verificados a cada restauração.

**Uma intervenção por cenário.** Cada cenário altera exatamente um aspecto —
apenas o dado, apenas o contrato, apenas a política — para que o efeito observado
seja atribuível.

**Verificação de que os verificadores reprovam.** Durante o desenvolvimento
constatou-se que verificações automatizadas podem executar, reportar aprovação e
serem *estruturalmente incapazes* de reprovar: por compararem identificadores que
nenhum contrato usa, por testarem presença de chaves que a camada de adaptação
sempre cria, ou por referenciarem atributos que nenhum produto publica. Um
relatório inteiramente verde só significa algo se as verificações puderem
reprovar. Daí o autoteste e as injeções controladas de registros inválidos.

## Cenários executados

Cada pasta em `experimentos/` contém os dados e contratos alterados, os relatórios
gerados e um `alteracoes.json` que registra a intervenção, o resultado por camada
e os achados.

| Cenário | Intervenção | Governança | Qualidade | Reconciliação |
|---|---|---|---|---|
| **C1** Integridade referencial | 5 faturas logísticas passam a apontar para faturas inexistentes | PASS | PASS | **detecta** |
| **C2** Contradição de estado | 5 operações logísticas marcadas como concluídas sobre faturas canceladas | PASS | PASS | **detecta** |
| **C3a** Contrato evolui sem o dado | dois atributos obrigatórios acrescentados ao contrato | PASS | **FAIL** | — |
| **C3b** Dado evolui sem o contrato | dois atributos publicados sem declaração no contrato | PASS | **FAIL** | — |
| **C4a** Metadados ausentes | remoção de `owner` e `tags` do contrato | **FAIL** | PASS | — |
| **C4b** Cobertura das políticas | nenhuma — é medição de quanto da política é executável | — | — | — |
| **C5** Duplicação de entidade-mestre | uma fatura duplicada em contas-a-pagar | PASS | **FAIL** | **detecta** |

A leitura do conjunto é o resultado central do trabalho: **nenhuma inconsistência
entre domínios foi detectada pela governança computacional ou pela validação de
qualidade.** C1, C2 e C5 só se tornaram visíveis pelo instrumento externo de
reconciliação. Em contrapartida, C4a demonstra que a governança reprova de fato o
que foi programada para verificar — o silêncio dos demais cenários não decorre de
inércia do mecanismo, e sim da ausência da verificação correspondente.

## Métricas coletadas

Valores no estado de controle, para referência:

| Métrica | Origem | Baseline |
|---|---|---|
| Registros válidos | `data_quality_validation.json` | 4.939/4.939 |
| Contratos conformes | `governance_compliance.json` | 3/3 |
| Checagens de governança por contrato | idem | 75–76 |
| Cobertura das políticas | `experimentos/cenario4b/` | 9 automatizadas · 10 declaratórias · 2 parciais |
| Integridade referencial | `cross_domain_divergences_analysis.json` | 100% |
| Taxa de convergência | idem | 100% |
| Granularidade 1:N | `invoice_keyed_reconciliation.json` | 161 faturas |
| Divergência de valor AP × AR | idem | 160 faturas |

As duas últimas são **métricas de contexto**, ou controle negativo: divergências
corretas por desenho, que devem permanecer estáveis entre cenários. Variação nelas
indica efeito colateral da intervenção, não descoberta.

## Limitações

- **Não há camada de execução.** Os produtos são arquivos, não serviços.
  Disponibilidade, latência, vazão e orçamento de erro existem apenas como
  compromisso declarado — quebra real de SLO não é observável.
- **A governança verifica declarações, não histórico.** Sem registro de esquemas
  versionados, remover um atributo obrigatório sob a mesma versão atravessa a
  verificação.
- **Poucos atributos comparáveis.** Dos atributos publicados, apenas a unidade
  monetária é diretamente confrontável entre domínios.
- **Sem cadeia de consumo entre produtos.** Cenários de propagação de qualidade não
  são reproduzíveis.
- **Geradores não determinísticos.** Reexecutá-los não reproduz o snapshot; o
  estado de controle é preservado por cópia, nunca regenerado.

## Requisitos

Python 3.10 ou superior e **PyYAML** como única dependência externa. Não são
utilizadas bibliotecas de qualidade de dados prontas — a avaliação das regras
declaradas nos contratos é implementada sobre a biblioteca padrão, por meio de
análise sintática restrita, sem `eval`.

```bash
pip install -r requirements.txt
```

---

Desenvolvido como Trabalho de Conclusão de Curso em Ciência da Computação ·
Universidade Federal do ABC · 2026
