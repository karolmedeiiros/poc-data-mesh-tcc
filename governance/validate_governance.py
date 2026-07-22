import yaml
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Dict, List, Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from odcs_adapter import load_and_normalize

def load_yaml(file_path: str) -> Dict[str, Any]:
    """Carrega arquivo YAML"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def get_nested(d: Dict[str, Any], keys: list[str], default: Any = None) -> Any:
    """Lê caminhos aninhados com fallback seguro."""
    current = d
    for k in keys:
        if not isinstance(current, dict) or k not in current:
            return default
        current = current[k]
    return current

def parse_iso_duration_to_minutes(value: str) -> float:
    """Converte duração ISO-8601 simples (P/ PT) para minutos."""
    if not isinstance(value, str):
        raise ValueError("duration must be string")

    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value)
    if not match:
        raise ValueError(f"invalid ISO duration: {value}")

    days = int(match.group(1) or 0)
    hours = int(match.group(2) or 0)
    minutes = int(match.group(3) or 0)
    seconds = int(match.group(4) or 0)

    return (days * 24 * 60) + (hours * 60) + minutes + (seconds / 60)

def parse_percent(value: str) -> float:
    """Converte string percentual (ex: '99.0%') para float."""
    if not isinstance(value, str) or not value.endswith("%"):
        raise ValueError(f"invalid percent format: {value}")
    return float(value.replace("%", ""))

def check_required_sections(contract: Dict, policies: Dict) -> Dict[str, str]:
    """Verifica seções obrigatórias do contrato"""
    required = policies["spec"]["required_contract_sections"]
    results = {}
    
    for section in required:
        # Verifica se a seção existe no contrato
        if section == "metadata":
            results[section] = "PASS" if "metadata" in contract else "FAIL"
        elif section.startswith("spec."):
            spec_section = section.replace("spec.", "")
            spec_content = contract.get("spec", {})
            results[section] = "PASS" if spec_section in spec_content else "FAIL"
        else:
            results[section] = "FAIL"
    
    return results

def check_slas(contract: Dict, policies: Dict) -> Dict[str, str]:
    """Verifica compliance com SLAs globais"""
    results = {}
    required_freshness = get_nested(policies, ["spec", "standards", "quality", "min_freshness"])
    required_availability = get_nested(policies, ["spec", "standards", "quality", "min_availability"])

    # fallback para global_slas.default se necessário
    if required_freshness is None:
        required_freshness = get_nested(policies, ["spec", "global_slas", "freshness", "default"])
    if required_availability is None:
        required_availability = get_nested(policies, ["spec", "global_slas", "availability", "default"])

    if required_freshness is None or required_availability is None:
        results["sla_policy_config"] = "FAIL"
        results["sla_defined"] = "FAIL"
        return results
    
    if "spec" not in contract or "product" not in contract["spec"] or "sla" not in contract["spec"]["product"]:
        results["sla_defined"] = "FAIL"
        return results
    
    contract_sla = contract["spec"]["product"]["sla"]
    results["sla_policy_config"] = "PASS"
    results["sla_defined"] = "PASS"
    
    # Verifica freshness
    if "freshness" in contract_sla:
        try:
            contract_freshness_min = parse_iso_duration_to_minutes(contract_sla["freshness"])
            required_freshness_min = parse_iso_duration_to_minutes(required_freshness)
            # Menor duração = mais restritivo (melhor)
            results["freshness_compliance"] = "PASS" if contract_freshness_min <= required_freshness_min else "FAIL"
        except ValueError:
            results["freshness_compliance"] = "FAIL"
    else:
        results["freshness_compliance"] = "FAIL"
    
    # Verifica availability
    if "availability" in contract_sla:
        try:
            contract_avail_num = parse_percent(contract_sla["availability"])
            required_avail_num = parse_percent(required_availability)
            results["availability_compliance"] = "PASS" if contract_avail_num >= required_avail_num else "FAIL"
        except ValueError:
            results["availability_compliance"] = "FAIL"
    else:
        results["availability_compliance"] = "FAIL"
    
    return results

def check_quality_rules(contract: Dict, policies: Dict) -> Dict[str, str]:
    """Verifica se regras de qualidade globais estão presentes"""
    results = {}
    global_rules = policies["spec"]["global_quality_rules"]
    
    if "spec" not in contract or "quality" not in contract["spec"] or "rules" not in contract["spec"]["quality"]:
        results["quality_rules_defined"] = "FAIL"
        return results
    
    contract_rules = contract["spec"]["quality"]["rules"]
    results["quality_rules_defined"] = "PASS"
    
    dataset_fields = {f.get("name") for f in contract.get("spec", {}).get("dataset", {}).get("fields", [])}

    # Verifica cobertura de cada regra global por campo relevante
    for rule in global_rules:
        rule_id = rule["id"]
        applies_to = set(rule.get("applies_to", []))

        # Só exige regra quando o contrato contém os campos alvo
        if applies_to and not (dataset_fields & applies_to):
            results[f"quality_rule_{rule_id}"] = "PASS"
            continue

        rule_found = False
        for contract_rule in contract_rules:
            text = " ".join([
                str(contract_rule.get("id", "")),
                str(contract_rule.get("description", "")),
                str(contract_rule.get("expression", "")),
            ]).lower()
            if any(field.lower() in text for field in applies_to):
                rule_found = True
                break

        results[f"quality_rule_{rule_id}"] = "PASS" if rule_found else "FAIL"
    
    return results

def check_required_fields(contract: Dict, policies: Dict) -> Dict[str, str]:
    """Verifica campos obrigatórios conforme `output_port_kind`.

    - aggregate (default)         : exige `aggregate` + `measures` (count, total)
    - entity / entity_keyed       : exige `aggregate` + campo de master_entity declarada
    """
    results: Dict[str, str] = {}
    required_fields = policies["spec"]["required_fields"]
    metadata = contract.get("metadata", {}) or {}
    kind = metadata.get("output_port_kind", "aggregate")

    if "spec" not in contract or "dataset" not in contract["spec"] or "fields" not in contract["spec"]["dataset"]:
        results["dataset_fields_defined"] = "FAIL"
        return results

    contract_fields = contract["spec"]["dataset"]["fields"]
    field_set = {f["name"] for f in contract_fields if isinstance(f, dict)}
    results["dataset_fields_defined"] = "PASS"

    # Campos obrigatórios comuns aos produtos analíticos
    for field in required_fields.get("aggregate", []):
        results[f"required_field_{field}"] = "PASS" if field in field_set else "FAIL"

    if kind in ("entity", "entity_keyed"):
        # Para output ports keyed por master entity, validar que o campo da
        # entidade-mestre declarada está presente.
        master_entity_id = metadata.get("master_entity")
        master_entities = policies.get("spec", {}).get("interoperability", {}).get("master_entities", [])
        canonical_field = None
        for me in master_entities:
            if me.get("id") == master_entity_id:
                canonical_field = me.get("canonical_field")
                break
        if canonical_field is None:
            results["master_entity_declared"] = "FAIL"
        else:
            results["master_entity_declared"] = "PASS"
            results[f"master_entity_field_{canonical_field}"] = (
                "PASS" if canonical_field in field_set else "FAIL"
            )
    else:
        # Aggregate: medidas (count, total) presentes
        for token in required_fields.get("measures", []):
            match = any(token in name for name in field_set)
            results[f"required_measure_{token}"] = "PASS" if match else "FAIL"

    return results

def check_monitoring(contract: Dict, policies: Dict) -> Dict[str, str]:
    """Verifica se monitoring está configurado"""
    results = {}
    
    if "spec" not in contract or "monitoring" not in contract["spec"]:
        results["monitoring_defined"] = "FAIL"
        return results
    
    monitoring = contract["spec"]["monitoring"]
    results["monitoring_defined"] = "PASS"
    
    # Verifica métricas obrigatórias
    required_metrics = policies["spec"]["required_monitoring"]["metrics"]
    contract_metrics = monitoring.get("metrics", [])
    
    for metric in required_metrics:
        metric_name = metric["name"]
        metric_found = any(m.get("name") == metric_name for m in contract_metrics)
        results[f"monitoring_metric_{metric_name}"] = "PASS" if metric_found else "FAIL"
    
    # Verifica alerts obrigatórios
    required_alerts = policies["spec"]["required_monitoring"]["alerts"]
    contract_alerts = monitoring.get("alerts", [])
    
    for alert in required_alerts:
        alert_name = alert["name"]
        alert_found = any(a.get("name") == alert_name for a in contract_alerts)
        results[f"monitoring_alert_{alert_name}"] = "PASS" if alert_found else "FAIL"
    
    return results

def check_interoperability(contract: Dict, policies: Dict) -> Dict[str, str]:
    """Verifica compliance com a política de interoperabilidade da governança federativa.

    Cobre: formatos abertos, schema registry, identificadores compartilhados entre
    domínios, padrões semânticos (moeda/datetime), convenções de nomenclatura,
    metadados de catálogo, linhagem federada e versionamento semântico.
    """
    results: Dict[str, str] = {}
    interop = get_nested(policies, ["spec", "interoperability"])
    if not interop:
        results["interoperability_policy_defined"] = "FAIL"
        return results
    results["interoperability_policy_defined"] = "PASS"

    spec = contract.get("spec", {})
    schema = spec.get("schema", {})
    dataset = spec.get("dataset", {})
    fields = dataset.get("fields", [])
    field_names = {f.get("name") for f in fields if isinstance(f, dict)}
    field_by_name = {f.get("name"): f for f in fields if isinstance(f, dict)}
    metadata = contract.get("metadata", {})

    # 1) Formato de dados aberto
    allowed_formats = set(get_nested(interop, ["data_formats", "allowed"], []) or [])
    fmt = schema.get("format")
    results["interop_data_format_open"] = "PASS" if fmt and fmt in allowed_formats else "FAIL"

    # 2) Schema Registry obrigatório
    registry_required = bool(get_nested(interop, ["schema_registry", "required"], False))
    registry_pattern = get_nested(interop, ["schema_registry", "endpoint_pattern"])
    registry = schema.get("registry")
    if registry_required:
        if registry and (not registry_pattern or re.match(registry_pattern, str(registry))):
            results["interop_schema_registry"] = "PASS"
        else:
            results["interop_schema_registry"] = "FAIL"
    else:
        results["interop_schema_registry"] = "PASS"

    # 3) Modo de compatibilidade do schema (backward) alinhado com a política federada
    expected_compat = get_nested(interop, ["schema_registry", "compatibility_mode"])
    contract_compat = get_nested(schema, ["evolution", "policy"], "")
    if expected_compat:
        results["interop_schema_compatibility"] = (
            "PASS" if expected_compat in str(contract_compat).lower() else "FAIL"
        )

    # 4) Identificadores compartilhados (rastreabilidade entre domínios)
    shared_required = get_nested(interop, ["shared_identifiers", "required_fields"], []) or []
    for fname in shared_required:
        results[f"interop_shared_id_{fname}"] = "PASS" if fname in field_names else "FAIL"

    # 5) Pelo menos uma chave de junção entre domínios deve existir
    cross_keys = set(get_nested(interop, ["shared_identifiers", "cross_domain_keys"], []) or [])
    results["interop_cross_domain_key_present"] = (
        "PASS" if cross_keys & field_names else "FAIL"
    )

    # 6) Moeda alinhada ao padrão semântico (ISO-4217, lista permitida)
    allowed_currencies = set(get_nested(interop, ["semantic_standards", "currency", "allowed"], []) or [])
    currency_field_name = get_nested(interop, ["semantic_standards", "currency", "field_name"], "currency")
    if currency_field_name in field_by_name:
        enum_vals = set(field_by_name[currency_field_name].get("enum", []) or [])
        results["interop_currency_standard"] = (
            "PASS" if enum_vals and enum_vals.issubset(allowed_currencies) else "FAIL"
        )
    else:
        # Se não há campo de moeda, regra não se aplica
        results["interop_currency_standard"] = "PASS"

    # 7) Tipo datetime conforme padrão semântico (campo de timestamp de materialização).
    # A malha usa dt_versao (ISO-8601 armazenado como string) como campo canônico;
    # aceita também generated_at/updated_at para compatibilidade.
    expected_dt_type = get_nested(interop, ["semantic_standards", "datetime", "field_type"], "string")
    dt_field_name = get_nested(interop, ["semantic_standards", "datetime", "field_name"], "dt_versao")
    dt_candidates = [name for name in (dt_field_name, "generated_at", "updated_at") if name in field_by_name]
    if dt_candidates:
        results["interop_datetime_type"] = (
            "PASS" if any(field_by_name[name].get("type") == expected_dt_type for name in dt_candidates) else "FAIL"
        )
    else:
        results["interop_datetime_type"] = "FAIL"

    # 8) Convenção de nomenclatura snake_case para campos
    naming = get_nested(interop, ["naming_conventions", "fields"], "snake_case")
    max_len = int(get_nested(interop, ["naming_conventions", "max_identifier_length"], 50))
    snake_re = re.compile(r"^[a-z][a-z0-9_]*$")
    if naming == "snake_case":
        invalid = [n for n in field_names if not n or not snake_re.match(n) or len(n) > max_len]
        results["interop_naming_convention"] = "PASS" if not invalid else "FAIL"
    else:
        results["interop_naming_convention"] = "PASS"

    # 9) Metadados de catálogo obrigatórios (DCAT-like)
    required_meta = get_nested(interop, ["catalog", "required_metadata"], []) or []
    missing_meta = [k for k in required_meta if not metadata.get(k) and not (k == "description" and spec.get("product", {}).get("description"))]
    results["interop_catalog_metadata"] = "PASS" if not missing_meta else "FAIL"

    # 10) Linhagem federada: campos de rastreio devem existir
    trace_fields = get_nested(interop, ["federated_lineage", "trace_fields"], []) or []
    missing_trace = [f for f in trace_fields if f not in field_names]
    results["interop_federated_lineage"] = "PASS" if not missing_trace else "FAIL"

    # 11) Versionamento semântico (SemVer) no metadata.version
    version = str(metadata.get("version", ""))
    semver_re = re.compile(r"^\d+\.\d+\.\d+(?:[-+].+)?$")
    results["interop_semver"] = "PASS" if semver_re.match(version) else "FAIL"

    # 12) Consumer contracts declarados quando exigidos pela política
    consumer_required = bool(get_nested(interop, ["consumer_contracts", "required"], False))
    if consumer_required:
        results["interop_consumer_contracts"] = (
            "PASS" if spec.get("consumers") else "FAIL"
        )
    else:
        results["interop_consumer_contracts"] = "PASS"

    return results


def validate_contract_governance(contract_path: str, policies_path: str) -> Dict[str, Any]:
    """Valida compliance de um contrato com as políticas de governança"""
    
    try:
        contract = load_and_normalize(contract_path)
        policies = load_yaml(policies_path)
    except Exception as e:
        return {
            "contract": os.path.basename(contract_path),
            "error": f"Failed to load files: {str(e)}",
            "compliant": False,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    validation_result = {
        "contract": contract["metadata"]["name"],
        "version": contract["metadata"]["version"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "compliance": {},
        "compliant": True,
        "summary": {
            "total_checks": 0,
            "passed_checks": 0,
            "failed_checks": 0
        }
    }
    
    # Executa todas as validações
    checks = [
        ("required_sections", check_required_sections),
        ("slas", check_slas),
        ("quality_rules", check_quality_rules),
        ("required_fields", check_required_fields),
        ("monitoring", check_monitoring),
        ("interoperability", check_interoperability)
    ]
    
    for check_name, check_func in checks:
        try:
            check_results = check_func(contract, policies)
            validation_result["compliance"][check_name] = check_results
            
            # Atualiza contadores
            for result in check_results.values():
                validation_result["summary"]["total_checks"] += 1
                if result == "PASS":
                    validation_result["summary"]["passed_checks"] += 1
                else:
                    validation_result["summary"]["failed_checks"] += 1
                    validation_result["compliant"] = False
                    
        except Exception as e:
            validation_result["compliance"][check_name] = {"error": str(e)}
            validation_result["summary"]["total_checks"] += 1
            validation_result["summary"]["failed_checks"] += 1
            validation_result["compliant"] = False
    
    # Calcula percentual de compliance
    total = validation_result["summary"]["total_checks"]
    passed = validation_result["summary"]["passed_checks"]
    if total > 0:
        validation_result["summary"]["compliance_percentage"] = round((passed / total) * 100, 2)
    else:
        validation_result["summary"]["compliance_percentage"] = 0.0
    
    return validation_result

def main():
    """Função principal de validação"""
    
    # Lista de contratos para validar
    contracts = [
        "domains/financeiro/contas-a-pagar/data_contract.yaml",
        "domains/financeiro/contas-a-receber/data_contract.yaml",
        "domains/logistica/data_contract.yaml",
    ]
    
    policies_path = "governance/policies.yaml"
    
    # Verifica se o arquivo de políticas existe
    if not os.path.exists(policies_path):
        print(f"❌ Arquivo de políticas não encontrado: {policies_path}")
        return
    
    # Valida cada contrato
    results = []
    for contract_path in contracts:
        if os.path.exists(contract_path):
            print(f"🔍 Validando: {contract_path}")
            result = validate_contract_governance(contract_path, policies_path)
            results.append(result)
            
            # Mostra resultado resumido
            status = "✅" if result["compliant"] else "❌"
            compliance_pct = result["summary"]["compliance_percentage"]
            print(f"{status} {result['contract']} - {compliance_pct}% compliant")
        else:
            print(f"❌ Contrato não encontrado: {contract_path}")
            results.append({
                "contract": os.path.basename(contract_path),
                "error": "File not found",
                "compliant": False,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
    
    # Gera relatório consolidado
    report = {
        "validation_summary": {
            "total_contracts": len(results),
            "compliant_contracts": sum(1 for r in results if r.get("compliant", False)),
            "validation_timestamp": datetime.now(timezone.utc).isoformat(),
            "policies_version": load_yaml(policies_path)["metadata"]["version"]
        },
        "contracts": results
    }
    
    # Salva relatório
    os.makedirs("reports", exist_ok=True)
    report_path = "reports/governance_compliance.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    # Mostra resumo final
    compliant = report["validation_summary"]["compliant_contracts"]
    total = report["validation_summary"]["total_contracts"]
    
    print(f"\n📊 Resumo da Validação:")
    print(f"   Total de contratos: {total}")
    print(f"   Contratos compliant: {compliant}")
    print(f"   Taxa de compliance: {round((compliant/total)*100, 1)}%")
    print(f"   📄 Relatório salvo em: {report_path}")

if __name__ == "__main__":
    main()