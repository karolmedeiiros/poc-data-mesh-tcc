# Baseline — snapshot base do trabalho

> ## ⚠️ IMUTÁVEL — NÃO ATUALIZAR
>
> Este diretório é o **estado de controle** de todos os experimentos. Nenhuma alteração
> feita na raiz do projeto deve ser refletida aqui.
>
> ```
> baseline/  ──restore──▶  raiz do projeto
>            ◀──── NUNCA ────
> ```
>
> **Nunca rode `rsync ... ./ baseline/`** — sobrescreve o snapshot. O projeto não é
> versionado em git: se isto for destruído, não há como recuperar.
>
> Precisa de outro ponto de comparação? Crie uma pasta nova: `cp -a baseline/ baseline-v2/`

Snapshot congelado da PoC Data Mesh em **2026-08-01**.
Excluídos: `.git/`, `.venv/`, `__pycache__/`, `*.pyc`.

## Estado das métricas neste snapshot

Valores de referência do grupo de controle:

| Métrica | Valor |
|---|---|
| Data Quality | 4939/4939 válidos (100 %) |
| Governance Compliance | 3/3 contratos |
| Contract Validation | 3/3 válidos |
| Convergência cross-domain | 100 % |
| Integridade referencial | 100 % (0 órfãos) |
| Divergências persistentes | 321 (160 valor AP↔AR + 161 granularidade 1:N) |

Órfãos verificados e zerados em todos os pares: AP↔AR, Logística→Financeiro,
publicado↔operacional, e duplicatas de master entity nos três produtos.

## Conteúdo

| Diretório | Descrição |
|---|---|
| `domains/` | Data products por domínio (financeiro: contas-a-pagar, contas-a-receber; logística), cada um com `data_contract.yaml` e dados analíticos |
| `operational/` | Dados operacionais "naturais" de origem, por domínio |
| `platform/` | Geradores, qualidade, catálogo e reconciliação |
| `governance/` | Governança computacional federada: políticas e validadores |
| `reports/` | Saídas de validação e análise de divergências |
| `odcs_adapter.py` | Adaptador para o padrão Open Data Contract Standard |

## Restaurar

```bash
bash baseline/restore.sh            # com confirmação
bash baseline/restore.sh --dry-run  # só mostra o que mudaria
bash baseline/restore.sh --force    # sem perguntar
```

O restore sobrescreve a raiz com este snapshot e remove arquivos criados depois dele.
Não toca em `.git/`, `.venv/`, `__pycache__/` nem neste diretório.

> O restore preserva `experimentos/` e `docs/`: os resultados dos cenários e os textos
> do trabalho não são afetados. Qualquer outro arquivo fora do snapshot é removido.
