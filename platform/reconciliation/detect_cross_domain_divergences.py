#!/usr/bin/env python3
"""
Detecção de divergências cross-domain (Logística vs Financeiro)

Este script analisa divergências entre operações de logística e registros financeiros
considerando:
- Granularidade 1:N (múltiplas operações por fatura)
- Diferenças de valores por regras de negócio
- Janelas temporais de processamento
- Integridade referencial

Uso: python platform/reconciliation/detect_cross_domain_divergences.py
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Any, Tuple
from collections import defaultdict

# Adiciona a raiz do projeto ao path para importar odcs_adapter
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from odcs_adapter import load_and_normalize

class CrossDomainDivergenceDetector:
    """Detector de divergências cross-domain"""
    
    def __init__(self):
        self.results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "analysis_type": "cross_domain_divergences",
            "domains_compared": ["logistica", "financeiro"],
            "total_invoices": 0,
            "matched_invoices": 0,
            "divergences": {},
            "convergence_metrics": {},
            "referential_integrity": {}
        }
    
    def load_datasets(self) -> Tuple[List[Dict], List[Dict], List[Dict]]:
        """Carrega datasets de Logística, AP e AR"""
        logistics_data = []
        ap_data = []
        ar_data = []
        
        # Carregar dados de Logística
        try:
            with open("domains/logistica/data/logistics.jsonl", "r") as f:
                for line in f:
                    if line.strip():
                        logistics_data.append(json.loads(line))
        except FileNotFoundError:
            print("❌ Dataset Logística não encontrado")
            return [], [], []
        
        # Carregar dados de AP
        try:
            with open("domains/financeiro/contas-a-pagar/data/contas_a_pagar.jsonl", "r") as f:
                for line in f:
                    if line.strip():
                        ap_data.append(json.loads(line))
        except FileNotFoundError:
            print("❌ Dataset AP não encontrado")
            return [], [], []
        
        # Carregar dados de AR
        try:
            with open("domains/financeiro/contas-a-receber/data/contas_a_receber.jsonl", "r") as f:
                for line in f:
                    if line.strip():
                        ar_data.append(json.loads(line))
        except FileNotFoundError:
            print("❌ Dataset AR não encontrado")
            return [], [], []
        
        return logistics_data, ap_data, ar_data
    
    def create_invoice_lookups(self, logistics_data: List[Dict], ap_data: List[Dict], ar_data: List[Dict]) -> Tuple[Dict, Dict, Dict]:
        """Cria lookups de invoice_id para cada domínio"""
        def create_lookup(data: List[Dict]) -> Dict[str, List[Dict]]:
            lookup = defaultdict(list)
            for record in data:
                invoice_id = record.get("invoice_id")
                if invoice_id:
                    lookup[invoice_id].append(record)
            return dict(lookup)
        
        logistics_lookup = create_lookup(logistics_data)
        ap_lookup = create_lookup(ap_data)
        ar_lookup = create_lookup(ar_data)
        
        return logistics_lookup, ap_lookup, ar_lookup
    
    def analyze_granularity_differences(self, logistics_records: List[Dict], finance_records: List[Dict]) -> List[str]:
        """Analisa diferenças de granularidade (1:N)"""
        divergences = []
        
        logistics_count = len(logistics_records)
        finance_count = len(finance_records)
        
        if logistics_count > 1 and finance_count == 1:
            divergences.append(f"granularity_one_to_many: {logistics_count} ops vs 1 financeiro")
        elif logistics_count == 1 and finance_count > 1:
            divergences.append(f"granularity_many_to_one: 1 op vs {finance_count} financeiros")
        elif logistics_count > 1 and finance_count > 1:
            divergences.append(f"granularity_many_to_many: {logistics_count} ops vs {finance_count} financeiros")
        
        return divergences
    
    def analyze_value_aggregation(self, logistics_records: List[Dict], finance_records: List[Dict]) -> List[str]:
        """Analisa diferenças de valores agregados"""
        divergences = []
        
        # Somar valores de logística
        logistics_total = sum(float(r.get("valor_total", 0)) for r in logistics_records)
        
        # Valor financeiro (usar AP como referência)
        finance_value = float(finance_records[0].get("valor_liquido", 0)) if finance_records else 0
        
        # Tolerância para diferenças (5% para regras de negócio)
        tolerance = 0.05
        
        if logistics_total > 0:
            diff_percent = abs((logistics_total - finance_value) / logistics_total) * 100
            if diff_percent > tolerance * 100:
                divergences.append(f"value_aggregation_diff: logistics {logistics_total:.2f} vs finance {finance_value:.2f} ({diff_percent:.1f}%)")
        
        return divergences
    
    def analyze_temporal_alignment(self, logistics_records: List[Dict], finance_records: List[Dict]) -> List[str]:
        """Analisa alinhamento temporal"""
        divergences = []
        
        # Extrair meses dos registros (campos originais dos output ports)
        logistics_months = set()
        for record in logistics_records:
            month = record.get("operation_date", "")
            if month:
                logistics_months.add(month[:7])
        
        finance_months = set()
        for record in finance_records:
            month = record.get("due_date", "")
            if month:
                finance_months.add(month[:7])
        
        # Verificar diferenças de janela temporal
        if logistics_months and finance_months:
            common_months = logistics_months & finance_months
            if not common_months:
                divergences.append(f"temporal_misalignment: logistics {logistics_months} vs finance {finance_months}")
            else:
                only_in_logistics = logistics_months - finance_months
                only_in_finance = finance_months - logistics_months
                if only_in_logistics:
                    divergences.append(f"logistics_ahead: {only_in_logistics}")
                if only_in_finance:
                    divergences.append(f"finance_ahead: {only_in_finance}")
        
        return divergences
    
    def analyze_referential_integrity(self, logistics_lookup: Dict, finance_lookup: Dict) -> Dict[str, int]:
        """Analisa integridade referencial"""
        integrity_metrics = {
            "logistics_orphan_records": 0,
            "finance_orphan_records": 0,
            "valid_references": 0,
            "broken_references": 0
        }
        
        logistics_invoices = set(logistics_lookup.keys())
        finance_invoices = set(finance_lookup.keys())
        
        # Registros órfãos em logística (não encontrados no financeiro)
        logistics_orphan = logistics_invoices - finance_invoices
        for invoice_id in logistics_orphan:
            integrity_metrics["logistics_orphan_records"] += len(logistics_lookup[invoice_id])
        
        # Registros órfãos no financeiro (não encontrados em logística)
        finance_orphan = finance_invoices - logistics_invoices
        for invoice_id in finance_orphan:
            integrity_metrics["finance_orphan_records"] += len(finance_lookup[invoice_id])
        
        # Referências válidas
        valid_refs = logistics_invoices & finance_invoices
        integrity_metrics["valid_references"] = len(valid_refs)
        
        # Referências quebradas (total de órfãos)
        integrity_metrics["broken_references"] = (
            integrity_metrics["logistics_orphan_records"] + 
            integrity_metrics["finance_orphan_records"]
        )
        
        return integrity_metrics
    
    def compare_cross_domain(self, logistics_lookup: Dict, ap_lookup: Dict, ar_lookup: Dict):
        """Compara dados cross-domain"""
        # Combinar dados financeiros (AP + AR)
        finance_lookup = {}
        for invoice_id in set(ap_lookup.keys()) | set(ar_lookup.keys()):
            finance_records = []
            if invoice_id in ap_lookup:
                finance_records.extend(ap_lookup[invoice_id])
            if invoice_id in ar_lookup:
                finance_records.extend(ar_lookup[invoice_id])
            finance_lookup[invoice_id] = finance_records
        
        # Todos os invoices
        all_invoice_ids = set(logistics_lookup.keys()) | set(finance_lookup.keys())
        
        divergence_categories = {
            "granularity_one_to_many": 0,
            "value_aggregation_diff": 0,
            "temporal_misalignment": 0,
            "only_in_logistics": 0,
            "only_in_finance": 0,
            "data_quality_issues": 0
        }
        
        matched_invoices = 0
        
        for invoice_id in all_invoice_ids:
            logistics_records = logistics_lookup.get(invoice_id, [])
            finance_records = finance_lookup.get(invoice_id, [])
            
            # Verificar existência em ambos
            if not logistics_records:
                divergence_categories["only_in_finance"] += len(finance_records)
                continue
            if not finance_records:
                divergence_categories["only_in_logistics"] += len(logistics_records)
                continue
            
            # Análises cross-domain
            granularity_div = self.analyze_granularity_differences(logistics_records, finance_records)
            value_div = self.analyze_value_aggregation(logistics_records, finance_records)
            temporal_div = self.analyze_temporal_alignment(logistics_records, finance_records)
            
            # Contabilizar divergências
            if granularity_div:
                divergence_categories["granularity_one_to_many"] += 1
            if value_div:
                divergence_categories["value_aggregation_diff"] += 1
            if temporal_div:
                divergence_categories["temporal_misalignment"] += 1
            
            # Verificar qualidade dos dados
            if any(not r.get("invoice_id") for r in logistics_records + finance_records):
                divergence_categories["data_quality_issues"] += 1
            
            # Considerar como matched se não houver divergências críticas
            if not value_div and not temporal_div:
                matched_invoices += 1
        
        self.results["divergences"] = divergence_categories
        self.results["matched_invoices"] = matched_invoices
        self.results["total_invoices"] = len(all_invoice_ids)
        
        # Análise de integridade referencial
        self.results["referential_integrity"] = self.analyze_referential_integrity(
            logistics_lookup, finance_lookup
        )
        
        # Calcular métricas de convergência
        convergence_rate = (matched_invoices / len(all_invoice_ids)) * 100 if all_invoice_ids else 0
        self.results["convergence_metrics"] = {
            "convergence_rate": convergence_rate,
            "coverage_logistics": len(set(logistics_lookup.keys()) & set(finance_lookup.keys())) / len(set(logistics_lookup.keys())) * 100,
            "coverage_finance": len(set(logistics_lookup.keys()) & set(finance_lookup.keys())) / len(set(finance_lookup.keys())) * 100,
            "referential_integrity_rate": (self.results["referential_integrity"]["valid_references"] / len(all_invoice_ids)) * 100 if all_invoice_ids else 0
        }
    
    def generate_recommendations(self) -> List[str]:
        """Gera recomendações baseadas nas divergências"""
        recommendations = []
        divergences = self.results["divergences"]
        integrity = self.results["referential_integrity"]
        
        if divergences.get("granularity_one_to_many", 0) > 0:
            recommendations.append(
                "📏 Documentar política de granularidade: N operações por fatura é esperado"
            )
        
        if divergences.get("value_aggregation_diff", 0) > 0:
            recommendations.append(
                "💰 Mapear regras de negócio cross-domain: custos logísticos vs valor financeiro"
            )
        
        if divergences.get("temporal_misalignment", 0) > 0:
            recommendations.append(
                "📅 Sincronizar janelas temporais de processamento entre domínios"
            )
        
        if integrity.get("broken_references", 0) > 0:
            recommendations.append(
                "🔗 Implementar validação de integridade referencial em tempo real"
            )
        
        if integrity.get("logistics_orphan_records", 0) > 0:
            recommendations.append(
                "🚨 Investigar operações logísticas não faturadas"
            )
        
        convergence = self.results["convergence_metrics"]["convergence_rate"]
        if convergence < 75:
            recommendations.append(
                "📈 Estabelecer SLAs de reconciliação cross-domain com monitoramento"
            )
        
        return recommendations
    
    def save_report(self) -> str:
        """Salva relatório da análise"""
        report_path = "reports/cross_domain_divergences_analysis.json"
        
        # Criar diretório se não existir
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        
        # Adicionar recomendações
        self.results["recommendations"] = self.generate_recommendations()
        
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        
        return report_path
    
    def display_results(self):
        """Exibe resultados formatados"""
        print("\n📊 Cross-Domain Divergences Analysis (Logística vs Financeiro)")
        print("=" * 70)
        
        # Métricas gerais
        metrics = self.results["convergence_metrics"]
        print(f"📈 Taxa de convergência: {metrics['convergence_rate']:.1f}%")
        print(f"📋 Cobertura Logística: {metrics['coverage_logistics']:.1f}%")
        print(f"📋 Cobertura Financeiro: {metrics['coverage_finance']:.1f}%")
        print(f"🔗 Integridade Referencial: {metrics['referential_integrity_rate']:.1f}%")
        
        # Divergências detalhadas
        print(f"\n🔍 Divergências encontradas:")
        divergences = self.results["divergences"]
        total_div = sum(divergences.values())
        
        for category, count in divergences.items():
            if count > 0:
                percent = (count / total_div) * 100 if total_div > 0 else 0
                print(f"   • {category}: {count} ({percent:.1f}%)")
        
        # Integridade referencial
        integrity = self.results["referential_integrity"]
        print(f"\n🔗 Integridade Referencial:")
        print(f"   • Referências válidas: {integrity['valid_references']}")
        print(f"   • Registros órfãos (logística): {integrity['logistics_orphan_records']}")
        print(f"   • Registros órfãos (financeiro): {integrity['finance_orphan_records']}")
        
        # Recomendações
        if self.results.get("recommendations"):
            print(f"\n💡 Recomendações:")
            for rec in self.results["recommendations"]:
                print(f"   {rec}")
    
    def run_analysis(self) -> Dict[str, Any]:
        """Executa análise completa"""
        print("🔍 Analisando divergências cross-domain (Logística vs Financeiro)...")
        
        # Carregar datasets
        logistics_data, ap_data, ar_data = self.load_datasets()
        if not logistics_data or not ap_data or not ar_data:
            raise RuntimeError("Datasets não encontrados")
        
        print(f"📊 Logística: {len(logistics_data)} registros")
        print(f"📊 AP: {len(ap_data)} registros")
        print(f"📊 AR: {len(ar_data)} registros")
        
        # Criar lookups
        logistics_lookup, ap_lookup, ar_lookup = self.create_invoice_lookups(
            logistics_data, ap_data, ar_data
        )
        
        print(f"🔑 Logística: {len(logistics_lookup)} faturas únicas")
        print(f"🔑 Financeiro (AP+AR): {len(set(ap_lookup.keys()) | set(ar_lookup.keys()))} faturas únicas")
        
        # Comparar cross-domain
        self.compare_cross_domain(logistics_lookup, ap_lookup, ar_lookup)
        
        # Salvar relatório
        report_path = self.save_report()
        
        # Exibir resultados
        self.display_results()
        
        print(f"\n📄 Relatório completo em: {report_path}")
        
        return self.results


def main():
    """Função principal"""
    try:
        detector = CrossDomainDivergenceDetector()
        results = detector.run_analysis()
        
        # Relatório gerado com sucesso. Divergências fazem parte do output esperado
        # e não devem quebrar o baseline da arquitetura.
        sys.exit(0)
        
    except Exception as e:
        print(f"❌ Erro na análise: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
