#!/usr/bin/env python3
"""
Detecção de divergências naturais intra-domínio (AP vs AR)

Este script analisa divergências esperadas entre Contas a Pagar e Contas a Receber
considerando:
- Diferenças de vocabulário de status (PAID vs SETTLED)
- Regras de negócio que afetam valores (retenções, juros)
- Timing de processamento

Uso: python platform/reconciliation/detect_natural_divergences.py
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Any, Tuple

# Adiciona a raiz do projeto ao path para importar odcs_adapter
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from odcs_adapter import load_and_normalize

class NaturalDivergenceDetector:
    """Detector de divergências naturais intra-domínio"""
    
    def __init__(self):
        self.results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "analysis_type": "natural_divergences",
            "domains": ["financeiro"],
            "products_compared": [],
            "total_invoices": 0,
            "matched_invoices": 0,
            "divergences": {},
            "convergence_metrics": {}
        }
    
    def load_datasets(self) -> Tuple[List[Dict], List[Dict]]:
        """Carrega datasets de AP e AR"""
        ap_data = []
        ar_data = []
        
        # Carregar dados de AP
        try:
            with open("domains/financeiro/contas-a-pagar/data/ap.jsonl", "r") as f:
                for line in f:
                    if line.strip():
                        ap_data.append(json.loads(line))
        except FileNotFoundError:
            print("❌ Dataset AP não encontrado")
            return [], []
        
        # Carregar dados de AR
        try:
            with open("domains/financeiro/contas-a-receber/data/ar.jsonl", "r") as f:
                for line in f:
                    if line.strip():
                        ar_data.append(json.loads(line))
        except FileNotFoundError:
            print("❌ Dataset AR não encontrado")
            return [], []
        
        return ap_data, ar_data
    
    def create_invoice_lookup(self, data: List[Dict]) -> Dict[str, Dict]:
        """Cria lookup de invoice_id para registros"""
        lookup = {}
        for record in data:
            invoice_id = record.get("invoice_id")
            if invoice_id:
                if invoice_id not in lookup:
                    lookup[invoice_id] = []
                lookup[invoice_id].append(record)
        return lookup
    
    def analyze_status_vocabulary(self, ap_record: Dict, ar_record: Dict) -> List[str]:
        """Analisa divergências de vocabulário de status"""
        divergences = []
        
        ap_status = ap_record.get("status", "")
        ar_status = ar_record.get("status", "")
        
        # Mapeamento de vocabulário esperado
        status_mapping = {
            "PAID": "SETTLED",  # AP usa PAID, AR usa SETTLED
            "OPEN": "PENDING",  # Diferenças terminológicas
        }
        
        if ap_status in status_mapping and status_mapping[ap_status] != ar_status:
            divergences.append(f"status_vocabulary_diff: {ap_status} vs {ar_status}")
        elif ap_status not in status_mapping and ap_status != ar_status:
            divergences.append(f"status_unmapped_diff: {ap_status} vs {ar_status}")
        
        return divergences
    
    def analyze_amount_differences(self, ap_record: Dict, ar_record: Dict) -> List[str]:
        """Analisa diferenças de valor com regras de negócio"""
        divergences = []
        
        ap_amount = float(ap_record.get("amount", 0))
        ar_amount = float(ar_record.get("amount", 0))
        
        # Tolerância para diferenças pequenas (arredondamento)
        tolerance = 0.01
        
        if abs(ap_amount - ar_amount) > tolerance:
            diff_percent = abs((ap_amount - ar_amount) / ap_amount) * 100
            divergences.append(f"amount_diff: {ap_amount} vs {ar_amount} ({diff_percent:.1f}%)")
        
        return divergences
    
    def analyze_timing_differences(self, ap_record: Dict, ar_record: Dict) -> List[str]:
        """Analisa diferenças de timing"""
        divergences = []
        
        ap_date = ap_record.get("due_date", "")
        ar_date = ar_record.get("due_date", "")
        
        if ap_date != ar_date:
            divergences.append(f"due_date_diff: {ap_date} vs {ar_date}")
        
        return divergences
    
    def compare_invoices(self, ap_lookup: Dict[str, List[Dict]], ar_lookup: Dict[str, List[Dict]]):
        """Compara faturas entre AP e AR"""
        all_invoice_ids = set(ap_lookup.keys()) | set(ar_lookup.keys())
        matched_invoices = 0
        
        divergence_categories = {
            "status_vocabulary_diff": 0,
            "amount_diff": 0,
            "due_date_diff": 0,
            "only_in_ap": 0,
            "only_in_ar": 0,
            "multiple_records": 0
        }
        
        for invoice_id in all_invoice_ids:
            ap_records = ap_lookup.get(invoice_id, [])
            ar_records = ar_lookup.get(invoice_id, [])
            
            # Verificar se existe em ambos
            if not ap_records:
                divergence_categories["only_in_ar"] += len(ar_records)
                continue
            if not ar_records:
                divergence_categories["only_in_ap"] += len(ap_records)
                continue
            
            # Verificar multiplicidade (deveria ser 1:1)
            if len(ap_records) > 1 or len(ar_records) > 1:
                divergence_categories["multiple_records"] += max(len(ap_records), len(ar_records))
                continue
            
            # Comparar registros pareados
            ap_record = ap_records[0]
            ar_record = ar_records[0]
            
            # Análises específicas
            status_div = self.analyze_status_vocabulary(ap_record, ar_record)
            amount_div = self.analyze_amount_differences(ap_record, ar_record)
            timing_div = self.analyze_timing_differences(ap_record, ar_record)
            
            # Contabilizar divergências
            if status_div:
                divergence_categories["status_vocabulary_diff"] += 1
            if amount_div:
                divergence_categories["amount_diff"] += 1
            if timing_div:
                divergence_categories["due_date_diff"] += 1
            
            # Se não houver divergências críticas, consideramos como matched
            if not amount_div and not timing_div:
                matched_invoices += 1
        
        self.results["divergences"] = divergence_categories
        self.results["matched_invoices"] = matched_invoices
        self.results["total_invoices"] = len(all_invoice_ids)
        
        # Calcular métricas de convergência
        convergence_rate = (matched_invoices / len(all_invoice_ids)) * 100 if all_invoice_ids else 0
        self.results["convergence_metrics"] = {
            "convergence_rate": convergence_rate,
            "coverage_rate": (matched_invoices / max(len(ap_lookup), len(ar_lookup))) * 100,
            "divergence_rate": 100 - convergence_rate
        }
    
    def generate_recommendations(self) -> List[str]:
        """Gera recomendações baseadas nas divergências"""
        recommendations = []
        divergences = self.results["divergences"]
        
        if divergences.get("status_vocabulary_diff", 0) > 0:
            recommendations.append(
                "🔧 Padronizar vocabulário de status: mapear PAID→SETTLED em catálogo federado"
            )
        
        if divergences.get("amount_diff", 0) > 0:
            recommendations.append(
                "💰 Documentar regras de negócio que afetam valores (retenções, juros, multas)"
            )
        
        if divergences.get("due_date_diff", 0) > 0:
            recommendations.append(
                "📅 Alinhar cálculo de due dates entre sistemas AP e AR"
            )
        
        if divergences.get("only_in_ap", 0) > 0 or divergences.get("only_in_ar", 0) > 0:
            recommendations.append(
                "🔍 Investigar faturas não pareadas (possíveis problemas de integração)"
            )
        
        convergence = self.results["convergence_metrics"]["convergence_rate"]
        if convergence < 85:
            recommendations.append(
                "📈 Implementar KPIs de reconciliação com alertas automáticos"
            )
        
        return recommendations
    
    def save_report(self) -> str:
        """Salva relatório da análise"""
        report_path = "reports/natural_divergences_analysis.json"
        
        # Criar diretório se não existir
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        
        # Adicionar recomendações
        self.results["recommendations"] = self.generate_recommendations()
        
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        
        return report_path
    
    def display_results(self):
        """Exibe resultados formatados"""
        print("\n📊 Natural Divergences Analysis (AP vs AR)")
        print("=" * 55)
        
        # Métricas gerais
        metrics = self.results["convergence_metrics"]
        print(f"📈 Taxa de convergência: {metrics['convergence_rate']:.1f}%")
        print(f"📋 Taxa de cobertura: {metrics['coverage_rate']:.1f}%")
        print(f"⚠️ Taxa de divergência: {metrics['divergence_rate']:.1f}%")
        
        # Divergências detalhadas
        print(f"\n🔍 Divergências encontradas:")
        divergences = self.results["divergences"]
        total_div = sum(divergences.values())
        
        for category, count in divergences.items():
            if count > 0:
                percent = (count / total_div) * 100 if total_div > 0 else 0
                print(f"   • {category}: {count} ({percent:.1f}%)")
        
        # Recomendações
        if self.results.get("recommendations"):
            print(f"\n💡 Recomendações:")
            for rec in self.results["recommendations"]:
                print(f"   {rec}")
    
    def run_analysis(self) -> Dict[str, Any]:
        """Executa análise completa"""
        print("🔍 Analisando divergências naturais intra-domínio (AP vs AR)...")
        
        # Carregar datasets
        ap_data, ar_data = self.load_datasets()
        if not ap_data or not ar_data:
            raise RuntimeError("Datasets não encontrados")
        
        print(f"📊 AP: {len(ap_data)} registros")
        print(f"📊 AR: {len(ar_data)} registros")
        
        # Criar lookups
        ap_lookup = self.create_invoice_lookup(ap_data)
        ar_lookup = self.create_invoice_lookup(ar_data)
        
        print(f"🔑 AP: {len(ap_lookup)} faturas únicas")
        print(f"🔑 AR: {len(ar_lookup)} faturas únicas")
        
        # Comparar faturas
        self.compare_invoices(ap_lookup, ar_lookup)
        
        # Salvar relatório
        report_path = self.save_report()
        
        # Exibir resultados
        self.display_results()
        
        print(f"\n📄 Relatório completo em: {report_path}")
        
        return self.results


def main():
    """Função principal"""
    try:
        detector = NaturalDivergenceDetector()
        results = detector.run_analysis()
        
        # Status de saída baseado na convergência
        convergence = results["convergence_metrics"]["convergence_rate"]
        if convergence >= 85:
            exit_code = 0
        elif convergence >= 70:
            exit_code = 1
        else:
            exit_code = 2
        
        sys.exit(exit_code)
        
    except Exception as e:
        print(f"❌ Erro na análise: {e}")
        sys.exit(3)


if __name__ == "__main__":
    main()
