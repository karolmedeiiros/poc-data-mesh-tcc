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
    return {r["invoice_id"]: r for r in rows}


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

        ap_status_raw = ap.get("situacao", "")
        ar_status_raw = ar.get("situacao", "")
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
        "value_business_rules_diff": [],
        "month_window_diff": [],
    }

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
                    "operation_types": log.get("tipos_operacao", []),
                    "statuses": log.get("situacoes", []),
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

        if finance_value is not None and max(log_value, finance_value) > 0:
            diff_pct = abs(log_value - finance_value) / max(log_value, finance_value)
            if diff_pct > AMOUNT_TOLERANCE_PCT:
                counters["value_business_rules_diff"] += 1
                if len(persistent["value_business_rules_diff"]) < 50:
                    persistent["value_business_rules_diff"].append({
                        "invoice_id": inv_id,
                        "logistics_value": round(log_value, 2),
                        "finance_value": round(finance_value, 2),
                        "finance_side": finance_side,
                        "diff_pct": round(diff_pct * 100, 2),
                        "root_cause": "Frete/manuseio (log) vs valor de fatura (finance) — naturais por desenho",
                    })

        # Mês: logística pode operar em outro mês
        log_months = set(log.get("meses_operacao", []))
        finance_month = (ap or ar).get("mes_emissao") if (ap or ar) else None
        if finance_month and log_months and finance_month not in log_months:
            counters["month_window_diff"] += 1
            if len(persistent["month_window_diff"]) < 50:
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
    }


def main() -> None:
    ap_rows = read_jsonl(AP_PATH)
    ar_rows = read_jsonl(AR_PATH)
    log_rows = read_jsonl(LOG_PATH)

    ap_idx = index_by_invoice(ap_rows)
    ar_idx = index_by_invoice(ar_rows)
    log_idx = index_by_invoice(log_rows)

    intra = reconcile_ap_vs_ar(ap_idx, ar_idx)
    cross = reconcile_logistics_vs_finance(log_idx, ap_idx, ar_idx)

    # Resumo da tese: quantas divergências persistem MESMO com chave casada
    intra_persistent_total = sum(intra["persistent_divergences_summary"].values())
    cross_persistent_total = (
        cross["counters"].get("value_business_rules_diff", 0)
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
        },
        "conclusions": [
            (
                "Mesma chave invoice_id — vocabulário de status diverge em "
                f"{intra['persistent_divergences_summary'].get('status_vocabulary_diff', 0)} faturas "
                "(PAID vs SETTLED). Sem canonicalização federada, consumidores filtrariam errado."
            ),
            (
                "Mesma chave invoice_id — valor de fatura diverge em "
                f"{intra['persistent_divergences_summary'].get('amount_business_rules_diff', 0)} casos "
                "AP vs AR (retenções fiscais vs descontos/juros). Divergência é correta por desenho."
            ),
            (
                "Mesma chave invoice_id — granularidade 1:N entre Logística e Financeiro em "
                f"{cross['counters'].get('granularity_one_to_many', 0)} faturas. "
                "Chave compartilhada não unifica grão."
            ),
            (
                "Surgiu nova categoria de vulnerabilidade: integridade referencial. "
                f"{cross['counters'].get('referential_integrity_violation', 0)} operações logísticas "
                "apontam para faturas que não existem no financeiro publicado."
            ),
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
    print("⚠️  Divergências PERSISTENTES (mesmo com chave casada):")
    for k, v in intra["persistent_divergences_summary"].items():
        print(f"   • intra-domain  | {k:35s}: {v}")
    for k, v in cross["counters"].items():
        print(f"   • cross-domain  | {k:35s}: {v}")
    print()
    print("📋 Conclusões da tese:")
    for c in report["conclusions"]:
        print(f"   • {c}")
    print(f"\n📄 Relatório completo em: {REPORT_PATH}")


if __name__ == "__main__":
    main()
