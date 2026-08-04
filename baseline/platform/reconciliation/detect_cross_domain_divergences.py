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
        """
        Compara a ordem de grandeza dos valores entre os domínios.

        ATENÇÃO — esta NÃO é uma verificação de igualdade. `valor_total` da
        logística (mercadoria + frete + seguro + imposto) e `valor_liquido` da
        fatura são grandezas distintas por definição: não existe regra de
        negócio que as obrigue a coincidir, e nestes dados sintéticos os
        geradores as produzem de forma independente (vinculam apenas a chave
        `invoice_id`, não os montantes).

        Por isso o resultado é classificado como *achado informacional*, não
        como divergência. A versão anterior usava tolerância de 5 % sobre
        valores não comparáveis e acusava 913 de 939 faturas — falso positivo
        por construção.

        A razão entre os dois valores é registrada como estatística descritiva,
        sem limiar de aprovação/reprovação. Nos dados atuais ela varia de forma
        contínua (p1 ≈ 0,02; mediana ≈ 1,16; p99,9 ≈ 91), sem descontinuidade
        que permita separar "anômalo" de "normal" — qualquer corte seria
        arbitrário e produziria falso positivo no baseline.

        Um limiar só faria sentido se o contrato declarasse a relação esperada
        entre os domínios (p.ex. "frete ≤ 30 % do valor da fatura"). Enquanto
        essa regra não existir na governança federada, não há o que validar.
        """
        return []

    # Combinações de estado factualmente contraditórias entre os domínios.
    # Chave: estado no Financeiro. Valor: estados logísticos incompatíveis.
    #
    # CANCELADO x CONCLUIDO — a conclusão afirma um fato (mercadoria movimentada,
    # entrega realizada) incompatível com o cancelamento da obrigação financeira.
    # Estados transitórios (PENDENTE, EM_PROCESSAMENTO) NÃO são contraditórios:
    # podem coexistir com um cancelamento ainda não propagado à Logística.
    ESTADOS_INCOMPATIVEIS = {
        "CANCELADO": {"CONCLUIDO"},
    }

    def analyze_state_coherence(self, logistics_records: List[Dict],
                                finance_records: List[Dict]) -> List[str]:
        """
        Detecta combinações de estado contraditórias entre Logística e Financeiro.

        Esta verificação NÃO existe em nenhuma camada da arquitetura. Os
        vocabulários de estado são autônomos por domínio (Princípio 1) e cada
        valor é individualmente válido em seu contrato, de modo que a
        contradição não reside em nenhum registro isoladamente --- apenas na
        relação entre registros de domínios distintos.

        Implementada aqui por ser este o instrumento de análise: seu propósito
        é justamente revelar inconsistências que a governança federada deixa
        passar. Não confundir com mecanismo da arquitetura.
        """
        divergences = []
        if not finance_records:
            return divergences

        finance_status = finance_records[0].get("status")
        proibidos = self.ESTADOS_INCOMPATIVEIS.get(finance_status)
        if not proibidos:
            return divergences

        for record in logistics_records:
            estados = record.get("status", [])
            if not isinstance(estados, list):
                estados = [estados]
            for estado in estados:
                if estado in proibidos:
                    divergences.append(
                        f"state_contradiction: logística '{estado}' vs "
                        f"financeiro '{finance_status}'"
                    )
                    break
        return divergences

    # Atributos publicados por AMBOS os domínios com a mesma semântica, para os
    # quais divergência entre produtos caracteriza inconsistência.
    #
    # `dsc_moeda` é padrão semântico global (ISO-4217, restrito a BRL na
    # política federada). Cada produto valida a própria moeda contra o seu
    # contrato, mas nenhuma camada da arquitetura verifica se os dois domínios
    # publicam a MESMA moeda para a mesma fatura — se divergirem, valores
    # deixam de ser somáveis sem que nada sinalize.
    #
    # Não inclui `valor_base`: homônimo com semânticas distintas, declaradas
    # como não comparáveis nos respectivos contratos.
    ATRIBUTOS_COMUNS = ["dsc_moeda"]

    def analyze_attribute_divergence(self, logistics_records: List[Dict],
                                     finance_records: List[Dict]) -> List[str]:
        """
        Compara atributos de mesma semântica publicados pelos dois domínios.

        Como a contradição existe apenas na relação entre produtos, nenhum
        registro está individualmente em desconformidade e nenhuma camada da
        arquitetura a sinaliza. Verificação pertencente ao instrumento de
        análise, não à arquitetura.
        """
        divergences = []
        if not finance_records or not logistics_records:
            return divergences

        for atributo in self.ATRIBUTOS_COMUNS:
            valor_fin = finance_records[0].get(atributo)
            if valor_fin is None:
                continue
            for record in logistics_records:
                valor_log = record.get(atributo)
                if valor_log is not None and valor_log != valor_fin:
                    divergences.append(
                        f"attribute_divergence: {atributo} "
                        f"logística='{valor_log}' vs financeiro='{valor_fin}'"
                    )
                    break
        return divergences

    @staticmethod
    def _print_ids(rotulo: str, ids: List[str], por_linha: int = 6) -> None:
        """Lista completa de invoice_ids, quebrada em linhas legíveis."""
        if not ids:
            return
        print(f"   {rotulo} ({len(ids)}):")
        for i in range(0, len(ids), por_linha):
            print("      " + ", ".join(ids[i:i + por_linha]))

    def value_ratio_stats(self, logistics_records: List[Dict], finance_records: List[Dict]):
        """Razão valor logístico / valor da fatura, para estatística descritiva."""
        logistics_total = sum(float(r.get("valor_total", 0)) for r in logistics_records)
        finance_value = float(finance_records[0].get("valor_liquido", 0)) if finance_records else 0
        if logistics_total > 0 and finance_value > 0:
            return logistics_total / finance_value
        return None
    
    def analyze_temporal_alignment(self, logistics_records: List[Dict], finance_records: List[Dict]) -> List[str]:
        """Analisa alinhamento temporal"""
        divergences = []
        
        # Extrair meses dos registros publicados.
        #
        # Os output ports analíticos publicam `meses_operacao` (lista de meses,
        # logística) e `mes_emissao` (string, financeiro). Este método lia
        # `operation_date` e `due_date`, que existem apenas na camada
        # OPERACIONAL — ambos os conjuntos ficavam vazios, a condição abaixo
        # nunca era satisfeita e `temporal_misalignment` permanecia sempre zero.
        logistics_months = set()
        for record in logistics_records:
            for month in record.get("meses_operacao", []) or []:
                if month:
                    logistics_months.add(str(month)[:7])

        finance_months = set()
        for record in finance_records:
            month = record.get("mes_emissao", "")
            if month:
                finance_months.add(str(month)[:7])
        
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
            "logistics_orphan_invoices": 0,
            "finance_without_logistics_invoices": 0,
            "valid_references": 0,
            "broken_references": 0,
        }

        logistics_invoices = set(logistics_lookup.keys())
        finance_invoices = set(finance_lookup.keys())

        # ÓRFÃO DE VERDADE: operação logística que referencia uma fatura
        # inexistente no financeiro. A logística é quem carrega a chave
        # estrangeira, então só ela pode quebrar a integridade referencial.
        logistics_orphan = logistics_invoices - finance_invoices
        integrity_metrics["logistics_orphan_invoices"] = len(logistics_orphan)
        for invoice_id in logistics_orphan:
            integrity_metrics["logistics_orphan_records"] += len(logistics_lookup[invoice_id])

        # NÃO é órfão: fatura sem operação logística. Nem toda fatura gera
        # frete (serviços, faturas canceladas). O financeiro não referencia a
        # logística — a ausência não quebra nada. Registrado como cobertura
        # parcial, em faturas (não em registros, para não contar AP e AR duas
        # vezes para a mesma fatura).
        integrity_metrics["finance_without_logistics_invoices"] = len(
            finance_invoices - logistics_invoices
        )

        integrity_metrics["valid_references"] = len(logistics_invoices & finance_invoices)

        # Só referências de fato quebradas.
        integrity_metrics["broken_references"] = integrity_metrics["logistics_orphan_records"]

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
            "state_contradiction": 0,
            "attribute_divergence": 0,
            "temporal_misalignment": 0,
            "only_in_logistics": 0,
            "data_quality_issues": 0
        }
        state_contradiction_examples = []
        temporal_examples = []
        attribute_divergence_examples = []
        value_ratios = []
        # Faturas sem operação logística NÃO são divergência: nem toda fatura
        # gera frete (serviços, faturas canceladas, etc.). Trata-se de cobertura
        # parcial esperada, reportada como métrica informacional.
        informational_coverage = {"finance_without_logistics": 0}
        informational_findings = {
            "granularity_one_to_many": 0,
            "granularity_many_to_one": 0,
            "granularity_many_to_many": 0,
        }

        matched_invoices = 0

        for invoice_id in all_invoice_ids:
            logistics_records = logistics_lookup.get(invoice_id, [])
            finance_records = finance_lookup.get(invoice_id, [])

            # Verificar existência em ambos.
            # Contamos FATURAS, não registros: uma fatura presente em AP e AR
            # é uma única fatura sem logística, não duas.
            if not logistics_records:
                informational_coverage["finance_without_logistics"] += 1
                continue
            if not finance_records:
                # Operação logística apontando para fatura inexistente: esta sim
                # é violação de integridade referencial.
                divergence_categories["only_in_logistics"] += len(logistics_records)
                continue

            # Análises cross-domain
            granularity_div = self.analyze_granularity_differences(logistics_records, finance_records)
            temporal_div = self.analyze_temporal_alignment(logistics_records, finance_records)
            state_div = self.analyze_state_coherence(logistics_records, finance_records)
            attr_div = self.analyze_attribute_divergence(logistics_records, finance_records)
            value_div = []  # ver analyze_value_aggregation: sem regra declarada, nada a validar

            if state_div:
                divergence_categories["state_contradiction"] += len(state_div)
                state_contradiction_examples.append({
                    "invoice_id": invoice_id,
                    "status_logistica": logistics_records[0].get("status"),
                    "status_financeiro": finance_records[0].get("status"),
                    "detalhe": state_div[0],
                })

            if attr_div:
                divergence_categories["attribute_divergence"] += len(attr_div)
                attribute_divergence_examples.append({
                    "invoice_id": invoice_id,
                    "detalhe": attr_div[0],
                })

            # Granularidade 1:N (e derivados) é informacional: no domínio logístico
            # é normal haver várias operações para uma mesma fatura (recebimento,
            # envio, paradas, etc.), portanto não é divergência.
            for finding in granularity_div:
                key = "granularity_one_to_many"
                if "many_to_one" in finding:
                    key = "granularity_many_to_one"
                elif "many_to_many" in finding:
                    key = "granularity_many_to_many"
                informational_findings[key] += 1

            ratio = self.value_ratio_stats(logistics_records, finance_records)
            if ratio is not None:
                value_ratios.append(ratio)
            if temporal_div:
                divergence_categories["temporal_misalignment"] += 1
                meses_log = sorted({m for r in logistics_records
                                    for m in (r.get("meses_operacao") or [])})
                temporal_examples.append({
                    "invoice_id": invoice_id,
                    "meses_operacao_logistica": meses_log,
                    "mes_emissao_financeiro": finance_records[0].get("mes_emissao"),
                    "detalhe": temporal_div[0],
                })

            # Verificar qualidade dos dados
            if any(not r.get("invoice_id") for r in logistics_records + finance_records):
                divergence_categories["data_quality_issues"] += 1

            # Considerar como matched se não houver divergências críticas
            if not value_div and not temporal_div and not state_div and not attr_div:
                matched_invoices += 1

        self.results["divergences"] = divergence_categories
        self.results["informational_findings"] = informational_findings
        self.results["informational_coverage"] = informational_coverage
        if state_contradiction_examples:
            self.results["state_contradiction_examples"] = sorted(
                state_contradiction_examples, key=lambda e: e["invoice_id"])
        if temporal_examples:
            self.results["temporal_misalignment_examples"] = sorted(
                temporal_examples, key=lambda e: e["invoice_id"])
        if attribute_divergence_examples:
            self.results["attribute_divergence_examples"] = sorted(
                attribute_divergence_examples, key=lambda e: e["invoice_id"])
        if value_ratios:
            ordenado = sorted(value_ratios)
            self.results["value_ratio_stats"] = {
                "description": ("razão valor_total logístico / valor_liquido da fatura; "
                                "grandezas distintas, sem regra de negócio que as vincule"),
                "n": len(ordenado),
                "min": round(ordenado[0], 4),
                "p50": round(ordenado[len(ordenado) // 2], 4),
                "max": round(ordenado[-1], 4),
            }
        self.results["matched_invoices"] = matched_invoices
        self.results["total_invoices"] = len(all_invoice_ids)
        # Universo comparável: só faturas presentes nos DOIS domínios. Faturas
        # sem logística não podem convergir nem divergir — incluí-las no
        # denominador subestima a convergência.
        comparable = len(set(logistics_lookup.keys()) & set(finance_lookup.keys()))
        self.results["comparable_invoices"] = comparable
        
        # Análise de integridade referencial
        self.results["referential_integrity"] = self.analyze_referential_integrity(
            logistics_lookup, finance_lookup
        )
        
        # Métricas de convergência, calculadas sobre o universo comparável.
        convergence_rate = (matched_invoices / comparable) * 100 if comparable else 0
        logistics_keys = set(logistics_lookup.keys())
        # Integridade referencial: das faturas citadas pela logística, quantas
        # existem de fato no financeiro. Faturas sem logística não entram —
        # elas não são referências quebradas.
        referential_rate = (
            (len(logistics_keys & set(finance_lookup.keys())) / len(logistics_keys)) * 100
            if logistics_keys else 100.0
        )
        self.results["convergence_metrics"] = {
            "convergence_rate": convergence_rate,
            "convergence_basis": "faturas presentes em ambos os domínios",
            "coverage_logistics": len(logistics_keys & set(finance_lookup.keys())) / len(logistics_keys) * 100,
            "coverage_finance": len(logistics_keys & set(finance_lookup.keys())) / len(set(finance_lookup.keys())) * 100,
            "referential_integrity_rate": referential_rate,
        }
    
    def save_report(self) -> str:
        """Salva relatório da análise"""
        report_path = "reports/cross_domain_divergences_analysis.json"
        
        # Criar diretório se não existir
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        
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

        # Achados informacionais (não são divergências)
        informational = self.results.get("informational_findings", {})
        coverage = self.results.get("informational_coverage", {})
        total_info = sum(informational.values()) + sum(coverage.values())
        if total_info > 0:
            print(f"\nℹ️  Achados informacionais (não divergências):")
            for category, count in informational.items():
                if count > 0:
                    print(f"   • {category}: {count}")
            sem_log = coverage.get("finance_without_logistics", 0)
            if sem_log:
                print(f"   • finance_without_logistics: {sem_log} faturas "
                      f"(esperado — nem toda fatura gera frete)")

        exemplos = self.results.get("state_contradiction_examples")
        if exemplos:
            print(f"\n🚨 Contradições de estado entre domínios "
                  f"({self.results['divergences']['state_contradiction']}):")
            for e in exemplos[:10]:
                print(f"   • {e['invoice_id']}: logística={e['status_logistica']} "
                      f"vs financeiro={e['status_financeiro']}")
            if len(exemplos) > 10:
                print(f"   … e mais {len(exemplos)-10}")
            self._print_ids("invoice_id afetados", [e["invoice_id"] for e in exemplos])
            print("   ℹ️ Nenhuma camada da arquitetura sinaliza esta classe de inconsistência")

        attrs = self.results.get("attribute_divergence_examples")
        if attrs:
            print(f"\n🚨 Atributos comuns divergentes entre domínios "
                  f"({self.results['divergences']['attribute_divergence']}):")
            for e in attrs[:10]:
                print(f"   • {e['invoice_id']}: {e['detalhe']}")
            if len(attrs) > 10:
                print(f"   … e mais {len(attrs)-10}")
            self._print_ids("invoice_id afetados", [e["invoice_id"] for e in attrs])
            print("   ℹ️ Nenhuma camada da arquitetura compara este atributo entre produtos")

        temporais = self.results.get("temporal_misalignment_examples")
        if temporais:
            print(f"\n🚨 Desalinhamento temporal entre domínios ({len(temporais)}):")
            for e in temporais[:10]:
                print(f"   • {e['invoice_id']}: operação em "
                      f"{e['meses_operacao_logistica']} vs emissão em "
                      f"{e['mes_emissao_financeiro']}")
            if len(temporais) > 10:
                print(f"   … e mais {len(temporais)-10}")
            self._print_ids("invoice_id afetados", [e["invoice_id"] for e in temporais])
            print("   ℹ️ Nenhuma política declara a relação esperada entre os dois períodos")

        vr = self.results.get("value_ratio_stats")
        if vr:
            print(f"\n📐 Razão valor logístico / valor da fatura (n={vr['n']}):")
            print(f"   min={vr['min']}  mediana={vr['p50']}  max={vr['max']}")
            print("   ℹ️ Grandezas distintas (mercadoria+frete+seguro+imposto vs valor")
            print("      da fatura). Sem regra declarada no contrato, não há o que validar.")

        # Integridade referencial
        integrity = self.results["referential_integrity"]
        print(f"\n🔗 Integridade Referencial:")
        print(f"   • Referências válidas: {integrity['valid_references']} faturas")
        print(f"   • Órfãos (logística → fatura inexistente): "
              f"{integrity['logistics_orphan_records']} registros "
              f"em {integrity['logistics_orphan_invoices']} faturas")
        print(f"   • Faturas sem logística: "
              f"{integrity['finance_without_logistics_invoices']} (não é violação)")
    
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
