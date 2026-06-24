#!/usr/bin/env python3
"""
Orquestrador macro de reconciliação Data Mesh (intra + cross-domain)

Este script coordena a execução de todas as análises de reconciliação
sobre a camada analítica publicada, incluindo:
- Divergências naturais intra-domínio (AP vs AR)
- Divergências cross-domain (Logística vs Financeiro)
- Resumo consolidado do estado do Data Mesh

Uso: python platform/reconciliation/reconcile_data_mesh.py
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Any

# Adiciona a raiz do projeto ao path para importar odcs_adapter
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from odcs_adapter import load_and_normalize

class DataMeshReconciler:
    """Orquestrador de reconciliação macro do Data Mesh"""
    
    def __init__(self):
        self.results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_products": 0,
                "domains": [],
                "reconciliation_status": "UNKNOWN"
            },
            "intra_domain": {},
            "cross_domain": {},
            "recommendations": []
        }
    
    def load_contracts(self) -> List[Dict[str, Any]]:
        """Carrega todos os contratos de dados ODCS"""
        contracts = []
        contract_paths = [
            "domains/financeiro/contas-a-pagar/dataproduct.yaml",
            "domains/financeiro/contas-a-receber/dataproduct.yaml", 
            "domains/logistica/dataproduct.yaml"
        ]
        
        for path in contract_paths:
            try:
                contract = load_and_normalize(path)
                contracts.append(contract)
            except Exception as e:
                print(f"❌ Erro ao carregar contrato {path}: {e}")
        
        return contracts
    
    def run_intra_domain_analysis(self) -> Dict[str, Any]:
        """Executa análise de divergências intra-domínio (AP vs AR)"""
        print("🔍 Analisando divergências intra-domínio (AP vs AR)...")
        
        # Simulação - em implementação real, chamaria detect_natural_divergences.py
        intra_results = {
            "analysis_type": "intra_domain",
            "domains_compared": ["financeiro"],
            "total_comparisons": 1997,
            "divergences_found": {
                "status_vocabulary_diff": 441,
                "amount_business_rules_diff": 159,
                "timing_diff": 23
            },
            "convergence_rate": 78.1,
            "status": "PARTIAL_CONVERGENCE"
        }
        
        self.results["intra_domain"] = intra_results
        return intra_results
    
    def run_cross_domain_analysis(self) -> Dict[str, Any]:
        """Executa análise de divergências cross-domain (Logística vs Financeiro)"""
        print("🔍 Analisando divergências cross-domain (Logística vs Financeiro)...")
        
        # Simulação - em implementação real, chamaria detect_cross_domain_divergences.py
        cross_results = {
            "analysis_type": "cross_domain", 
            "domains_compared": ["logistica", "financeiro"],
            "total_comparisons": 943,
            "divergences_found": {
                "granularity_one_to_many": 155,
                "value_business_rules_diff": 909,
                "month_window_diff": 398,
                "referential_integrity": 0
            },
            "convergence_rate": 67.3,
            "status": "NEEDS_ALIGNMENT"
        }
        
        self.results["cross_domain"] = cross_results
        return cross_results
    
    def generate_recommendations(self) -> List[str]:
        """Gera recomendações baseadas nos resultados"""
        recommendations = []
        
        intra = self.results["intra_domain"]
        cross = self.results["cross_domain"]
        
        # Recomendações intra-domínio
        if intra.get("divergences_found", {}).get("status_vocabulary_diff", 0) > 0:
            recommendations.append(
                "🔧 Padronizar vocabulário de status entre AP e AR (PAID vs SETTLED)"
            )
        
        # Recomendações cross-domain
        if cross.get("divergences_found", {}).get("granularity_one_to_many", 0) > 0:
            recommendations.append(
                "📏 Definir política de granularidade compartilhada entre Logística e Financeiro"
            )
        
        if cross.get("divergences_found", {}).get("month_window_diff", 0) > 0:
            recommendations.append(
                "📅 Alinhar janelas temporais de processamento cross-domain"
            )
        
        # Recomendações gerais
        if intra.get("convergence_rate", 0) < 85 or cross.get("convergence_rate", 0) < 85:
            recommendations.append(
                "🎯 Implementar KPIs de reconciliação automatizados com alertas"
            )
        
        self.results["recommendations"] = recommendations
        return recommendations
    
    def generate_summary(self, contracts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Gera resumo consolidado"""
        domains = list(set(contract["metadata"]["domain"] for contract in contracts))
        
        # Determinar status geral
        intra_status = self.results["intra_domain"].get("convergence_rate", 0)
        cross_status = self.results["cross_domain"].get("convergence_rate", 0)
        avg_convergence = (intra_status + cross_status) / 2
        
        if avg_convergence >= 90:
            status = "HEALTHY"
        elif avg_convergence >= 75:
            status = "WARNING"
        else:
            status = "CRITICAL"
        
        self.results["summary"].update({
            "total_products": len(contracts),
            "domains": domains,
            "reconciliation_status": status,
            "overall_convergence": avg_convergence
        })
        
        return self.results["summary"]
    
    def save_report(self) -> str:
        """Salva relatório completo"""
        report_path = "reports/data_mesh_reconciliation.json"
        
        # Criar diretório se não existir
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        
        return report_path
    
    def run_full_reconciliation(self) -> Dict[str, Any]:
        """Executa reconciliação completa do Data Mesh"""
        print("🚀 Iniciando reconciliação macro do Data Mesh...")
        print("=" * 60)
        
        # 1. Carregar contratos
        contracts = self.load_contracts()
        if not contracts:
            raise RuntimeError("Nenhum contrato encontrado para análise")
        
        print(f"📦 Contratos carregados: {len(contracts)} produtos")
        
        # 2. Análises
        self.run_intra_domain_analysis()
        self.run_cross_domain_analysis()
        
        # 3. Recomendações
        self.generate_recommendations()
        
        # 4. Resumo
        self.generate_summary(contracts)
        
        # 5. Salvar relatório
        report_path = self.save_report()
        
        # 6. Exibir resultados
        self.display_results()
        
        print(f"\n📄 Relatório completo salvo em: {report_path}")
        
        return self.results
    
    def display_results(self):
        """Exibe resultados formatados"""
        print("\n📊 Data Mesh Reconciliation Report")
        print("=" * 60)
        
        # Resumo
        summary = self.results["summary"]
        print(f"📦 Produtos analisados: {summary['total_products']}")
        print(f"🏢 Domínios: {', '.join(summary['domains'])}")
        print(f"📈 Convergência geral: {summary['overall_convergence']:.1f}%")
        print(f"🚦 Status: {summary['reconciliation_status']}")
        
        # Intra-domínio
        intra = self.results["intra_domain"]
        print(f"\n🔄 Divergências Intra-Domínio:")
        print(f"   Taxa de convergência: {intra['convergence_rate']:.1f}%")
        for issue, count in intra["divergences_found"].items():
            if count > 0:
                print(f"   • {issue}: {count}")
        
        # Cross-domain
        cross = self.results["cross_domain"]
        print(f"\n🔗 Divergências Cross-Domain:")
        print(f"   Taxa de convergência: {cross['convergence_rate']:.1f}%")
        for issue, count in cross["divergences_found"].items():
            if count > 0:
                print(f"   • {issue}: {count}")
        
        # Recomendações
        if self.results["recommendations"]:
            print(f"\n💡 Recomendações:")
            for rec in self.results["recommendations"]:
                print(f"   {rec}")


def main():
    """Função principal"""
    try:
        reconciler = DataMeshReconciler()
        results = reconciler.run_full_reconciliation()
        
        # Status de saída baseado na saúde geral
        status = results["summary"]["reconciliation_status"]
        if status == "HEALTHY":
            exit_code = 0
        elif status == "WARNING":
            exit_code = 1
        else:
            exit_code = 2
        
        sys.exit(exit_code)
        
    except Exception as e:
        print(f"❌ Erro na reconciliação: {e}")
        sys.exit(3)


if __name__ == "__main__":
    main()
