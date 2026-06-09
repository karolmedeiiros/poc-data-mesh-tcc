"""Gera os datasets analíticos (output ports) de cada produto de dados.

Padrão Data Mesh (datamesh-architecture.com):
- Entrada: dados operacionais brutos em `<domain>/<product>/operational/*.jsonl`
- Saída : output port publicado em `<domain>/<product>/data/*_analytical.jsonl`

Cada produto agrega seus próprios dados operacionais conforme regras do domínio,
sem depender de transformações centrais (autonomia + governança federativa).
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: str, rows: Iterable[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def month_of(date_str: str) -> str:
    """Extrai YYYY-MM de uma data ISO (date ou datetime)."""
    if not date_str:
        return "unknown"
    return date_str[:7]


def aggregate_ap(operational: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Output port analítico de Contas a Pagar.

    Agregado por (mês de emissão, status, tipo de fatura): volume e valor total.
    """
    buckets: Dict[tuple, Dict[str, Any]] = defaultdict(
        lambda: {"invoice_count": 0, "total_amount": 0.0, "total_base_amount": 0.0, "unique_suppliers": set()}
    )

    for row in operational:
        key = (month_of(row.get("issue_date", "")), row.get("status"), row.get("invoice_type"))
        b = buckets[key]
        b["invoice_count"] += 1
        b["total_amount"] += float(row.get("amount", 0) or 0)
        b["total_base_amount"] += float(row.get("base_amount", 0) or 0)
        if row.get("supplier_id"):
            b["unique_suppliers"].add(row["supplier_id"])

    generated_at = now_iso()
    output: List[Dict[str, Any]] = []
    for (issue_month, status, invoice_type), b in sorted(buckets.items()):
        count = b["invoice_count"]
        output.append({
            "issue_month": issue_month,
            "status": status,
            "invoice_type": invoice_type,
            "invoice_count": count,
            "supplier_count": len(b["unique_suppliers"]),
            "total_amount": round(b["total_amount"], 2),
            "total_base_amount": round(b["total_base_amount"], 2),
            "avg_amount": round(b["total_amount"] / count, 2) if count else 0.0,
            "currency": "BRL",
            "domain": "contas-a-pagar",
            "product": "contas-a-pagar",
            "generated_at": generated_at,
        })
    return output


