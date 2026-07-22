import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Any
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from odcs_adapter import load_and_normalize

class DataQualityValidator:
    """Validação runtime de qualidade de dados (Data Mesh Pattern)"""
    
    def __init__(self, contract_path: str):
        self.contract = self.load_contract(contract_path)
        self.product_name = self.contract["metadata"]["name"]
        self.domain = self.contract["metadata"]["domain"]
        self.quality_rules = self.contract.get("spec", {}).get("quality", {}).get("rules", [])
        
    def load_contract(self, path: str) -> Dict:
        # Contrato no padrão ODCS v3 (Bitol), normalizado para a visão interna.
        return load_and_normalize(path)
    
    def validate_record(self, record: Dict) -> Dict[str, Any]:
        """Valida um único registro contra as regras de qualidade"""
        results = {
            "record_id": record.get("invoice_id", record.get("operation_id", "unknown")),
            "product": self.product_name,
            "domain": self.domain,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "validations": [],
            "overall_status": "PASS",
            "errors": 0,
            "warnings": 0
        }
        
        for rule in self.quality_rules:
            validation_result = self.apply_rule(record, rule)
            results["validations"].append(validation_result)
            
            if validation_result["status"] == "FAIL":
                results["errors"] += 1
                results["overall_status"] = "FAIL"
            elif validation_result["status"] == "WARN":
                results["warnings"] += 1
                if results["overall_status"] == "PASS":
                    results["overall_status"] = "WARN"
        
        return results
    
    def apply_rule(self, record: Dict, rule: Dict) -> Dict[str, Any]:
        """Aplica uma regra de qualidade a um registro"""
        rule_id = rule["id"]
        description = rule["description"]
        expression = rule["expression"]
        applies_to = rule.get("applies_to", [])
        severity = rule["severity"]
        
        result = {
            "rule_id": rule_id,
            "description": description,
            "severity": severity,
            "status": "PASS",
            "message": "Regra satisfeita",
            "field_value": None,
            "expected": expression
        }
        
        try:
            # Implementação simplificada de validação
            if rule_id == "ap-amount-positive" or rule_id == "ar-gross-amount-positive" or rule_id == "log-quantity-positive":
                field_name = "valor_liquido" if "valor_liquido" in record else ("valor_bruto" if "valor_bruto" in record else "quantity")
                if field_name in record:
                    value = float(record[field_name])
                    if value <= 0:
                        result["status"] = "FAIL" if severity == "error" else "WARN"
                        result["message"] = f"{field_name} deve ser positivo, mas é {value}"
                        result["field_value"] = value
            
            elif rule_id == "ap-currency-valid" or rule_id == "ar-currency-valid" or rule_id == "log-currency-valid":
                if "moeda" in record:
                    currency = record["moeda"]
                    if currency != "BRL":
                        result["status"] = "FAIL" if severity == "error" else "WARN"
                        result["message"] = f"Currency deve ser BRL, mas é {currency}"
                        result["field_value"] = currency
            
            elif rule_id == "ap-future-due-date" or rule_id == "ar-future-due-date" or rule_id == "log-future-operation-date":
                if "due_date" in record and "issue_date" in record:
                    due_date = datetime.fromisoformat(record["due_date"].replace("Z", "+00:00"))
                    issue_date = datetime.fromisoformat(record["issue_date"].replace("Z", "+00:00"))
                    if due_date <= issue_date:
                        result["status"] = "WARN"
                        result["message"] = "due_date deve ser futura à issue_date"
                        result["field_value"] = f"due={record['due_date']}, issue={record['issue_date']}"
            
            elif rule_id == "log-consistent-calculation":
                if "quantity" in record and "unit_price" in record and "valor_total" in record:
                    quantity = float(record["quantity"])
                    unit_price = float(record["unit_price"])
                    total_value = float(record["valor_total"])
                    expected = quantity * unit_price
                    if abs(total_value - expected) > 0.01:  # Tolerância de 1 centavo
                        result["status"] = "FAIL" if severity == "error" else "WARN"
                        result["message"] = f"valor_total ({total_value}) != quantity ({quantity}) * unit_price ({unit_price}) = {expected}"
                        result["field_value"] = total_value
            
            elif rule_id == "log-positive-values":
                if "unit_price" in record and "valor_total" in record:
                    unit_price = float(record["unit_price"])
                    total_value = float(record["valor_total"])
                    if unit_price <= 0 or total_value <= 0:
                        result["status"] = "FAIL" if severity == "error" else "WARN"
                        result["message"] = f"Valores devem ser positivos: unit_price={unit_price}, valor_total={total_value}"
                        result["field_value"] = f"unit_price={unit_price}, valor_total={total_value}"
            
            elif rule_id == "non_null_ids":
                id_fields = ["invoice_id", "operation_id", "id_cliente", "id_fornecedor", "party_id"]
                for field in id_fields:
                    if field in record:
                        value = record[field]
                        if not value or value == "":
                            result["status"] = "FAIL" if severity == "error" else "WARN"
                            result["message"] = f"{field} não pode ser nulo ou vazio"
                            result["field_value"] = value
                            break
            
            elif rule_id == "valid_status":
                if "status" in record:
                    status = record["status"]
                    # Para logística, status é um array
                    if isinstance(status, list):
                        # Valida cada status no array
                        for s in status:
                            if s not in ["ABERTO", "PAGO", "LIQUIDADO", "CANCELADO", "PENDENTE", "EM_PROCESSAMENTO", "CONCLUIDO"]:
                                result["status"] = "FAIL" if severity == "error" else "WARN"
                                result["message"] = f"Status inválido: {s}"
                                result["field_value"] = s
                                break
                    else:
                        # Para AP/AR, status é string
                        valid_statuses = ["ABERTO", "PAGO", "LIQUIDADO", "CANCELADO", "PENDENTE", "EM_PROCESSAMENTO", "CONCLUIDO"]
                        if status not in valid_statuses:
                            result["status"] = "FAIL" if severity == "error" else "WARN"
                            result["message"] = f"Status inválido: {status}"
                            result["field_value"] = status
            
        except Exception as e:
            result["status"] = "ERROR"
            result["message"] = f"Erro na validação: {str(e)}"
        
        return result
    
    def validate_dataset(self, data_path: str) -> Dict[str, Any]:
        """Valida um dataset completo e gera métricas de qualidade"""
        
        records = []
        with open(data_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        
        validation_results = []
        total_records = len(records)
        total_errors = 0
        total_warnings = 0
        
        for record in records:
            result = self.validate_record(record)
            validation_results.append(result)
            total_errors += result["errors"]
            total_warnings += result["warnings"]
        
        # Métricas agregadas
        quality_metrics = {
            "product": self.product_name,
            "domain": self.domain,
            "dataset_path": data_path,
            "validation_timestamp": datetime.now(timezone.utc).isoformat(),
            "total_records": total_records,
            "records_with_errors": sum(1 for r in validation_results if r["overall_status"] == "FAIL"),
            "records_with_warnings": sum(1 for r in validation_results if r["overall_status"] == "WARN"),
            "records_valid": sum(1 for r in validation_results if r["overall_status"] == "PASS"),
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "error_rate": (total_errors / total_records) * 100 if total_records > 0 else 0,
            "warning_rate": (total_warnings / total_records) * 100 if total_records > 0 else 0,
            "quality_score": ((total_records - total_errors) / total_records) * 100 if total_records > 0 else 0,
            "rule_performance": self.analyze_rule_performance(validation_results),
            "sample_errors": [r for r in validation_results if r["overall_status"] == "FAIL"][:5],
            "sample_warnings": [r for r in validation_results if r["overall_status"] == "WARN"][:3]
        }
        
        return quality_metrics
    
    def analyze_rule_performance(self, validation_results: List[Dict]) -> Dict[str, Dict]:
        """Analisa performance de cada regra de qualidade"""
        rule_stats = {}
        
        for result in validation_results:
            for validation in result["validations"]:
                rule_id = validation["rule_id"]
                if rule_id not in rule_stats:
                    rule_stats[rule_id] = {
                        "description": validation["description"],
                        "total_executions": 0,
                        "passes": 0,
                        "failures": 0,
                        "warnings": 0,
                        "errors": 0
                    }
                
                rule_stats[rule_id]["total_executions"] += 1
                status = validation["status"]
                if status == "PASS":
                    rule_stats[rule_id]["passes"] += 1
                elif status == "FAIL":
                    rule_stats[rule_id]["failures"] += 1
                elif status == "WARN":
                    rule_stats[rule_id]["warnings"] += 1
                elif status == "ERROR":
                    rule_stats[rule_id]["errors"] += 1
        
        # Calcular taxas
        for rule_id, stats in rule_stats.items():
            total = stats["total_executions"]
            if total > 0:
                stats["pass_rate"] = (stats["passes"] / total) * 100
                stats["failure_rate"] = (stats["failures"] / total) * 100
                stats["warning_rate"] = (stats["warnings"] / total) * 100
                stats["error_rate"] = (stats["errors"] / total) * 100
            else:
                stats["pass_rate"] = 0
                stats["failure_rate"] = 0
                stats["warning_rate"] = 0
                stats["error_rate"] = 0
        
        return rule_stats

def validate_all_products():
    """Valida qualidade de todos os produtos de dados"""
    
    # Mapeamento de contratos para datasets
    contract_data_mapping = [
        ("domains/financeiro/contas-a-pagar/data_contract.yaml", "domains/financeiro/contas-a-pagar/data/contas_a_pagar.jsonl"),
        ("domains/financeiro/contas-a-receber/data_contract.yaml", "domains/financeiro/contas-a-receber/data/contas_a_receber.jsonl"),
        ("domains/logistica/data_contract.yaml", "domains/logistica/data/logistics.jsonl"),
    ]
    
    all_results = []
    
    for contract_path, data_path in contract_data_mapping:
        if os.path.exists(contract_path) and os.path.exists(data_path):
            print(f"Validando qualidade do dataset: {data_path}")
            validator = DataQualityValidator(contract_path)
            metrics = validator.validate_dataset(data_path)
            all_results.append(metrics)
        else:
            print(f"⚠️ Arquivos não encontrados: {data_path} ou {contract_path}")
    
    # Salva relatório completo
    os.makedirs("reports", exist_ok=True)
    report_path = "reports/data_quality_validation.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    
    # Resumo no console
    print("\n🔍 Data Quality Validation Report")
    print("=" * 50)
    
    for metrics in all_results:
        print(f"\n📦 Produto: {metrics['product']} (Domain: {metrics['domain']})")
        print(f"   📊 Total registros: {metrics['total_records']}")
        print(f"   ✅ Válidos: {metrics['records_valid']} ({metrics['quality_score']:.1f}%)")
        print(f"   ❌ Com erros: {metrics['records_with_errors']} ({metrics['error_rate']:.1f}%)")
        print(f"   ⚠️ Com avisos: {metrics['records_with_warnings']} ({metrics['warning_rate']:.1f}%)")
        
        if metrics['sample_errors']:
            print(f"   🚨 Amostra de erros:")
            for error in metrics['sample_errors'][:2]:
                for validation in error['validations']:
                    if validation['status'] in ['FAIL', 'ERROR']:
                        print(f"      • {validation['rule_id']}: {validation['message']}")
    
    print(f"\n📄 Relatório completo em: {report_path}")
    return all_results

if __name__ == "__main__":
    validate_all_products()
