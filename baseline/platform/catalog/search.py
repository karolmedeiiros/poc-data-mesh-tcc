#!/usr/bin/env python3
"""
Busca unificada no catálogo de produtos de dados
Uso: python3 platform/catalog/search.py [comando] [query]
"""

import json
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

def load_catalog():
    """Carrega catálogo existente"""
    try:
        with open("reports/data_products_catalog.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print("❌ Catálogo não encontrado. Execute primeiro:")
        print("   python3 platform/catalog/build_data_catalog.py")
        sys.exit(1)

def search_by_name(catalog, name):
    """Busca produtos por nome (parcial ou exato)"""
    results = []
    name_lower = name.lower()
    
    for product in catalog["products"]:
        if name_lower in product["name"].lower():
            results.append(product)
    
    if results:
        print(f"📝 Produtos com nome '{name}':")
        for product in results:
            print(f"   • {product['name']} (domínio: {product['domain']}, owner: {product['owner']})")
        return results
    else:
        print(f"❌ Nenhum produto encontrado com nome '{name}'")
        return []

def search_by_tag(catalog, tag):
    """Busca produtos por tag"""
    products = catalog["search_indices"]["by_tags"].get(tag, [])
    if products:
        print(f"🏷️ Produtos com tag '{tag}': {', '.join(products)}")
        return products
    else:
        print(f"❌ Nenhum produto encontrado com tag '{tag}'")
        return []

def search_by_domain(catalog, domain):
    """Busca produtos por domínio"""
    products = catalog["search_indices"]["by_domain"].get(domain, [])
    if products:
        print(f"📂 Produtos do domínio '{domain}': {', '.join(products)}")
        return products
    else:
        print(f"❌ Nenhum produto encontrado no domínio '{domain}'")
        return []

def search_by_owner(catalog, owner):
    """Busca produtos por proprietário"""
    results = []
    owner_lower = owner.lower()
    
    for product in catalog["products"]:
        if owner_lower in product["owner"].lower():
            results.append(product)
    
    if results:
        print(f"👤 Produtos do proprietário '{owner}':")
        for product in results:
            print(f"   • {product['name']} (domínio: {product['domain']}, owner: {product['owner']})")
        return results
    else:
        print(f"❌ Nenhum produto encontrado do proprietário '{owner}'")
        return []

def search_by_field(catalog, field):
    """Busca produtos por campo"""
    products = catalog["search_indices"]["by_fields"].get(field, [])
    if products:
        print(f"🔧 Produtos com campo '{field}': {', '.join(products)}")
        return products
    else:
        print(f"❌ Nenhum produto encontrado com campo '{field}'")
        return []

def search_by_consumer(catalog, consumer):
    """Busca produtos por consumidor"""
    products = catalog["search_indices"]["by_consumers"].get(consumer, [])
    if products:
        print(f"👥 Produtos consumidos por '{consumer}': {', '.join(products)}")
        return products
    else:
        print(f"❌ Nenhum produto encontrado consumido por '{consumer}'")
        return []

def search_dependencies(catalog, product_name):
    """Busca dependências de um produto (consumidores e relacionamentos)"""
    product_found = None
    for product in catalog["products"]:
        if product["name"] == product_name:
            product_found = product
            break
    
    if not product_found:
        print(f"❌ Produto '{product_name}' não encontrado")
        return []
    
    print(f"🔗 Dependências do produto '{product_name}':")
    
    # Consumidores
    consumers = product_found.get("consumers", [])
    if consumers:
        print(f"\n👥 Consumidores ({len(consumers)}):")
        for consumer in consumers:
            print(f"   • {consumer['name']} (versão: {consumer['version']}, contato: {consumer['contact']})")
    else:
        print(f"\n👥 Consumidores: Nenhum")
    
    # Relacionamentos cross-domain
    relationships = product_found.get("discovery", {}).get("cross_domain_relationships", [])
    if relationships:
        print(f"\n🌐 Relacionamentos Cross-Domain ({len(relationships)}):")
        for rel in relationships:
            print(f"   • Campo '{rel['field']}' -> {', '.join(rel['target_domains'])} ({rel['relationship_type']})")
    else:
        print(f"\n🌐 Relacionamentos Cross-Domain: Nenhum")
    
    # Lineage fields
    lineage_fields = product_found.get("discovery", {}).get("lineage_fields", [])
    if lineage_fields:
        print(f"\n📊 Campos de Lineage ({len(lineage_fields)}): {', '.join(lineage_fields)}")
    else:
        print(f"\n📊 Campos de Lineage: Nenhum")
    
    return [product_found]

def show_all(catalog):
    """Mostra todas as opções de busca disponíveis"""
    print("🔍 Catálogo de Produtos de Dados - Busca Disponível")
    print("=" * 60)
    
    print("\n📂 Domínios:")
    for domain in catalog["search_indices"]["by_domain"].keys():
        products = catalog["search_indices"]["by_domain"][domain]
        print(f"   • {domain}: {', '.join(products)}")
    
    print("\n🏷️ Tags:")
    for tag in catalog["search_indices"]["by_tags"].keys():
        products = catalog["search_indices"]["by_tags"][tag]
        print(f"   • {tag}: {', '.join(products)}")
    
    print("\n👥 Consumidores:")
    for consumer in catalog["search_indices"]["by_consumers"].keys():
        products = catalog["search_indices"]["by_consumers"][consumer]
        print(f"   • {consumer}: {', '.join(products)}")
    
    print("\n🔗 Lineage Cross-Domain:")
    lineage_fields = set()
    for product in catalog["products"]:
        lineage_fields.update(product["discovery"]["lineage_fields"])
    
    for field in sorted(lineage_fields):
        products_with_field = [p["name"] for p in catalog["products"] if field in p["discovery"]["lineage_fields"]]
        print(f"   • {field}: {', '.join(products_with_field)}")

def show_examples(catalog):
    """Mostra exemplos de busca comuns"""
    print("🔍 Exemplos de Busca no Catálogo")
    print("=" * 50)
    
    # Exemplos práticos
    print("\n📋 Produtos com Master Entity invoice_id:")
    invoice_products = catalog["search_indices"]["by_fields"].get("invoice_id", [])
    print(f"   • {', '.join(invoice_products)}")
    
    print("\n🔄 Produtos para Reconciliação Cross-Domain:")
    reconciliation_products = catalog["search_indices"]["by_consumers"].get("cross-domain-reconciliation", [])
    print(f"   • {', '.join(reconciliation_products)}")
    
    print("\n💰 Produtos Financeiros:")
    financial_products = catalog["search_indices"]["by_tags"].get("finance", [])
    print(f"   • {', '.join(financial_products)}")
    
    print("\n� Produtos de Logística:")
    logistics_products = catalog["search_indices"]["by_tags"].get("logistics", [])
    print(f"   • {', '.join(logistics_products)}")

def show_help():
    """Mostra ajuda"""
    print("🔍 Busca no Catálogo de Produtos de Dados")
    print("=" * 50)
    print()
    print("Uso:")
    print("  python3 platform/catalog/search.py [comando] [query]")
    print()
    print("Comandos de busca:")
    print("  name [nome]           - Busca por nome (parcial ou exato)")
    print("  tag [tag_name]        - Busca por tag (ex: tag invoice)")
    print("  domain [domain_name]   - Busca por domínio (ex: domain financeiro)")
    print("  owner [owner]         - Busca por proprietário (ex: owner finance)")
    print("  field [field_name]     - Busca por campo (ex: field invoice_id)")
    print("  consumer [consumer]    - Busca por consumidor (ex: consumer cross-domain-reconciliation)")
    print("  deps [product_name]    - Mostra dependências do produto (consumidores, relacionamentos)")
    print()
    print("Comandos de visualização:")
    print("  all                    - Mostra todas as opções disponíveis")
    print("  examples               - Mostra exemplos de busca comuns")
    print("  help                   - Mostra esta ajuda")
    print()
    print("Exemplos:")
    print("  python3 platform/catalog/search.py name contas")
    print("  python3 platform/catalog/search.py tag invoice")
    print("  python3 platform/catalog/search.py domain financeiro")
    print("  python3 platform/catalog/search.py owner finance")
    print("  python3 platform/catalog/search.py field invoice_id")
    print("  python3 platform/catalog/search.py consumer cross-domain-reconciliation")
    print("  python3 platform/catalog/search.py deps contas-a-pagar")
    print("  python3 platform/catalog/search.py all")
    print("  python3 platform/catalog/search.py examples")

def main():
    """Função principal"""
    if len(sys.argv) < 2:
        show_help()
        return
    
    catalog = load_catalog()
    command = sys.argv[1].lower()
    
    if command == "help":
        show_help()
    elif command == "all":
        show_all(catalog)
    elif command == "examples":
        show_examples(catalog)
    elif len(sys.argv) < 3:
        print("❌ É necessário fornecer um termo para busca")
        print(f"   Uso: python3 {sys.argv[0]} {command} [query]")
        print("   Use 'help' para ver os comandos disponíveis")
    else:
        query = sys.argv[2]
        
        if command == "name":
            search_by_name(catalog, query)
        elif command == "tag":
            search_by_tag(catalog, query)
        elif command == "domain":
            search_by_domain(catalog, query)
        elif command == "owner":
            search_by_owner(catalog, query)
        elif command == "field":
            search_by_field(catalog, query)
        elif command == "consumer":
            search_by_consumer(catalog, query)
        elif command == "deps":
            search_dependencies(catalog, query)
        else:
            print(f"❌ Comando desconhecido: {command}")
            print("   Use 'help' para ver os comandos disponíveis")

if __name__ == "__main__":
    main()
