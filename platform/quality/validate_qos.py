import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Any
import yaml

class QoSValidator:
    """Validação avançada de QoS de Dados (Data Mesh - Livro)"""
    
    def __init__(self, contract_path: str):
        self.contract = self.load_contract(contract_path)
        self.product_name = self.contract["metadata"]["name"]
        self.domain = self.contract["metadata"]["domain"]
        
    def load_contract(self, path: str) -> Dict:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    
    def validate_observability(self) -> Dict[str, Any]:
        """Valida configurações de Data Observability"""
        observability = self.contract.get("spec", {}).get("observability", {})
        
        results = {
            "section": "observability",
            "checks": [],
            "overall_status": "PASS",
            "score": 0,
            "max_score": 5
        }
        
        # Check 1: Data Freshness
        if observability.get("data_freshness", {}).get("enabled"):
            freshness = observability["data_freshness"]
            if freshness.get("threshold") and freshness.get("alert_threshold"):
                results["checks"].append({
                    "check": "data_freshness_configured",
                    "status": "PASS",
                    "message": f"Freshness configurado: {freshness['threshold']} / Alerta: {freshness['alert_threshold']}"
                })
                results["score"] += 1
            else:
                results["checks"].append({
                    "check": "data_freshness_configured",
                    "status": "FAIL",
                    "message": "Data freshness não configurado completamente"
                })
        else:
            results["checks"].append({
                "check": "data_freshness_enabled",
                "status": "FAIL",
                "message": "Data freshness não habilitado"
            })
        
        # Check 2: Schema Drift
        if observability.get("schema_drift", {}).get("enabled"):
            results["checks"].append({
                "check": "schema_drift_enabled",
                "status": "PASS",
                "message": "Schema drift detection habilitado"
            })
            results["score"] += 1
        else:
            results["checks"].append({
                "check": "schema_drift_enabled",
                "status": "FAIL",
                "message": "Schema drift não habilitado"
            })
        
        # Check 3: Volume Anomalies
        if observability.get("volume_anomalies", {}).get("enabled"):
            results["checks"].append({
                "check": "volume_anomalies_enabled",
                "status": "PASS",
                "message": "Volume anomalies detection habilitado"
            })
            results["score"] += 1
        else:
            results["checks"].append({
                "check": "volume_anomalies_enabled",
                "status": "FAIL",
                "message": "Volume anomalies não habilitado"
            })
        
        # Check 4: Quality Degradation
        if observability.get("quality_degradation", {}).get("enabled"):
            results["checks"].append({
                "check": "quality_degradation_enabled",
                "status": "PASS",
                "message": "Quality degradation monitoring habilitado"
            })
            results["score"] += 1
        else:
            results["checks"].append({
                "check": "quality_degradation_enabled",
                "status": "FAIL",
                "message": "Quality degradation não habilitado"
            })
        
        # Check 5: Lineage Tracking
        if observability.get("lineage_tracking", {}).get("enabled"):
            results["checks"].append({
                "check": "lineage_tracking_enabled",
                "status": "PASS",
                "message": "Lineage tracking habilitado"
            })
            results["score"] += 1
        else:
            results["checks"].append({
                "check": "lineage_tracking_enabled",
                "status": "FAIL",
                "message": "Lineage tracking não habilitado"
            })
        
        results["overall_status"] = "PASS" if results["score"] == results["max_score"] else "PARTIAL"
        return results
    
    def validate_error_budgets(self) -> Dict[str, Any]:
        """Valida configurações de Error Budgets (SRE)"""
        error_budgets = self.contract.get("spec", {}).get("error_budgets", {})
        
        results = {
            "section": "error_budgets",
            "checks": [],
            "overall_status": "PASS",
            "score": 0,
            "max_score": 4
        }
        
        # Check 1: Monthly Budget
        if error_budgets.get("monthly_budget"):
            budget = error_budgets["monthly_budget"]
            results["checks"].append({
                "check": "monthly_budget_defined",
                "status": "PASS",
                "message": f"Monthly budget: {budget}"
            })
            results["score"] += 1
        else:
            results["checks"].append({
                "check": "monthly_budget_defined",
                "status": "FAIL",
                "message": "Monthly budget não definido"
            })
        
        # Check 2: Burn Rate Alerts
        if error_budgets.get("burn_rate_alerts"):
            alerts = error_budgets["burn_rate_alerts"]
            if alerts.get("warning_threshold") and alerts.get("critical_threshold"):
                results["checks"].append({
                    "check": "burn_rate_alerts_configured",
                    "status": "PASS",
                    "message": f"Burn rate alerts: Warning={alerts['warning_threshold']}, Critical={alerts['critical_threshold']}"
                })
                results["score"] += 1
            else:
                results["checks"].append({
                    "check": "burn_rate_alerts_configured",
                    "status": "FAIL",
                    "message": "Burn rate alerts incompletos"
                })
        else:
            results["checks"].append({
                "check": "burn_rate_alerts_defined",
                "status": "FAIL",
                "message": "Burn rate alerts não definidos"
            })
        
        # Check 3: Outage Classification
        if error_budgets.get("outage_classification"):
            classification = error_budgets["outage_classification"]
            if "critical" in classification and "major" in classification and "minor" in classification:
                results["checks"].append({
                    "check": "outage_classification_complete",
                    "status": "PASS",
                    "message": "Outage classification completa (critical, major, minor)"
                })
                results["score"] += 1
            else:
                results["checks"].append({
                    "check": "outage_classification_complete",
                    "status": "FAIL",
                    "message": "Outage classification incompleta"
                })
        else:
            results["checks"].append({
                "check": "outage_classification_defined",
                "status": "FAIL",
                "message": "Outage classification não definida"
            })
        
        # Check 4: Budget Calculation
        if error_budgets.get("budget_calculation"):
            calc = error_budgets["budget_calculation"]
            if calc.get("measurement_window"):
                results["checks"].append({
                    "check": "budget_calculation_configured",
                    "status": "PASS",
                    "message": f"Budget calculation: Window={calc['measurement_window']}"
                })
                results["score"] += 1
            else:
                results["checks"].append({
                    "check": "budget_calculation_configured",
                    "status": "FAIL",
                    "message": "Budget calculation incompleto"
                })
        else:
            results["checks"].append({
                "check": "budget_calculation_defined",
                "status": "FAIL",
                "message": "Budget calculation não definido"
            })
        
        results["overall_status"] = "PASS" if results["score"] == results["max_score"] else "PARTIAL"
        return results
    
    def validate_reliability(self) -> Dict[str, Any]:
        """Valida configurações de Reliability"""
        reliability = self.contract.get("spec", {}).get("reliability", {})
        
        results = {
            "section": "reliability",
            "checks": [],
            "overall_status": "PASS",
            "score": 0,
            "max_score": 4
        }
        
        # Check 1: MTTR e MTBF
        if reliability.get("mean_time_to_recovery") and reliability.get("mean_time_between_failures"):
            results["checks"].append({
                "check": "recovery_metrics_defined",
                "status": "PASS",
                "message": f"MTTR: {reliability['mean_time_to_recovery']}, MTBF: {reliability['mean_time_between_failures']}"
            })
            results["score"] += 1
        else:
            results["checks"].append({
                "check": "recovery_metrics_defined",
                "status": "FAIL",
                "message": "MTTR/MTBF não definidos"
            })
        
        # Check 2: Data Loss Prevention
        if reliability.get("data_loss_prevention"):
            results["checks"].append({
                "check": "data_loss_prevention_defined",
                "status": "PASS",
                "message": f"Data loss prevention: {reliability['data_loss_prevention']}"
            })
            results["score"] += 1
        else:
            results["checks"].append({
                "check": "data_loss_prevention_defined",
                "status": "FAIL",
                "message": "Data loss prevention não definido"
            })
        
        # Check 3: Recovery Objectives
        if reliability.get("recovery_objectives"):
            objectives = reliability["recovery_objectives"]
            if objectives.get("rto") and objectives.get("rpo"):
                results["checks"].append({
                    "check": "recovery_objectives_defined",
                    "status": "PASS",
                    "message": f"RTO: {objectives['rto']}, RPO: {objectives['rpo']}"
                })
                results["score"] += 1
            else:
                results["checks"].append({
                    "check": "recovery_objectives_defined",
                    "status": "FAIL",
                    "message": "RTO/RPO não definidos"
                })
        else:
            results["checks"].append({
                "check": "recovery_objectives_defined",
                "status": "FAIL",
                "message": "Recovery objectives não definidos"
            })
        
        # Check 4: Backup Strategy
        if reliability.get("backup_strategy"):
            backup = reliability["backup_strategy"]
            if backup.get("frequency") and backup.get("retention"):
                results["checks"].append({
                    "check": "backup_strategy_defined",
                    "status": "PASS",
                    "message": f"Backup: {backup['frequency']}, Retention: {backup['retention']}"
                })
                results["score"] += 1
            else:
                results["checks"].append({
                    "check": "backup_strategy_defined",
                    "status": "FAIL",
                    "message": "Backup strategy incompleta"
                })
        else:
            results["checks"].append({
                "check": "backup_strategy_defined",
                "status": "FAIL",
                "message": "Backup strategy não definida"
            })
        
        results["overall_status"] = "PASS" if results["score"] == results["max_score"] else "PARTIAL"
        return results
    
    def validate_performance(self) -> Dict[str, Any]:
        """Valida configurações de Performance"""
        performance = self.contract.get("spec", {}).get("performance", {})
        
        results = {
            "section": "performance",
            "checks": [],
            "overall_status": "PASS",
            "score": 0,
            "max_score": 4
        }
        
        # Check 1: Query Performance
        if performance.get("query_performance"):
            query = performance["query_performance"]
            if query.get("response_time_p95"):
                results["checks"].append({
                    "check": "query_performance_defined",
                    "status": "PASS",
                    "message": f"Response time P95: {query['response_time_p95']}"
                })
                results["score"] += 1
            else:
                results["checks"].append({
                    "check": "query_performance_defined",
                    "status": "FAIL",
                    "message": "Query performance incompleto"
                })
        else:
            results["checks"].append({
                "check": "query_performance_defined",
                "status": "FAIL",
                "message": "Query performance não definido"
            })
        
        # Check 2: Batch Processing
        if performance.get("batch_processing"):
            batch = performance["batch_processing"]
            if batch.get("max_processing_time"):
                results["checks"].append({
                    "check": "batch_processing_defined",
                    "status": "PASS",
                    "message": f"Max processing time: {batch['max_processing_time']}"
                })
                results["score"] += 1
            else:
                results["checks"].append({
                    "check": "batch_processing_defined",
                    "status": "FAIL",
                    "message": "Batch processing incompleto"
                })
        else:
            results["checks"].append({
                "check": "batch_processing_defined",
                "status": "FAIL",
                "message": "Batch processing não definido"
            })
        
        # Check 3: Streaming
        if performance.get("streaming"):
            streaming = performance["streaming"]
            if streaming.get("throughput_min"):
                results["checks"].append({
                    "check": "streaming_defined",
                    "status": "PASS",
                    "message": f"Min throughput: {streaming['throughput_min']}"
                })
                results["score"] += 1
            else:
                results["checks"].append({
                    "check": "streaming_defined",
                    "status": "FAIL",
                    "message": "Streaming incompleto"
                })
        else:
            results["checks"].append({
                "check": "streaming_defined",
                "status": "FAIL",
                "message": "Streaming não definido"
            })
        
        # Check 4: Scalability
        if performance.get("scalability"):
            scalability = performance["scalability"]
            if scalability.get("max_concurrent_users"):
                results["checks"].append({
                    "check": "scalability_defined",
                    "status": "PASS",
                    "message": f"Max concurrent users: {scalability['max_concurrent_users']}"
                })
                results["score"] += 1
            else:
                results["checks"].append({
                    "check": "scalability_defined",
                    "status": "FAIL",
                    "message": "Scalability incompleto"
                })
        else:
            results["checks"].append({
                "check": "scalability_defined",
                "status": "FAIL",
                "message": "Scalability não definido"
            })
        
        results["overall_status"] = "PASS" if results["score"] == results["max_score"] else "PARTIAL"
        return results
    
    def validate_all_qos(self) -> Dict[str, Any]:
        """Valida todas as seções QoS"""
        
        validation_results = {
            "product": self.product_name,
            "domain": self.domain,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sections": [],
            "summary": {
                "total_sections": 4,
                "passed_sections": 0,
                "partial_sections": 0,
                "failed_sections": 0,
                "overall_score": 0,
                "max_score": 16,
                "compliance_percentage": 0.0
            }
        }
        
        # Validar cada seção
        sections_validators = [
            self.validate_observability,
            self.validate_error_budgets,
            self.validate_reliability,
            self.validate_performance
        ]
        
        for validator in sections_validators:
            section_result = validator()
            validation_results["sections"].append(section_result)
            
            # Atualizar summary
            if section_result["overall_status"] == "PASS":
                validation_results["summary"]["passed_sections"] += 1
            elif section_result["overall_status"] == "PARTIAL":
                validation_results["summary"]["partial_sections"] += 1
            else:
                validation_results["summary"]["failed_sections"] += 1
            
            validation_results["summary"]["overall_score"] += section_result["score"]
        
        # Calcular compliance percentage
        summary = validation_results["summary"]
        if summary["max_score"] > 0:
            summary["compliance_percentage"] = min(100.0, round(
                (summary["overall_score"] / summary["max_score"]) * 100, 1
            ))
        
        return validation_results

