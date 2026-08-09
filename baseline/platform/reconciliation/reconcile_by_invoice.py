"""Reconciliação fatura-a-fatura sobre output ports entity.

Demonstração da tese:
  "Compartilhar a chave (invoice_id) entre produtos é necessário para
   reconciliação fina, mas INSUFICIENTE para alinhamento — divergências
   de vocabulário, regras de domínio, granularidade e janela temporal
   persistem mesmo com a chave casada."

Lê os 3 output ports entity publicados (sob a master_entity `invoice` da
política federada) e executa a junção. Reporta:

  • Cobertura: % de invoice_ids presentes em cada par de produtos
  • Persistentes (mesmo com chave igual):
      - Status divergente (vocabulário PAID vs SETTLED, etc.)
      - Valor divergente (regras de domínio: retenções, juros, frete)
      - Mês divergente (janela de processamento)
      - Granularidade divergente (1:N AP↔Logística)
  • Novas categorias que SURGEM com chave compartilhada:
      - Integridade referencial (logística -> fatura inexistente)
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List

import yaml

AP_PATH = "domains/financeiro/contas-a-pagar/data/contas_a_pagar.jsonl"
AR_PATH = "domains/financeiro/contas-a-receber/data/contas_a_receber.jsonl"
LOG_PATH = "domains/logistica/data/logistics.jsonl"
POLICIES_PATH = "governance/policies.yaml"
REPORT_PATH = "reports/invoice_keyed_reconciliation.json"

STATUS_CANONICAL = {
    "ABERTO": "ABERTO",
    "PAGO": "PAGO",
    "LIQUIDADO": "PAGO",
    "CANCELADO": "CANCELADO",
}

AMOUNT_TOLERANCE_PCT = 0.05  # 5% (retenções fiscais, descontos)


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def index_by_invoice(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Indexa os registros pela master entity, uma linha por `invoice_id`.

    A indexação PRESSUPÕE unicidade da chave. Quando ela não se verifica, a
    ocorrência seguinte sobrescreve a anterior e o registro desaparece da
    análise sem qualquer sinal — o relatório informa 2.000 faturas para um
    arquivo de 2.001 linhas, e a reconciliação compara um dos registros
    ignorando a existência do outro. É perda de informação no instrumento, não
    apenas violação do contrato, e por isso a colisão precisa ser reportada
    aqui, e não só na camada de qualidade.
    """
    idx: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        idx[r["invoice_id"]] = r
    return idx


def detectar_colisoes(rows: List[Dict[str, Any]], produto: str) -> Dict[str, Any]:
    """Registros que a indexação por `invoice_id` colapsaria.

    Distingue dois casos, porque a consequência analítica é diferente:

      • duplicata idêntica — o registro sobrescrito é igual ao que fica, então
        nada se perde no conteúdo, apenas a contagem fica errada;
      • duplicata divergente — os registros diferem em algum atributo, e a
        reconciliação passa a analisar um deles ignorando o outro. Aqui a
        conclusão sobre a fatura depende da ordem das linhas no arquivo.
    """
    ocorrencias: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        ocorrencias[r["invoice_id"]].append(r)

    duplicadas = {inv: regs for inv, regs in ocorrencias.items() if len(regs) > 1}
    identicas, divergentes = [], []
    for inv, regs in sorted(duplicadas.items()):
        primeiro = json.dumps(regs[0], sort_keys=True, ensure_ascii=False)
        todas_iguais = all(
            json.dumps(r, sort_keys=True, ensure_ascii=False) == primeiro for r in regs[1:])
        alvo = identicas if todas_iguais else divergentes
        campos_divergentes = sorted({
            campo for r in regs[1:] for campo in set(regs[0]) | set(r)
            if regs[0].get(campo) != r.get(campo)
        })
        alvo.append({
            "invoice_id": inv,
            "ocorrencias": len(regs),
            "registros_descartados": len(regs) - 1,
            **({"campos_divergentes": campos_divergentes} if campos_divergentes else {}),
        })

    return {
        "produto": produto,
        "linhas_no_arquivo": len(rows),
        "faturas_distintas": len(ocorrencias),
        "chaves_duplicadas": len(duplicadas),
        "registros_descartados": sum(len(r) - 1 for r in duplicadas.values()),
        "duplicatas_identicas": identicas[:50],
        "duplicatas_divergentes": divergentes[:50],
    }


