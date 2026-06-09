import yaml
import json
from datetime import datetime

def validate_contract(contract_path: str) -> dict:
    """Valida se o contrato segue os padrões do livro"""
    with open(contract_path, 'r') as f:
        contract = yaml.safe_load(f)
    
    validation_result = {
        "contract": contract["metadata"]["name"],
        "version": contract["metadata"]["version"],
        "timestamp": datetime.now().isoformat(),
        "checks": [],
        "valid": True
    }
    
    # Check 1: Metadados obrigatórios
    required_metadata = ["name", "domain", "owner", "version"]
    for field in required_metadata:
        if field in contract["metadata"]:
            validation_result["checks"].append({
                "check": f"metadata.{field}",
                "status": "PASS",
                "message": f"{field} presente"
            })
        else:
            validation_result["checks"].append({
                "check": f"metadata.{field}",
                "status": "FAIL", 
                "message": f"{field} ausente"
            })
            validation_result["valid"] = False
    
    # Check 2: Schema Registry definido
    if "schema" in contract["spec"]:
        validation_result["checks"].append({
            "check": "schema.defined",
            "status": "PASS",
            "message": "Schema registry configurado"
        })
    else:
        validation_result["checks"].append({
            "check": "schema.defined",
            "status": "FAIL",
            "message": "Schema registry não configurado"
        })
        validation_result["valid"] = False
    
    # Check 3: Test suite definido
    if "tests" in contract["spec"]:
        validation_result["checks"].append({
            "check": "tests.defined",
            "status": "PASS",
            "message": "Test suite configurado"
        })
    else:
        validation_result["checks"].append({
            "check": "tests.defined",
            "status": "FAIL",
            "message": "Test suite não configurado"
        })
        validation_result["valid"] = False
    
    # Check 4: Consumer contracts definido
    if "consumers" in contract["spec"]:
        validation_result["checks"].append({
            "check": "consumers.defined",
            "status": "PASS",
            "message": "Consumer contracts configurados"
        })
    else:
        validation_result["checks"].append({
            "check": "consumers.defined",
            "status": "FAIL",
            "message": "Consumer contracts não configurados"
        })
        validation_result["valid"] = False
    
    # Check 5: Monitoring definido
    if "monitoring" in contract["spec"]:
        validation_result["checks"].append({
            "check": "monitoring.defined",
            "status": "PASS",
            "message": "Monitoring configurado"
        })
    else:
        validation_result["checks"].append({
            "check": "monitoring.defined",
            "status": "FAIL",
            "message": "Monitoring não configurado"
        })
        validation_result["valid"] = False
    
    return validation_result

def main():
    contracts = [
        "domains/financeiro/contas-a-pagar/dataproduct.yaml",
        "domains/financeiro/contas-a-receber/dataproduct.yaml",
        "domains/logistica/dataproduct.yaml"
    ]
    
    results = []
    for contract_path in contracts:
        result = validate_contract(contract_path)
        results.append(result)
    
    # Salvar relatório
    with open("reports/contract_validation.json", "w") as f:
        json.dump({
            "summary": {
                "total_contracts": len(results),
                "valid_contracts": sum(1 for r in results if r["valid"]),
                "validation_timestamp": datetime.now().isoformat()
            },
            "results": results
        }, f, indent=2)
    
    print("✅ Validação de contratos concluída")
    print(f"📊 Relatório salvo em: reports/contract_validation.json")
    
    for result in results:
        status = "✅" if result["valid"] else "❌"
        print(f"{status} {result['contract']} v{result['version']}")

if __name__ == "__main__":
    main()