def validate_all_products_qos():
    """Valida QoS de todos os produtos de dados"""
    
    contracts = [
        "domains/financeiro/contas-a-pagar/dataproduct.yaml",
        "domains/financeiro/contas-a-receber/dataproduct.yaml",
        "domains/logistica/dataproduct.yaml"
    ]
    
    all_results = []
    
    print("🔍 QoS Advanced Validation Report")
    print("=" * 50)
    
    for contract_path in contracts:
        if os.path.exists(contract_path):
            print(f"Validando QoS: {contract_path}")
            validator = QoSValidator(contract_path)
            results = validator.validate_all_qos()
            all_results.append(results)
            
            # Exibir resumo do produto
            summary = results["summary"]
            status = "✅" if summary["compliance_percentage"] == 100.0 else "⚠️" if summary["compliance_percentage"] >= 75.0 else "❌"
            print(f"{status} {results['product']} - {summary['compliance_percentage']}% QoS Compliance")
            
            # Exibir detalhes das seções
            for section in results["sections"]:
                section_status = "✅" if section["overall_status"] == "PASS" else "⚠️" if section["overall_status"] == "PARTIAL" else "❌"
                print(f"   {section_status} {section['section']}: {section['score']}/{section['max_score']}")
            print()
        else:
            print(f"⚠️ Contrato não encontrado: {contract_path}")
    
    # Salvar relatório completo
    os.makedirs("reports", exist_ok=True)
    report_path = "reports/qos_validation_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "execution_timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_products": len(all_results),
                "average_compliance": round(sum(r["summary"]["compliance_percentage"] for r in all_results) / len(all_results), 1) if all_results else 0.0,
                "fully_compliant_products": len([r for r in all_results if r["summary"]["compliance_percentage"] == 100.0]),
                "partially_compliant_products": len([r for r in all_results if 75.0 <= r["summary"]["compliance_percentage"] < 100.0]),
                "non_compliant_products": len([r for r in all_results if r["summary"]["compliance_percentage"] < 75.0])
            },
            "results": all_results
        }, f, ensure_ascii=False, indent=2)
    
    print(f"📄 Relatório completo em: {report_path}")
    
    # Exibir resumo geral
    if all_results:
        avg_compliance = round(sum(r["summary"]["compliance_percentage"] for r in all_results) / len(all_results), 1)
        fully_compliant = len([r for r in all_results if r["summary"]["compliance_percentage"] == 100.0])
        
        print(f"\n📊 Resumo Geral:")
        print(f"   • Produtos validados: {len(all_results)}")
        print(f"   • Compliance médio: {avg_compliance}%")
        print(f"   • Totalmente compliant: {fully_compliant}/{len(all_results)}")
        print(f"   • Status QoS Data Mesh: {'✅ Excelente' if avg_compliance >= 90 else '⚠️ Bom' if avg_compliance >= 75 else '❌ Precisa melhorar'}")

if __name__ == "__main__":
    validate_all_products_qos()