def canonical_status(status: str) -> str:
    return STATUS_CANONICAL.get(status, "UNKNOWN")


def reconcile_ap_vs_ar(ap_idx: Dict[str, Dict[str, Any]], ar_idx: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Reconciliação fina AP vs AR: mesma fatura nos dois produtos."""
    ap_ids = set(ap_idx.keys())
    ar_ids = set(ar_idx.keys())
    common = ap_ids & ar_ids

    counters = defaultdict(int)
    persistent_divergences = {
        "status_vocabulary_diff": [],
        "amount_business_rules_diff": [],
        "issue_month_diff": [],
    }
    referential_integrity = {
        "in_ap_only": sorted(ap_ids - ar_ids)[:50],
        "in_ar_only": sorted(ar_ids - ap_ids)[:50],
    }

    for inv_id in common:
        ap = ap_idx[inv_id]
        ar = ar_idx[inv_id]

        # O atributo publicado chama-se `status` nos output ports analíticos.
        # Este trecho lia `situacao`, nome inexistente: ambos os lados
        # resultavam em string vazia, de modo que as comparações abaixo nunca
        # eram satisfeitas e os contadores `status_vocabulary_diff` e
        # `status_canonical_diff` permaneciam sempre em zero.
        ap_status_raw = ap.get("status", "")
        ar_status_raw = ar.get("status", "")
        ap_canon = canonical_status(ap_status_raw)
        ar_canon = canonical_status(ar_status_raw)

        # Vocabulário: mesmo conceito canônico, palavras diferentes (ex.: PAID vs SETTLED)
        if ap_status_raw != ar_status_raw and ap_canon == ar_canon:
            counters["status_vocabulary_diff"] += 1
            if len(persistent_divergences["status_vocabulary_diff"]) < 50:
                persistent_divergences["status_vocabulary_diff"].append({
                    "invoice_id": inv_id,
                    "ap_status_raw": ap_status_raw,
                    "ar_status_raw": ar_status_raw,
                    "canonical": ap_canon,
                })
        # Status canônico realmente diverge (uma quitada, outra em aberto)
        if ap_canon != ar_canon:
            counters["status_canonical_diff"] += 1

        # Valor: AP grava `amount` (líquido), AR grava `gross_amount` (bruto).
        # São naturalmente diferentes por desenho de domínio.
        ap_amount = float(ap.get("valor_liquido", 0) or 0)
        ar_gross = float(ar.get("valor_bruto", 0) or 0)
        if max(ap_amount, ar_gross) > 0:
            diff_pct = abs(ap_amount - ar_gross) / max(ap_amount, ar_gross)
            if diff_pct > AMOUNT_TOLERANCE_PCT:
                counters["amount_business_rules_diff"] += 1
                if len(persistent_divergences["amount_business_rules_diff"]) < 50:
                    persistent_divergences["amount_business_rules_diff"].append({
                        "invoice_id": inv_id,
                        "ap_amount": round(ap_amount, 2),
                        "ar_gross_amount": round(ar_gross, 2),
                        "diff_pct": round(diff_pct * 100, 2),
                        "root_cause": "AP retém impostos; AR aplica descontos/juros — mesma fatura, regras diferentes",
                    })

        # Mês de emissão: pode divergir por janela de processamento
        if ap.get("mes_emissao") != ar.get("mes_emissao"):
            counters["issue_month_diff"] += 1
            if len(persistent_divergences["issue_month_diff"]) < 50:
                persistent_divergences["issue_month_diff"].append({
                    "invoice_id": inv_id,
                    "ap_issue_month": ap.get("mes_emissao"),
                    "ar_issue_month": ar.get("mes_emissao"),
                })

    return {
        "comparison": "ap_invoice_keyed vs ar_invoice_keyed",
        "ap_total": len(ap_ids),
        "ar_total": len(ar_ids),
        "common_keys": len(common),
        "coverage_ap_in_ar_pct": round(len(common) / max(len(ap_ids), 1) * 100, 2),
        "coverage_ar_in_ap_pct": round(len(common) / max(len(ar_ids), 1) * 100, 2),
        "persistent_divergences_summary": dict(counters),
        "persistent_divergences_examples": persistent_divergences,
        "referential_integrity": {
            "ap_only_count": len(ap_ids - ar_ids),
            "ar_only_count": len(ar_ids - ap_ids),
            "examples": referential_integrity,
        },
    }


def reconcile_logistics_vs_finance(
    log_idx: Dict[str, Dict[str, Any]],
    ap_idx: Dict[str, Dict[str, Any]],
    ar_idx: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Cross-domain: logística (1:N por fatura) vs financeiro (1:1 por fatura)."""
    log_ids = set(log_idx.keys())
    finance_ids = set(ap_idx.keys()) | set(ar_idx.keys())

    counters = defaultdict(int)
    referential = {
        "logistics_pointing_to_missing_invoice": [],
        "operations_with_no_finance_counterpart": 0,
    }
    granularity = {"one_to_many_examples": []}
    persistent = {
        "month_window_diff": [],
        "cross_domain_state_contradiction": [],
        "cross_domain_attribute_divergence": [],
    }
    informational = {"value_ratio_samples": []}
    value_ratios = []

    for inv_id, log in log_idx.items():
        # Categoria nova: integridade referencial federada
        if inv_id not in finance_ids:
            counters["referential_integrity_violation"] += 1
            referential["operations_with_no_finance_counterpart"] += 1
            if len(referential["logistics_pointing_to_missing_invoice"]) < 50:
                referential["logistics_pointing_to_missing_invoice"].append({
                    "invoice_id": inv_id,
                    "operation_count": log.get("qtd_operacoes"),
                    "total_value": log.get("valor_total"),
                })
            continue

        # Granularidade: logística agrega N operações por fatura
        if int(log.get("qtd_operacoes", 0) or 0) > 1:
            counters["granularity_one_to_many"] += 1
            if len(granularity["one_to_many_examples"]) < 30:
                granularity["one_to_many_examples"].append({
                    "invoice_id": inv_id,
                    "operation_count": log["qtd_operacoes"],
                    # Nomes publicados nos output ports: `dsc_tipo_operacao` e
                    # `status`. Este trecho lia `tipos_operacao` e `situacoes`,
                    # inexistentes — os exemplos saíam sempre com listas vazias.
                    "operation_types": log.get("dsc_tipo_operacao", []),
                    "statuses": log.get("status", []),
                })

        # Coerência de estado entre domínios.
        #
        # Fatura CANCELADO no Financeiro não admite operação CONCLUIDO na
        # Logística: a conclusão afirma um fato (entrega realizada)
        # incompatível com o cancelamento da obrigação. Estados transitórios
        # (PENDENTE, EM_PROCESSAMENTO) não são contraditórios — podem coexistir
        # com um cancelamento ainda não propagado.
        #
        # Verificação do instrumento de análise: nenhuma camada da arquitetura
        # relaciona os vocabulários de estado dos dois domínios.
        fin_ref = ap_idx.get(inv_id) or ar_idx.get(inv_id)
        if fin_ref and fin_ref.get("status") == "CANCELADO":
            log_states = log.get("status", [])
            if not isinstance(log_states, list):
                log_states = [log_states]
            if "CONCLUIDO" in log_states:
                counters["cross_domain_state_contradiction"] += 1
                persistent["cross_domain_state_contradiction"].append({
                    "invoice_id": inv_id,
                    "status_logistica": log_states,
                    "status_financeiro": fin_ref.get("status"),
                })

        # Atributos de mesma semântica publicados pelos dois domínios.
        #
        # `dsc_moeda` é padrão semântico global (ISO-4217, restrito a BRL na
        # política federada). Cada produto valida a própria moeda contra o seu
        # contrato, mas nenhuma camada da arquitetura verifica se os dois
        # domínios publicam a MESMA moeda para a mesma fatura — se divergirem,
        # os valores deixam de ser somáveis sem que nada sinalize.
        if fin_ref:
            for atributo in ("dsc_moeda",):
                valor_fin = fin_ref.get(atributo)
                valor_log = log.get(atributo)
                if valor_fin is not None and valor_log is not None and valor_log != valor_fin:
                    counters["cross_domain_attribute_divergence"] += 1
                    persistent["cross_domain_attribute_divergence"].append({
                        "invoice_id": inv_id,
                        "atributo": atributo,
                        "valor_logistica": valor_log,
                        "valor_financeiro": valor_fin,
                    })

        # Valor: comparar com a contraparte financeira correta
        log_value = float(log.get("valor_total", 0) or 0)
        ap = ap_idx.get(inv_id)
        ar = ar_idx.get(inv_id)
        finance_value = None
        finance_side = None
        if ap is not None:
            finance_value = float(ap.get("valor_liquido", 0) or 0)
            finance_side = "ap"
        elif ar is not None:
            finance_value = float(ar.get("valor_bruto", 0) or 0)
            finance_side = "ar"

        # Razão entre valores logístico e financeiro: ACHADO INFORMACIONAL.
        #
        # `valor_total` da logística (mercadoria + frete + seguro + imposto) e o
        # valor da fatura são grandezas distintas — não existe regra de negócio
        # que as obrigue a coincidir, e os geradores as produzem de forma
        # independente (vinculam a chave `invoice_id`, não os montantes).
        # Aplicar tolerância percentual sobre grandezas não comparáveis
        # produzia 912 falsos positivos em 939 faturas.
        #
        # Registrado como estatística descritiva. Só viraria validação se o
        # contrato declarasse a relação esperada (p.ex. "frete ≤ X% da fatura").
        if finance_value is not None and log_value > 0 and finance_value > 0:
            counters["value_ratio_observed"] += 1
            value_ratios.append(log_value / finance_value)
            if len(informational["value_ratio_samples"]) < 20:
                informational["value_ratio_samples"].append({
                    "invoice_id": inv_id,
                    "logistics_value": round(log_value, 2),
                    "finance_value": round(finance_value, 2),
                    "finance_side": finance_side,
                    "ratio": round(log_value / finance_value, 4),
                    "note": "grandezas distintas; sem regra declarada no contrato",
                })

        # Mês: logística pode operar em outro mês.
        # `meses_operacao` é a LISTA de meses em que a fatura teve operação
        # logística (ex.: ["2026-07"]).
        log_months = set(log.get("meses_operacao", []))
        finance_month = (ap or ar).get("mes_emissao") if (ap or ar) else None
        if finance_month and log_months and finance_month not in log_months:
            counters["month_window_diff"] += 1
            persistent["month_window_diff"].append({
                "invoice_id": inv_id,
                "finance_issue_month": finance_month,
                "logistics_operation_months": sorted(log_months),
            })

    return {
        "comparison": "logistics_invoice_keyed vs finance_invoice_keyed",
        "logistics_total": len(log_ids),
        "finance_total": len(finance_ids),
        "logistics_with_finance_match": len(log_ids & finance_ids),
        "coverage_logistics_in_finance_pct": round(
            len(log_ids & finance_ids) / max(len(log_ids), 1) * 100, 2
        ),
        "counters": dict(counters),
        "referential_integrity": referential,
        "granularity": granularity,
        "persistent_divergences_examples": persistent,
        "informational": informational,
        "value_ratio_stats": (
            {
                "description": ("razão valor_total logístico / valor da fatura; "
                                "grandezas distintas, sem regra que as vincule"),
                "n": len(value_ratios),
                "min": round(min(value_ratios), 4),
                "p50": round(sorted(value_ratios)[len(value_ratios) // 2], 4),
                "max": round(max(value_ratios), 4),
            }
            if value_ratios else None
        ),
    }


def main() -> None:
    ap_rows = read_jsonl(AP_PATH)
    ar_rows = read_jsonl(AR_PATH)
    log_rows = read_jsonl(LOG_PATH)

    # Colisões de chave são apuradas ANTES da indexação: depois dela a evidência
    # já se perdeu, porque o dicionário guarda uma linha por invoice_id.
    colisoes = [
        detectar_colisoes(ap_rows, "contas-a-pagar"),
        detectar_colisoes(ar_rows, "contas-a-receber"),
        detectar_colisoes(log_rows, "operacoes-logistica"),
    ]
    colisoes_totais = sum(c["chaves_duplicadas"] for c in colisoes)

    ap_idx = index_by_invoice(ap_rows)
    ar_idx = index_by_invoice(ar_rows)
    log_idx = index_by_invoice(log_rows)

    intra = reconcile_ap_vs_ar(ap_idx, ar_idx)
    cross = reconcile_logistics_vs_finance(log_idx, ap_idx, ar_idx)

    # Resumo da tese: quantas divergências persistem MESMO com chave casada
    intra_persistent_total = sum(intra["persistent_divergences_summary"].values())
    cross_persistent_total = (
        cross["counters"].get("cross_domain_state_contradiction", 0)
        + cross["counters"].get("cross_domain_attribute_divergence", 0)
        + cross["counters"].get("month_window_diff", 0)
        + cross["counters"].get("granularity_one_to_many", 0)
    )

    with open(POLICIES_PATH, "r", encoding="utf-8") as f:
        policies = yaml.safe_load(f)
    master_entities = (
        policies.get("spec", {}).get("interoperability", {}).get("master_entities", [])
    )

    report = {
        "execution_timestamp": datetime.now(timezone.utc).isoformat(),
        "thesis": (
            "Compartilhar invoice_id (master entity federada) é necessário para "
            "reconciliação fina, mas insuficiente para eliminar divergências."
        ),
        "master_entity_in_use": next(
            (m for m in master_entities if m.get("id") == "invoice"), None
        ),
        "master_key_collisions": {
            "duplicated_keys_total": colisoes_totais,
            "records_discarded_total": sum(c["registros_descartados"] for c in colisoes),
            "by_product": colisoes,
        },
        "ap_vs_ar": intra,
        "logistics_vs_finance": cross,
        "summary": {
            "intra_domain_invoices_compared": intra["common_keys"],
            "intra_domain_persistent_divergences_total": intra_persistent_total,
            "cross_domain_invoices_with_match": cross["logistics_with_finance_match"],
            "cross_domain_persistent_divergences_total": cross_persistent_total,
            "new_category_referential_integrity_violations": cross["counters"].get(
                "referential_integrity_violation", 0
            ),
            "master_key_collisions": colisoes_totais,
        },
        "conclusions": [
            texto for ocorrencias, texto in (
                (colisoes_totais,
                 f"{colisoes_totais} invoice_id repetido(s) dentro de um mesmo produto. "
                 + "; ".join(
                     f"{c['produto']}: " + ", ".join(
                         d["invoice_id"] for d in
                         c["duplicatas_identicas"] + c["duplicatas_divergentes"])
                     for c in colisoes if c["chaves_duplicadas"])
                 + ". A reconciliação indexa uma linha por chave, de modo que "
                 f"{sum(c['registros_descartados'] for c in colisoes)} registro(s) "
                 "seriam descartados silenciosamente: a chave compartilhada só "
                 "sustenta a junção se a unicidade prometida no contrato se verificar."),
                (intra["persistent_divergences_summary"].get("status_vocabulary_diff", 0),
                 "Mesma chave invoice_id — vocabulário de status diverge em "
                 f"{intra['persistent_divergences_summary'].get('status_vocabulary_diff', 0)} "
                 "faturas de AP e AR. Sem canonicalização federada, consumidores "
                 "filtrariam errado."),
                (intra["persistent_divergences_summary"].get("amount_business_rules_diff", 0),
                 "Mesma chave invoice_id — valor de fatura diverge em "
                 f"{intra['persistent_divergences_summary'].get('amount_business_rules_diff', 0)} "
                 "casos AP vs AR (retenções fiscais vs descontos/juros). Divergência é "
                 "correta por desenho."),
                (cross["counters"].get("granularity_one_to_many", 0),
                 "Mesma chave invoice_id — granularidade 1:N entre Logística e Financeiro "
                 f"em {cross['counters'].get('granularity_one_to_many', 0)} faturas. "
                 "Chave compartilhada não unifica grão."),
                (cross["counters"].get("month_window_diff", 0),
                 "Mesma chave invoice_id — janela temporal divergente entre domínios em "
                 f"{cross['counters'].get('month_window_diff', 0)} faturas (mês de operação "
                 "logística vs mês de emissão da fatura). Nenhuma política declara a "
                 "relação esperada entre os dois períodos."),
                (cross["counters"].get("cross_domain_attribute_divergence", 0),
                 "Mesma chave invoice_id — atributo comum divergente entre domínios em "
                 f"{cross['counters'].get('cross_domain_attribute_divergence', 0)} faturas "
                 "(dsc_moeda). Cada produto valida a própria moeda contra o seu contrato; "
                 "nenhuma camada verifica se os dois domínios publicam a mesma unidade."),
                (cross["counters"].get("cross_domain_state_contradiction", 0),
                 "Mesma chave invoice_id — contradição de estado entre domínios em "
                 f"{cross['counters'].get('cross_domain_state_contradiction', 0)} faturas "
                 "(logística CONCLUIDO vs financeiro CANCELADO). Cada estado é válido no "
                 "vocabulário de seu domínio; nenhuma camada da arquitetura relaciona os dois."),
                (cross["counters"].get("referential_integrity_violation", 0),
                 f"{cross['counters'].get('referential_integrity_violation', 0)} faturas "
                 "logísticas apontam para faturas inexistentes no Financeiro. São elas: "
                 + ", ".join(sorted(
                     e["invoice_id"] for e in
                     cross["referential_integrity"]["logistics_pointing_to_missing_invoice"]
                 )) + "."),
            ) if ocorrencias
        ],
    }

    os.makedirs("reports", exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("🔑 Reconciliação fatura-a-fatura (output ports entity)")
    print("=" * 65)
    print(f"📦 AP keyed             : {intra['ap_total']} faturas")
    print(f"📦 AR keyed             : {intra['ar_total']} faturas")
    print(f"📦 Logística keyed      : {cross['logistics_total']} faturas distintas")
    print(f"🔗 Cobertura AP∩AR      : {intra['coverage_ap_in_ar_pct']}%")
    print(
        f"🔗 Cobertura Log→Finance : {cross['coverage_logistics_in_finance_pct']}%"
    )
    print()

    # Colisão de chave é reportada antes das divergências: ela compromete a
    # própria base da comparação, não é um resultado dela.
    if colisoes_totais:
        print("🔑 Colisão na master entity (a indexação descartaria registros):")
        for c in colisoes:
            if not c["chaves_duplicadas"]:
                continue
            print(f"   • {c['produto']}: {c['linhas_no_arquivo']} linhas → "
                  f"{c['faturas_distintas']} faturas distintas | "
                  f"{c['chaves_duplicadas']} chave(s) duplicada(s), "
                  f"{c['registros_descartados']} registro(s) descartado(s)")
            for d in c["duplicatas_divergentes"]:
                print(f"     ⚠️  {d['invoice_id']} ×{d['ocorrencias']} — registros DIVERGEM "
                      f"em {', '.join(d['campos_divergentes'])}; a conclusão sobre esta "
                      f"fatura depende da ordem das linhas no arquivo")
            for d in c["duplicatas_identicas"]:
                print(f"     • {d['invoice_id']} ×{d['ocorrencias']} — registros idênticos; "
                      f"perde-se a contagem, não o conteúdo")
        print()

    # Contadores informacionais: não são divergências, exibidos à parte.
    INFORMATIONAL_KEYS = {"value_ratio_observed"}

    print("⚠️  Divergências PERSISTENTES (mesmo com chave casada):")
    for k, v in intra["persistent_divergences_summary"].items():
        print(f"   • intra-domain  | {k:35s}: {v}")
    for k, v in cross["counters"].items():
        if k not in INFORMATIONAL_KEYS:
            print(f"   • cross-domain  | {k:35s}: {v}")

    for chave, rotulo in (("cross_domain_attribute_divergence", "Atributo comum divergente"),
                          ("cross_domain_state_contradiction", "Contradição de estado"),
                          ("month_window_diff", "Desalinhamento de janela temporal")):
        casos = sorted(cross["persistent_divergences_examples"].get(chave, []),
                       key=lambda e: e["invoice_id"])
        if not casos:
            continue
        print(f"\n🚨 {rotulo} entre domínios ({len(casos)}):")
        for e in casos[:10]:
            if chave == "cross_domain_attribute_divergence":
                print(f"   • {e['invoice_id']}: {e['atributo']} "
                      f"logística='{e['valor_logistica']}' vs financeiro='{e['valor_financeiro']}'")
            elif chave == "month_window_diff":
                print(f"   • {e['invoice_id']}: operação em "
                      f"{e['logistics_operation_months']} vs emissão em "
                      f"{e['finance_issue_month']}")
            else:
                print(f"   • {e['invoice_id']}: logística={e['status_logistica']} "
                      f"vs financeiro={e['status_financeiro']}")
        if len(casos) > 10:
            print(f"   … e mais {len(casos)-10}")
        ids = [e["invoice_id"] for e in casos]
        print(f"   invoice_id afetados ({len(ids)}):")
        for i in range(0, len(ids), 6):
            print("      " + ", ".join(ids[i:i+6]))

    print()
    # Exibe apenas conclusões com ocorrência efetiva: uma conclusão com
    # contagem zero não descreve achado algum e apenas polui a saída.
    if report["conclusions"]:
        print("📋 Conclusões da tese:")
        for c in report["conclusions"]:
            print(f"   • {c}")
    print(f"\n📄 Relatório completo em: {REPORT_PATH}")


if __name__ == "__main__":
    main()
