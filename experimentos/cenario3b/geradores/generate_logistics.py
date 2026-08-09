import json
import os
import random
from datetime import datetime, timedelta, date, timezone
from decimal import Decimal, ROUND_HALF_UP

def iso_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def iso_d(d: date) -> str:
    return d.isoformat()

def read_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows

def write_jsonl(path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║ INÍCIO — ATRIBUTOS DE DESTINO (dsc_cidade, dsc_uf)                        ║
# ║                                                                           ║
# ║ Bloco autocontido. Para desativar, basta trocar a constante abaixo para   ║
# ║ False: os registros voltam a ser gerados exatamente como antes, sem os    ║
# ║ dois atributos, e nenhuma outra parte do script precisa ser alterada.     ║
# ║                                                                           ║
# ║ A contrapartida analítica está em platform/generators/                    ║
# ║ generate_data_analytical.py, sob marcação equivalente.                    ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
INCLUIR_DESTINO = True

# (cidade, UF) — destino da encomenda. Pares reais para que a UF seja sempre
# consistente com a cidade; sortear os dois campos de forma independente
# produziria combinações inválidas.
DESTINOS = [
    ("São Paulo", "SP"), ("Campinas", "SP"), ("Santos", "SP"),
    ("Rio de Janeiro", "RJ"), ("Niterói", "RJ"),
    ("Belo Horizonte", "MG"), ("Uberlândia", "MG"),
    ("Curitiba", "PR"), ("Porto Alegre", "RS"), ("Florianópolis", "SC"),
    ("Salvador", "BA"), ("Recife", "PE"), ("Fortaleza", "CE"),
    ("Goiânia", "GO"), ("Brasília", "DF"), ("Manaus", "AM"),
]


def atributos_de_destino() -> dict:
    """Retorna os atributos de destino, ou vazio quando o bloco está desativado."""
    if not INCLUIR_DESTINO:
        return {}
    cidade, uf = random.choice(DESTINOS)
    return {"dsc_cidade": cidade, "dsc_uf": uf}

# ╚═══════════════════ FIM — ATRIBUTOS DE DESTINO ════════════════════════════╝


def generate_source_event(event_id: str, base_issue: date) -> dict:
    """Evento de negócio bruto que pode ser consumido por múltiplos domínios."""
    issue = base_issue + timedelta(days=random.randint(0, 10))
    quantity = random.randint(1, 200)
    unit_price = round(random.uniform(5, 50), 2)
    
    # Tipos de operação base
    operation_types = ["recebimento", "envio", "devolucao", "transferencia"]
    operation_weights = [0.40, 0.35, 0.15, 0.10]
    operation_type = random.choices(operation_types, weights=operation_weights, k=1)[0]
    
    # Status base
    statuses = ["pending", "processing", "completed", "cancelled"]
    status_weights = [0.20, 0.25, 0.50, 0.05]
    base_status = random.choices(statuses, weights=status_weights, k=1)[0]

    return {
        "source_event_id": event_id,
        "source_system": "wms_system",
        "operation_date": issue,
        "operation_type": operation_type,
        "base_status": base_status,
        "quantity": quantity,
        "unit_price": unit_price,
    }


def coerce_status_to_invoice(op_status: str, invoice_status: str) -> str:
    """
    Mantém coerência de negócio entre a operação logística e a fatura de origem.

    Uma fatura cancelada não pode ter operação logística concluída: a conclusão
    afirma um fato (entrega realizada) incompatível com o cancelamento da
    obrigação financeira. Estados transitórios (`pending`, `processing`)
    permanecem admitidos, pois podem coexistir com um cancelamento ainda não
    propagado ao domínio Logístico.

    Esta restrição atua na GERAÇÃO dos dados sintéticos, não na arquitetura:
    seu objetivo é garantir que o estado de controle (baseline) seja
    internamente coerente, permitindo que combinações contraditórias sejam
    introduzidas deliberadamente nos cenários experimentais. Sem ela, a geração
    independente dos dois domínios produzia tais combinações já no baseline,
    impedindo atribuir qualquer observação à intervenção do experimento.
    """
    if invoice_status == "cancelled" and op_status == "completed":
        return "cancelled"
    return op_status

class LogisticsOperationsProduct:
    """Data Product: Operações Logísticas (Domain: Logística).

    A camada operacional apenas registra o evento bruto (quantity, unit_price,
    base_status) e os atributos dimensionais (operation_type, party_id). As regras
    de negócio (cálculo de total_value, custos adicionais, vocabulário de status)
    são aplicadas na transformação analítica (generate_data_analytical.py).
    """
    
    def __init__(self):
        self.domain = "logistica"
        self.product_name = "operacoes-logistica"

    def generate_operation(self, operation_id: str, base_data: dict,
                           related_invoice_id: str = None,
                           party_id: str = None, party_type: str = None) -> dict:
        """Gera o registro operacional bruto do produto Logística (sem regras de negócio)."""
        
        # Timestamp do domínio Logística
        now = datetime.now(timezone.utc)
        log_updated = now - timedelta(minutes=random.randint(15, 120))
        
        # IDs de partes (usa valores reais do AP/AR quando disponíveis)
        if party_id is None:
            if base_data["operation_type"] == "recebimento":
                party_id = f"SUP-{random.randint(1, 50)}"
                party_type = "supplier"
            elif base_data["operation_type"] == "envio":
                party_id = f"CUS-{random.randint(1, 50)}"
                party_type = "customer"
            else:
                party_id = f"WH-{random.randint(1, 10)}"
                party_type = "warehouse"
        
        # SKUs e produtos
        product_skus = ["SKU-1001", "SKU-1002", "SKU-1003", "SKU-2001", "SKU-2002", "SKU-3001"]
        product_descriptions = [
            "Material de escritório", "Equipamento de TI", "Insumos industriais",
            "Produtos de limpeza", "Componentes eletrônicos", "Embalagens"
        ]
        sku_idx = random.randint(0, len(product_skus) - 1)
        
        # Transportadoras (apenas para envios concluídos no evento base)
        carrier_id = None
        tracking_number = None
        if base_data["operation_type"] == "envio" and base_data["base_status"] == "completed":
            carrier_id = f"CAR-{random.randint(1, 10)}"
            tracking_number = f"TRK-{random.randint(100000, 999999)}"
        
        return {
            "operation_id": operation_id,
            "source_event_id": base_data["source_event_id"],
            "source_system": base_data["source_system"],
            "processing_batch_id": f"LOG-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
            "operation_type": base_data["operation_type"],
            "operation_date": iso_d(base_data["operation_date"]),
            "related_invoice_id": related_invoice_id,
            "party_id": party_id,
            "party_type": party_type,
            "product_sku": product_skus[sku_idx],
            "product_description": product_descriptions[sku_idx],
            "quantity": base_data["quantity"],
            "unit_price": base_data["unit_price"],
            "currency": "BRL",
            "warehouse_id": f"WH-{random.randint(1, 5)}",
            "base_status": base_data["base_status"],
            "carrier_id": carrier_id,
            "tracking_number": tracking_number,
            # ── INÍCIO — ATRIBUTOS DE DESTINO (dsc_cidade, dsc_uf) ──────────
            # Desativar em INCLUIR_DESTINO, no topo do arquivo. Com o bloco
            # desligado, atributos_de_destino() devolve {} e o dicionário fica
            # idêntico ao original.
            **atributos_de_destino(),
            # ── FIM — ATRIBUTOS DE DESTINO ─────────────────────────────────
            "updated_at": iso_dt(log_updated),
        }

def main(seed: int = 7, n_independent: int = 300) -> None:
    """
    Gera dados do domínio Logística seguindo regras naturais.
    
    Duas fontes de operações:
    1. Operações vinculadas a faturas reais do AP/AR (cross-domain)
    2. Operações independentes (transferências, devoluções sem fatura)
    """
    random.seed(seed)

    logistics_product = LogisticsOperationsProduct()
    now = datetime.now(timezone.utc)
    base_issue = (now - timedelta(days=30)).date()
    logistics_rows = []
    op_counter = 1000

    # --- Parte 1: Operações vinculadas a faturas reais ---
    ap_rows = read_jsonl("operational/financeiro/contas-a-pagar/ap_natural.jsonl") if os.path.exists("operational/financeiro/contas-a-pagar/ap_natural.jsonl") else []
    ar_rows = read_jsonl("operational/financeiro/contas-a-receber/ar_natural.jsonl") if os.path.exists("operational/financeiro/contas-a-receber/ar_natural.jsonl") else []

    # Recebimentos vinculados a ~30% das faturas AP
    ap_sample = random.sample(ap_rows, min(int(len(ap_rows) * 0.30), len(ap_rows)))
    for ap_invoice in ap_sample:
        operation_id = f"LOG-{op_counter}"
        op_counter += 1

        base_data = generate_source_event(f"EVT-LOG-{op_counter}", base_issue)
        base_data["operation_type"] = "recebimento"
        base_data["base_status"] = coerce_status_to_invoice(
            base_data["base_status"], ap_invoice.get("base_status")
        )

        operation = logistics_product.generate_operation(
            operation_id, base_data,
            related_invoice_id=ap_invoice["invoice_id"],
            party_id=ap_invoice["supplier_id"],
            party_type="supplier"
        )

        if random.random() < 0.002:
            operation = None
        if operation:
            logistics_rows.append(operation)

    # Envios vinculados a ~25% das faturas AR
    ar_sample = random.sample(ar_rows, min(int(len(ar_rows) * 0.25), len(ar_rows)))
    for ar_invoice in ar_sample:
        operation_id = f"LOG-{op_counter}"
        op_counter += 1

        base_data = generate_source_event(f"EVT-LOG-{op_counter}", base_issue)
        base_data["operation_type"] = "envio"
        base_data["base_status"] = coerce_status_to_invoice(
            base_data["base_status"], ar_invoice.get("base_status")
        )

        operation = logistics_product.generate_operation(
            operation_id, base_data,
            related_invoice_id=ar_invoice["invoice_id"],
            party_id=ar_invoice["customer_id"],
            party_type="customer"
        )

        if random.random() < 0.002:
            operation = None
        if operation:
            logistics_rows.append(operation)

    # --- Parte 2: Operações independentes (sem fatura) ---
    for i in range(n_independent):
        operation_id = f"LOG-{op_counter}"
        op_counter += 1

        event_id = f"EVT-LOG-{op_counter}"
        base_data = generate_source_event(event_id, base_issue)
        # Força tipos sem fatura
        base_data["operation_type"] = random.choice(["devolucao", "transferencia", "recebimento", "envio"])

        operation = logistics_product.generate_operation(operation_id, base_data)

        if random.random() < 0.002:
            operation = None
        if operation:
            logistics_rows.append(operation)

    random.shuffle(logistics_rows)
    write_jsonl("operational/logistica/logistics_natural.jsonl", logistics_rows)

    linked = sum(1 for r in logistics_rows if r.get("related_invoice_id"))
    print("Gerado (Logística - regras naturais):")
    print(f"- operational/logistica/logistics_natural.jsonl (rows={len(logistics_rows)})")
    print(f"- Operações vinculadas a faturas: {linked}")
    print(f"- Operações independentes: {len(logistics_rows) - linked}")

if __name__ == "__main__":
    main()
