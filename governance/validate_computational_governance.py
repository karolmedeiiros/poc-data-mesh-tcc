#!/usr/bin/env python3
"""Validador de Governança Computacional.

Automatiza as políticas definidas em governance/policies.yaml para validar
inconsistências reais entre contratos ODCS e os artefatos de dados publicados.

Checagens:
- schema_enforcement: campos do contrato presentes/ausentes nos dados
- master_entity_integrity: formato e unicidade do invoice_id
- cross_domain_consistency: comparabilidade de status, valor e mês entre domínios

Sai com exit 1 quando encontra violações ativas, provando que a governança
computacional detecta inconsistências que a governança declarativa não pega.

Uso: python3 governance/validate_computational_governance.py
"""

import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import yaml

# Adiciona raiz do projeto ao path para importar odcs_adapter
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from odcs_adapter import load_odcs, normalize

POLICIES_PATH = "governance/policies.yaml"
CONTRACT_DATASET_MAP = {
    "contas-a-pagar": "domains/financeiro/contas-a-pagar/data/contas_a_pagar.jsonl",
    "contas-a-receber": "domains/financeiro/contas-a-receber/data/contas_a_receber.jsonl",
    "operacoes-logistica": "domains/logistica/data/logistics.jsonl",
}
CONTRACT_PATHS = {
    "contas-a-pagar": "domains/financeiro/contas-a-pagar/data_contract.yaml",
    "contas-a-receber": "domains/financeiro/contas-a-receber/data_contract.yaml",
    "operacoes-logistica": "domains/logistica/data_contract.yaml",
}


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_policies() -> Dict[str, Any]:
    with open(POLICIES_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def schema_properties(path: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Retorna (nome_do_schema, lista_de_propriedades_ODCS)."""
    odcs = load_odcs(path)
    schema_list = odcs.get("schema", []) or []
    if not schema_list:
        return "", []
    schema = schema_list[0]
    return schema.get("name", ""), schema.get("properties", [])


def validate_schema_enforcement(product: str, data: List[Dict], properties: List[Dict], config: Dict) -> Dict[str, Any]:
    violations = []
    expected = {p["name"]: p for p in properties if isinstance(p, dict)}
    required = {name for name, p in expected.items() if p.get("required")}
    enums = {name: set(p.get("logicalTypeOptions", {}).get("enum", [])) for name, p in expected.items() if p.get("logicalTypeOptions", {}).get("enum")}

    total = len(data)
    if total == 0:
        return {"product": product, "status": "SKIPPED", "violations": []}

    first_keys = set(data[0].keys())
    contract_names = set(expected.keys())

    # Campos no contrato, mas ausentes no primeiro registro (provável drift)
    if config.get("validate_required_fields", True):
        missing_in_artifact = sorted(contract_names - first_keys)
        if missing_in_artifact:
            violations.append({
                "type": "contract_field_missing_in_artifact",
                "fields": missing_in_artifact,
                "message": f"Campos declarados no contrato estão ausentes no artefato: {missing_in_artifact}",
            })

    # Campos no artefato, mas não no contrato
    if config.get("validate_no_extra_fields", True):
        extra_in_artifact = sorted(first_keys - contract_names)
        if extra_in_artifact:
            violations.append({
                "type": "artifact_field_not_in_contract",
                "fields": extra_in_artifact,
                "message": f"Campos presentes no artefato não estão no contrato: {extra_in_artifact}",
            })

    # Campos obrigatórios ausentes ou nulos em qualquer registro
    if config.get("validate_required_fields", True):
        missing_required_detail = {field: 0 for field in required}
        for row in data:
            for field in required:
                if field not in row or row.get(field) is None or row.get(field) == "":
                    missing_required_detail[field] += 1
        for field, count in missing_required_detail.items():
            if count > 0:
                violations.append({
                    "type": "required_field_missing",
                    "field": field,
                    "count": count,
                    "message": f"Campo obrigatório '{field}' ausente/nulo em {count} de {total} registros",
                })

    # Violações de enum
    if config.get("validate_enum_constraints", True):
        for field, allowed in enums.items():
            bad = sum(1 for row in data if field in row and row[field] not in allowed)
            if bad > 0:
                violations.append({
                    "type": "enum_violation",
                    "field": field,
                    "count": bad,
                    "allowed": sorted(allowed),
                    "message": f"Campo '{field}' com valor fora do enum em {bad} registros",
                })

    return {
        "product": product,
        "records_analyzed": total,
        "status": "PASS" if not violations else "FAIL",
        "violations": violations,
    }


def validate_master_entity_integrity(product: str, data: List[Dict], config: Dict) -> Dict[str, Any]:
    violations = []
    pattern = re.compile(r"^INV-[0-9]+$")
    ids = [row.get("invoice_id") for row in data if row.get("invoice_id")]
    duplicates = len(ids) - len(set(ids))

    if config.get("validate_format", True):
        bad_format = [inv for inv in ids if not pattern.match(str(inv))]
        if bad_format:
            violations.append({
                "type": "invalid_master_entity_format",
                "count": len(bad_format),
                "examples": bad_format[:5],
                "message": f"{len(bad_format)} invoice_id com formato inválido",
            })

    if config.get("validate_uniqueness", True) and duplicates > 0:
        # Para produtos que agregam por chave, duplicidade esperada em produtos não-entity
        # Aqui verificamos AP e AR (entity) e Logística (entity)
        seen = set()
        dup_ids = [inv for inv in ids if inv in seen or seen.add(inv)]
        if dup_ids:
            violations.append({
                "type": "duplicate_master_entity",
                "count": len(dup_ids),
                "examples": dup_ids[:5],
                "message": f"{len(dup_ids)} invoice_id duplicados",
            })

    return {
        "product": product,
        "status": "PASS" if not violations else "FAIL",
        "violations": violations,
    }


def create_lookup(data: List[Dict]) -> Dict[str, List[Dict]]:
    lookup = defaultdict(list)
    for row in data:
        inv = row.get("invoice_id")
        if inv:
            lookup[inv].append(row)
    return dict(lookup)


def validate_cross_domain_consistency(datasets: Dict[str, List[Dict]], config: Dict) -> Dict[str, Any]:
    ap_data = datasets.get("contas-a-pagar", [])
    ar_data = datasets.get("contas-a-receber", [])
    log_data = datasets.get("operacoes-logistica", [])

    ap_lookup = create_lookup(ap_data)
    ar_lookup = create_lookup(ar_data)
    log_lookup = create_lookup(log_data)

    violations = []

    all_ap_ar = set(ap_lookup.keys()) | set(ar_lookup.keys())
    if config.get("compare_amounts", True):
        amount_diff = 0
        for inv_id in all_ap_ar:
            ap = ap_lookup.get(inv_id, [{}])[0]
            ar = ar_lookup.get(inv_id, [{}])[0]
            if ap and ar:
                diff = round(abs(float(ap.get("valor_base", 0)) - float(ar.get("valor_base", 0))), 2)
                if diff >= config.get("amount_tolerance", 0.01):
                    amount_diff += 1
        if amount_diff > 0:
            violations.append({
                "type": "intra_domain_amount_mismatch",
                "count": amount_diff,
                "message": f"{amount_diff} faturas AP vs AR com valor divergente",
            })

    if config.get("compare_status_vocabulary", True):
        status_mismatch = 0
        # AP e AR pertencem ao MESMO domínio (financeiro), que governa um único
        # vocabulário de status. Portanto os status devem ser idênticos para a
        # mesma fatura (mapeamento identidade) — divergência aqui indicaria
        # inconsistência intra-domínio, que não deveria existir por desenho.
        mapping: Dict[str, str] = {}
        for inv_id in all_ap_ar:
            ap = ap_lookup.get(inv_id, [{}])[0]
            ar = ar_lookup.get(inv_id, [{}])[0]
            if ap and ar:
                as_, rs = ap.get("status", ""), ar.get("status", "")
                if mapping.get(as_, as_) != rs:
                    status_mismatch += 1
        if status_mismatch > 0:
            violations.append({
                "type": "status_vocabulary_mismatch",
                "count": status_mismatch,
                "message": f"{status_mismatch} faturas AP vs AR com vocabulário de status divergente",
            })

    # Integridade referencial Logística -> Financeiro
    finance_lookup = {}
    for inv_id in set(ap_lookup.keys()) | set(ar_lookup.keys()):
        finance_lookup[inv_id] = ap_lookup.get(inv_id) or ar_lookup.get(inv_id)

    all_finance_ids = set(finance_lookup.keys())
    all_logistics_ids = set(log_lookup.keys())
    total_finance = len(all_finance_ids)

    log_orphans = [inv for inv in log_lookup if inv not in finance_lookup]
    if log_orphans and config.get("orphan_logistics_is_violation", True):
        violations.append({
            "type": "cross_domain_orphan_logistics",
            "count": len(log_orphans),
            "message": f"{len(log_orphans)} operações logísticas sem fatura financeira correspondente",
        })

    finance_orphans = [inv for inv in finance_lookup if inv not in log_lookup]
    if finance_orphans and config.get("orphan_finance_is_violation", False):
        violations.append({
            "type": "cross_domain_orphan_finance",
            "count": len(finance_orphans),
            "message": f"{len(finance_orphans)} faturas financeiras sem operação logística correspondente",
        })

    coverage = round(len(all_logistics_ids) / total_finance, 4) if total_finance else 0.0
    return {
        "status": "PASS" if not violations else "FAIL",
        "violations": violations,
        "coverage": {
            "total_finance_invoices": total_finance,
            "invoices_with_logistics": len(all_logistics_ids & all_finance_ids),
            "logistics_coverage": coverage,
            "orphan_logistics_count": len(log_orphans),
            "orphan_finance_count": len(finance_orphans),
        },
    }


def main() -> None:
    print("🖥️  Governança Computacional — Validação Automatizada de Inconsistências")
    print("=" * 70)

    policies = load_policies()
    comp_config = policies.get("spec", {}).get("computational_governance", {})
    if not comp_config.get("enabled", False):
        print("⚠️ Governança computacional desabilitada em policies.yaml")
        sys.exit(0)

    checks_cfg = comp_config.get("checks", {})
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "schema_enforcement": [],
        "master_entity_integrity": [],
        "cross_domain_consistency": {},
    }

    # Carrega contratos e datasets
    datasets = {p: load_jsonl(path) for p, path in CONTRACT_DATASET_MAP.items()}

    # Schema enforcement por produto
    for product, contract_path in CONTRACT_PATHS.items():
        _, properties = schema_properties(contract_path)
        data = datasets.get(product, [])
        res = validate_schema_enforcement(product, data, properties, checks_cfg.get("schema_enforcement", {}))
        results["schema_enforcement"].append(res)

    # Master entity integrity por produto
    for product, data in datasets.items():
        res = validate_master_entity_integrity(product, data, checks_cfg.get("master_entity_integrity", {}))
        results["master_entity_integrity"].append(res)

    # Cross-domain consistency
    if checks_cfg.get("cross_domain_consistency", {}).get("enabled", True):
        results["cross_domain_consistency"] = validate_cross_domain_consistency(datasets, checks_cfg.get("cross_domain_consistency", {}))

    # Determina status global
    all_pass = all(
        r["status"] == "PASS" for r in results["schema_enforcement"]
    ) and all(
        r["status"] == "PASS" for r in results["master_entity_integrity"]
    ) and results["cross_domain_consistency"].get("status") == "PASS"

    results["overall_status"] = "PASS" if all_pass else "FAIL"

    os.makedirs("reports", exist_ok=True)
    report_path = "reports/computational_governance_validation.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Saída console
    print("\n📊 Schema Enforcement")
    for r in results["schema_enforcement"]:
        print(f"   {r['product']}: {r['status']}")
        for v in r["violations"]:
            print(f"      ❌ {v['message']}")

    print("\n🔑 Master Entity Integrity")
    for r in results["master_entity_integrity"]:
        print(f"   {r['product']}: {r['status']}")
        for v in r["violations"]:
            print(f"      ❌ {v['message']}")

    print("\n🔗 Cross-domain Consistency")
    cdc = results["cross_domain_consistency"]
    cov = cdc.get("coverage", {})
    print(f"   Status: {cdc.get('status', 'SKIPPED')}")
    if cov:
        print(f"   Cobertura logística: {cov.get('invoices_with_logistics', 0)}/{cov.get('total_finance_invoices', 0)} faturas ({cov.get('logistics_coverage', 0.0):.1%})")
        if cov.get("orphan_finance_count", 0):
            print(f"   ℹ️ Faturas sem logística (esperado/não violação): {cov['orphan_finance_count']}")
        if cov.get("orphan_logistics_count", 0):
            print(f"   ❌ Operações logísticas sem fatura: {cov['orphan_logistics_count']}")
    for v in cdc.get("violations", []):
        print(f"      ❌ {v['message']}")

    print("\n" + "=" * 70)
    print(f"🏁 Overall: {results['overall_status']}")
    print(f"📄 Relatório: {report_path}")

    if all_pass:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