def aggregate_ar(operational: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Output port analítico de Contas a Receber.

    Agregado por (mês de emissão, status, tipo de cliente).
    """
    buckets: Dict[tuple, Dict[str, Any]] = defaultdict(
        lambda: {"invoice_count": 0, "total_gross_amount": 0.0, "total_base_amount": 0.0, "unique_customers": set()}
    )

    for row in operational:
        key = (month_of(row.get("issue_date", "")), row.get("status"), row.get("customer_type"))
        b = buckets[key]
        b["invoice_count"] += 1
        b["total_gross_amount"] += float(row.get("gross_amount", 0) or 0)
        b["total_base_amount"] += float(row.get("base_amount", 0) or 0)
        if row.get("customer_id"):
            b["unique_customers"].add(row["customer_id"])

    generated_at = now_iso()
    output: List[Dict[str, Any]] = []
    for (issue_month, status, customer_type), b in sorted(buckets.items()):
        count = b["invoice_count"]
        output.append({
            "issue_month": issue_month,
            "status": status,
            "customer_type": customer_type,
            "invoice_count": count,
            "customer_count": len(b["unique_customers"]),
            "total_gross_amount": round(b["total_gross_amount"], 2),
            "total_base_amount": round(b["total_base_amount"], 2),
            "avg_gross_amount": round(b["total_gross_amount"] / count, 2) if count else 0.0,
            "currency": "BRL",
            "domain": "contas-a-receber",
            "product": "contas-a-receber",
            "generated_at": generated_at,
        })
    return output


def aggregate_logistics(operational: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Output port analítico de Logística.

    Agregado por (mês da operação, tipo de operação, status).
    """
    buckets: Dict[tuple, Dict[str, Any]] = defaultdict(
        lambda: {"operation_count": 0, "total_value": 0.0, "linked_to_invoice": 0, "unique_parties": set()}
    )

    for row in operational:
        op_date = row.get("operation_date") or row.get("updated_at", "")
        key = (month_of(op_date), row.get("operation_type"), row.get("status"))
        b = buckets[key]
        b["operation_count"] += 1
        b["total_value"] += float(row.get("total_value", 0) or 0)
        if row.get("related_invoice_id"):
            b["linked_to_invoice"] += 1
        if row.get("party_id"):
            b["unique_parties"].add(row["party_id"])

    generated_at = now_iso()
    output: List[Dict[str, Any]] = []
    for (operation_month, operation_type, status), b in sorted(buckets.items()):
        count = b["operation_count"]
        output.append({
            "operation_month": operation_month,
            "operation_type": operation_type,
            "status": status,
            "operation_count": count,
            "party_count": len(b["unique_parties"]),
            "linked_to_invoice_count": b["linked_to_invoice"],
            "linked_to_invoice_rate": round(b["linked_to_invoice"] / count, 4) if count else 0.0,
            "total_value": round(b["total_value"], 2),
            "avg_value": round(b["total_value"] / count, 2) if count else 0.0,
            "currency": "BRL",
            "domain": "logistica",
            "product": "operacoes-logistica",
            "generated_at": generated_at,
        })
    return output


# ----------------------------------------------------------------------------
# Entity-keyed output ports (chave compartilhada `invoice_id`).
# Cada domínio publica UMA linha por fatura/operação ligada à fatura,
# mantendo seu próprio vocabulário e regras de cálculo. Permite reconciliação
# fatura-a-fatura entre produtos sob a master_entity `invoice` da política
# federada — preservando, por desenho, divergências de domínio.
# ----------------------------------------------------------------------------

def keyed_ap(operational: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    generated_at = now_iso()
    out: List[Dict[str, Any]] = []
    for row in operational:
        invoice_id = row.get("invoice_id")
        if not invoice_id:
            continue
        out.append({
            "invoice_id": invoice_id,
            "issue_month": month_of(row.get("issue_date", "")),
            "status": row.get("status"),
            "invoice_type": row.get("invoice_type"),
            "supplier_id": row.get("supplier_id"),
            "amount": float(row.get("amount", 0) or 0),
            "base_amount": float(row.get("base_amount", 0) or 0),
            "currency": row.get("currency", "BRL"),
            "domain": "contas-a-pagar",
            "product": "contas-a-pagar-invoice-keyed",
            "generated_at": generated_at,
        })
    return out


def keyed_ar(operational: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    generated_at = now_iso()
    out: List[Dict[str, Any]] = []
    for row in operational:
        invoice_id = row.get("invoice_id")
        if not invoice_id:
            continue
        out.append({
            "invoice_id": invoice_id,
            "issue_month": month_of(row.get("issue_date", "")),
            "status": row.get("status"),
            "customer_type": row.get("customer_type"),
            "customer_id": row.get("customer_id"),
            "gross_amount": float(row.get("gross_amount", 0) or 0),
            "base_amount": float(row.get("base_amount", 0) or 0),
            "currency": row.get("currency", "BRL"),
            "domain": "contas-a-receber",
            "product": "contas-a-receber-invoice-keyed",
            "generated_at": generated_at,
        })
    return out


def keyed_logistics(operational: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Logística agrupa por invoice_id (uma fatura pode ter N operações)."""
    generated_at = now_iso()
    buckets: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "operation_count": 0,
        "total_value": 0.0,
        "operation_types": set(),
        "statuses": set(),
        "operation_months": set(),
    })
    for row in operational:
        invoice_id = row.get("related_invoice_id")
        if not invoice_id:
            continue
        b = buckets[invoice_id]
        b["operation_count"] += 1
        b["total_value"] += float(row.get("total_value", 0) or 0)
        b["operation_types"].add(row.get("operation_type", ""))
        b["statuses"].add(row.get("status", ""))
        op_date = row.get("operation_date") or row.get("updated_at", "")
        b["operation_months"].add(month_of(op_date))

    out: List[Dict[str, Any]] = []
    for invoice_id, b in sorted(buckets.items()):
        out.append({
            "invoice_id": invoice_id,
            "operation_count": b["operation_count"],
            "total_value": round(b["total_value"], 2),
            "operation_types": sorted(b["operation_types"]),
            "statuses": sorted(b["statuses"]),
            "operation_months": sorted(b["operation_months"]),
            "currency": "BRL",
            "domain": "logistica",
            "product": "operacoes-logistica-invoice-keyed",
            "generated_at": generated_at,
        })
    return out


PRODUCTS = [
    {
        "name": "contas-a-pagar",
        "operational": "domains/financeiro/contas-a-pagar/operational/ap_natural.jsonl",
        "analytical": "domains/financeiro/contas-a-pagar/data/ap_analytical.jsonl",
        "aggregator": aggregate_ap,
        "keyed": "domains/financeiro/contas-a-pagar/data/ap.jsonl",
        "keyed_builder": keyed_ap,
    },
    {
        "name": "contas-a-receber",
        "operational": "domains/financeiro/contas-a-receber/operational/ar_natural.jsonl",
        "analytical": "domains/financeiro/contas-a-receber/data/ar_analytical.jsonl",
        "aggregator": aggregate_ar,
        "keyed": "domains/financeiro/contas-a-receber/data/ar.jsonl",
        "keyed_builder": keyed_ar,
    },
    {
        "name": "operacoes-logistica",
        "operational": "domains/logistica/operational/logistics_natural.jsonl",
        "analytical": "domains/logistica/data/logistics_analytical.jsonl",
        "aggregator": aggregate_logistics,
        "keyed": "domains/logistica/data/logistics.jsonl",
        "keyed_builder": keyed_logistics,
    },
]


def main() -> None:
    print("Gerando output ports analíticos a partir dos dados operacionais...")
    for product in PRODUCTS:
        operational = read_jsonl(product["operational"])
        if not operational:
            print(f"  ! {product['name']}: operacional vazio em {product['operational']}")
            continue

        analytical = product["aggregator"](operational)
        write_jsonl(product["analytical"], analytical)

        keyed = product["keyed_builder"](operational)
        write_jsonl(product["keyed"], keyed)

        print(
            f"  - {product['name']}: {len(operational)} operacionais "
            f"-> {len(analytical)} agregados ({product['analytical']}) "
            f"| {len(keyed)} entity-keyed ({product['keyed']})"
        )


if __name__ == "__main__":
    main()
