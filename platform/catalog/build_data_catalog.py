import json
import os
import yaml
from datetime import datetime, timezone
from typing import Dict, List, Any

class DataCatalog:
    """Catálogo de Descoberta de Produtos de Dados (Data Mesh Pattern)"""
    
    def __init__(self):
        self.catalog = {
            "catalog_metadata": {
                "name": "Enterprise Data Products Catalog",
                "version": "1.0.0",
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "total_products": 0,
                "domains": [],
                "description": "Catálogo federado de produtos de dados da empresa"
            },
            "products": [],
            "domains": {},
            "search_indices": {
                "by_domain": {},
                "by_tags": {},
                "by_fields": {},
                "by_consumers": {}
            }
        }
    
    def add_product_from_contract(self, contract_path: str) -> None:
        """Adiciona produto ao catálogo a partir do contrato"""
        with open(contract_path, 'r', encoding='utf-8') as f:
            contract = yaml.safe_load(f)
        
        metadata = contract.get("metadata", {})
        spec = contract.get("spec", {})
        
        product = {
            "product_id": metadata.get("name", "").lower().replace(" ", "-"),
            "name": metadata.get("name", ""),
            "domain": metadata.get("domain", ""),
            "owner": metadata.get("owner", ""),
            "version": metadata.get("version", ""),
            "description": metadata.get("description", ""),
            "tags": metadata.get("tags", []),
            "created_at": metadata.get("created_at", ""),
            "last_modified": metadata.get("last_modified", ""),
            
            # Schema Information
            "schema": {
                "registry": spec.get("schema", {}).get("registry", ""),
                "subject": spec.get("schema", {}).get("subject", ""),
                "format": spec.get("schema", {}).get("format", ""),
                "evolution_policy": spec.get("schema", {}).get("evolution", {}).get("policy", ""),
                "breaking_changes": spec.get("schema", {}).get("evolution", {}).get("breaking_changes", ""),
                "deprecation_period": spec.get("schema", {}).get("evolution", {}).get("deprecation_period", "")
            },
            
            # SLA Information
            "sla": {
                "freshness": spec.get("product", {}).get("sla", {}).get("freshness", ""),
                "availability": spec.get("product", {}).get("sla", {}).get("availability", ""),
                "latency": spec.get("product", {}).get("sla", {}).get("latency", ""),
                "throughput": spec.get("product", {}).get("sla", {}).get("throughput", "")
            },
            
            # Dataset Fields
            "dataset_fields": spec.get("dataset", {}).get("fields", []),
            
            # Quality Rules
            "quality_rules": spec.get("quality", {}).get("rules", []),
            
            # Consumers
            "consumers": spec.get("consumers", []),
            
            # Monitoring
            "monitoring": spec.get("monitoring", {}),
            
            # Discovery Metadata
            "discovery": {
                "lineage_fields": [],
                "cross_domain_relationships": [],
                "searchable_fields": [],
                "data_quality_metrics": []
            }
        }
        
        # Extrair campos de lineage
        lineage_fields = ["source_event_id", "source_system", "processing_batch_id"]
        for field in product["dataset_fields"]:
            field_name = field.get("name", "")
            if field_name in lineage_fields:
                product["discovery"]["lineage_fields"].append(field_name)
                product["discovery"]["searchable_fields"].append(field_name)
        
        # Identificar relacionamentos cross-domain
        for field in product["dataset_fields"]:
            field_name = field.get("name", "")
            if field_name in ["related_invoice_id", "invoice_id"]:
                product["discovery"]["cross_domain_relationships"].append({
                    "field": field_name,
                    "target_domains": ["contas-a-pagar", "contas-a-receber", "logistica"],
                    "relationship_type": "reference"
                })
        
        # Adicionar ao catálogo
        self.catalog["products"].append(product)
        
        # Atualizar domínios
        domain = product["domain"]
        if domain not in self.catalog["domains"]:
            self.catalog["domains"][domain] = {
                "domain_name": domain,
                "total_products": 0,
                "total_consumers": 0,
                "products": []
            }
        
        self.catalog["domains"][domain]["total_products"] += 1
        self.catalog["domains"][domain]["products"].append(product["name"])
        
        # Atualizar consumidores
        for consumer in product["consumers"]:
            self.catalog["domains"][domain]["total_consumers"] += 1
        
        # Atualizar índices de busca
        self.update_search_indices(product)
        
        # Atualizar metadata
        self.catalog["catalog_metadata"]["total_products"] = len(self.catalog["products"])
        self.catalog["catalog_metadata"]["domains"] = list(self.catalog["domains"].keys())
        self.catalog["catalog_metadata"]["last_updated"] = datetime.now(timezone.utc).isoformat()
    
    def update_search_indices(self, product: Dict) -> None:
        """Atualiza índices de busca para descoberta rápida"""
        
        # Índice por domínio
        domain = product["domain"]
        if domain not in self.catalog["search_indices"]["by_domain"]:
            self.catalog["search_indices"]["by_domain"][domain] = []
        self.catalog["search_indices"]["by_domain"][domain].append(product["product_id"])
        
        # Índice por tags
        for tag in product.get("tags", []):
            if tag not in self.catalog["search_indices"]["by_tags"]:
                self.catalog["search_indices"]["by_tags"][tag] = []
            self.catalog["search_indices"]["by_tags"][tag].append(product["product_id"])
        
        # Índice por campos
        for field in product.get("dataset_fields", []):
            field_name = field.get("name", "")
            if field_name not in self.catalog["search_indices"]["by_fields"]:
                self.catalog["search_indices"]["by_fields"][field_name] = []
            self.catalog["search_indices"]["by_fields"][field_name].append(product["product_id"])
        
        # Índice por consumidores
        for consumer in product.get("consumers", []):
            consumer_name = consumer.get("name", "")
            if consumer_name not in self.catalog["search_indices"]["by_consumers"]:
                self.catalog["search_indices"]["by_consumers"][consumer_name] = []
            self.catalog["search_indices"]["by_consumers"][consumer_name].append(product["product_id"])
    
    def search_products(self, query: str, search_type: str = "all") -> List[Dict]:
        """Busca produtos no catálogo"""
        results = []
        query_lower = query.lower()
        
        for product in self.catalog["products"]:
            match = False
            
            if search_type in ["all", "name"]:
                if query_lower in product["name"].lower():
                    match = True
            
            if search_type in ["all", "domain"] and not match:
                if query_lower in product["domain"].lower():
                    match = True
            
            if search_type in ["all", "tags"] and not match:
                for tag in product.get("tags", []):
                    if query_lower in tag.lower():
                        match = True
                        break
            
            if search_type in ["all", "description"] and not match:
                if query_lower in product["description"].lower():
                    match = True
            
            if match:
                results.append(product)
        
        return results
    
    def get_lineage_graph(self) -> Dict:
        """Gera grafo de lineage entre produtos"""
        lineage_graph = {
            "nodes": [],
            "edges": []
        }
        
        # Adicionar nós (produtos)
        for product in self.catalog["products"]:
            lineage_graph["nodes"].append({
                "id": product["product_id"],
                "name": product["name"],
                "domain": product["domain"],
                "type": "data_product"
            })
        
        # Adicionar arestas (relacionamentos)
        for product in self.catalog["products"]:
            for relationship in product["discovery"]["cross_domain_relationships"]:
                target_field = relationship["field"]
                for target_domain in relationship["target_domains"]:
                    # Encontrar produtos no domínio alvo que têm o campo correspondente
                    for target_product in self.catalog["products"]:
                        if target_product["domain"] == target_domain:
                            for field in target_product.get("dataset_fields", []):
                                if field.get("name", "") == target_field:
                                    lineage_graph["edges"].append({
                                        "source": product["product_id"],
                                        "target": target_product["product_id"],
                                        "relationship": relationship["relationship_type"],
                                        "field": target_field
                                    })
        
        return lineage_graph
    
    def build_from_contracts(self, contracts_dir: str = ".") -> None:
        """Constrói catálogo a partir dos contratos"""
        print("🔍 Construindo catálogo de produtos de dados...")
        
        contracts = [
            "domains/financeiro/contas-a-pagar/dataproduct.yaml",
            "domains/financeiro/contas-a-receber/dataproduct.yaml",
            "domains/logistica/dataproduct.yaml"
        ]
        
        for contract_file in contracts:
            contract_path = os.path.join(contracts_dir, contract_file)
            if os.path.exists(contract_path):
                self.add_product_from_contract(contract_path)
                print(f"✅ Produto adicionado: {contract_file}")
            else:
                print(f"⚠️ Contrato não encontrado: {contract_path}")
        
        self.generate_catalog_report()
    
    def generate_catalog_report(self) -> None:
        """Gera relatório do catálogo"""
        print(f"\n📚 Data Products Catalog")
        print("=" * 50)
        print(f"📦 Total produtos: {self.catalog['catalog_metadata']['total_products']}")
        print(f"🏢 Domínios: {', '.join(self.catalog['catalog_metadata']['domains'])}")
        
        print(f"\n📊 Produtos por domínio:")
        for domain, info in self.catalog["domains"].items():
            print(f"   • {domain}: {info['total_products']} produtos, {info['total_consumers']} consumidores")
        
        print(f"\n🔍 Campos de lineage cross-domain:")
        all_lineage_fields = set()
        for product in self.catalog["products"]:
            all_lineage_fields.update(product["discovery"]["lineage_fields"])
        
        for field in sorted(all_lineage_fields):
            products_with_field = [p["name"] for p in self.catalog["products"] if field in p["discovery"]["lineage_fields"]]
            print(f"   • {field}: {', '.join(products_with_field)}")
    
    def save_catalog(self, output_path: str = "reports/data_products_catalog.json") -> None:
        """Salva catálogo em arquivo JSON"""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.catalog, f, ensure_ascii=False, indent=2)
        
        print(f"\n📄 Catálogo completo em: {output_path}")
    
    def get_search_examples(self) -> None:
        """Exemplos de busca no catálogo"""
        print(f"\n🔍 Exemplos de busca no catálogo:")
        
        # Buscar por domínio financeiro
        financial_products = self.search_products("financeiro", "domain")
        print(f"💰 Produtos financeiros: {[p['name'] for p in financial_products]}")
        
        # Buscar produtos com invoice_id
        invoice_products = []
        for product in self.catalog["products"]:
            for field in product.get("dataset_fields", []):
                if field.get("name", "") == "invoice_id":
                    invoice_products.append(product["name"])
                    break
        print(f"📋 Produtos com invoice_id: {invoice_products}")
        
        # Buscar produtos com source_event
        source_event_products = []
        for product in self.catalog["products"]:
            if "source_event_id" in product["discovery"]["lineage_fields"]:
                source_event_products.append(product["name"])
        print(f"🔗 Produtos com source_event: {source_event_products}")
        
        # Exibir lineage de um produto
        if self.catalog["products"]:
            first_product = self.catalog["products"][0]
            print(f"\n🔗 Lineage de {first_product['name']}:")
            print(f"   • Campos de lineage: {first_product['discovery']['lineage_fields']}")
            print(f"   • Produtos relacionados: {first_product['discovery']['cross_domain_relationships']}")

def main():
    """Função principal"""
    catalog = DataCatalog()
    catalog.build_from_contracts()
    
    # Salvar catálogo
    catalog.save_catalog()
    
    # Exemplos de busca
    catalog.get_search_examples()

if __name__ == "__main__":
    main()
