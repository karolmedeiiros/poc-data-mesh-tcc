import json
import os
import random
from datetime import datetime, timedelta, date, timezone
from decimal import Decimal, ROUND_HALF_UP

def iso_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def iso_d(d: date) -> str:
    return d.isoformat()

def write_jsonl(path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

def generate_source_event(event_id: str, base_issue: date) -> dict:
    """Evento de negócio bruto que ambos os produtos consomem."""
    issue = base_issue + timedelta(days=random.randint(0, 10))
    due = issue + timedelta(days=random.randint(10, 40))
    base_amount = round(random.uniform(100, 5000), 2)

    base_statuses = ["open", "paid", "cancelled"]
    base_status_weights = [0.70, 0.25, 0.05]
    base_status = random.choices(base_statuses, weights=base_status_weights, k=1)[0]

    return {
        "source_event_id": event_id,
        "source_system": "erp_finance",
        "issue_date": issue,
        "due_date": due,
        "base_amount": base_amount,
        "base_status": base_status,
    }

class AccountsPayableProduct:
    """Data Product: Contas a Pagar (Domain: contas-a-pagar).

    A camada operacional apenas registra o evento bruto (base_amount, base_status)
    e os atributos dimensionais do domínio (invoice_type, supplier_id). As regras
    de negócio (retenção de impostos, vocabulário de status) são aplicadas na
    transformação analítica (generate_data_analytical.py).
    """
    
    def __init__(self):
        self.domain = "contas-a-pagar"
        self.product_name = "contas-a-pagar"

    def generate_invoice(self, invoice_id: str, base_data: dict) -> dict:
        """Gera o registro operacional bruto do produto AP (sem regras de negócio)."""
        
        # Tipos de invoice do domínio AP (atributo dimensional, não é regra)
        invoice_types = ["fornecedor", "servico", "material", "aluguel", "imposto"]
        invoice_type = random.choice(invoice_types)
        
        # Timestamp do domínio AP (batch processing)
        now = datetime.now(timezone.utc)
        ap_updated = now - timedelta(minutes=random.randint(30, 180))
        
        return {
            "invoice_id": invoice_id,
            "source_event_id": base_data["source_event_id"],
            "source_system": base_data["source_system"],
            "processing_batch_id": f"AP-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
            "supplier_id": f"SUP-{random.randint(1, 50)}",
            "invoice_type": invoice_type,
            "currency": "BRL",
            "base_amount": base_data["base_amount"],
            "base_status": base_data["base_status"],
            "issue_date": iso_d(base_data["issue_date"]),
            "due_date": iso_d(base_data["due_date"]),
            "updated_at": iso_dt(ap_updated)
        }

class AccountsReceivableProduct:
    """Data Product: Contas a Receber (Domain: contas-a-receber).

    A camada operacional apenas registra o evento bruto (base_amount, base_status)
    e os atributos dimensionais do domínio (customer_type, customer_id). As regras
    de negócio (desconto de pontualidade, juros, vocabulário de status) são
    aplicadas na transformação analítica (generate_data_analytical.py).
    """
    
    def __init__(self):
        self.domain = "contas-a-receber"
        self.product_name = "contas-a-receber"

    def generate_invoice(self, invoice_id: str, base_data: dict) -> dict:
        """Gera o registro operacional bruto do produto AR (sem regras de negócio)."""
        
        # Tipos de cliente do domínio AR (atributo dimensional, não é regra)
        customer_types = ["corporate", "government", "b2c"]
        customer_type = random.choice(customer_types)
        
        # Timestamp do domínio AR (near real-time)
        now = datetime.now(timezone.utc)
        ar_updated = now - timedelta(minutes=random.randint(5, 45))
        
        return {
            "invoice_id": invoice_id,
            "source_event_id": base_data["source_event_id"],
            "source_system": base_data["source_system"],
            "processing_batch_id": f"AR-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
            "customer_id": f"CUS-{random.randint(1, 50)}",
            "customer_type": customer_type,
            "currency": "BRL",
            "base_amount": base_data["base_amount"],
            "base_status": base_data["base_status"],
            "issue_date": iso_d(base_data["issue_date"]),
            "due_date": iso_d(base_data["due_date"]),
            "updated_at": iso_dt(ar_updated)
        }

def main(seed: int = 7, n: int = 2000) -> None:
    """
    Gera dados seguindo regras Data natural - sem forçar divergências
    Cada domínio aplica suas regras de negócio naturalmente
    """
    random.seed(seed)

    # Inicializa produtos de dados (Data natural)
    ap_product = AccountsPayableProduct()
    ar_product = AccountsReceivableProduct()
    
    # Dados base compartilhados
    now = datetime.now(timezone.utc)
    base_issue = (now - timedelta(days=30)).date()

    ap_rows = []
    ar_rows = []

    for i in range(n):
        invoice_id = f"INV-{1000+i}"

        # Evento bruto compartilhado, depois cada produto aplica suas regras
        event_id = f"EVT-{1000+i}"
        base_data = generate_source_event(event_id, base_issue)
        
        # Cada produto gera seus dados segundo suas regras
        ap_invoice = ap_product.generate_invoice(invoice_id, base_data)
        ar_invoice = ar_product.generate_invoice(invoice_id, base_data)
        
        # Simula falhas naturais (sem forçar)
        if random.random() < 0.001:  # 0.1% falha natural AP
            ap_invoice = None
        
        if random.random() < 0.001:  # 0.1% falha natural AR
            ar_invoice = None
        
        # Adiciona se não houve falha
        if ap_invoice:
            ap_rows.append(ap_invoice)
        if ar_invoice:
            ar_rows.append(ar_invoice)

    write_jsonl("operational/financeiro/contas-a-pagar/ap_natural.jsonl", ap_rows)
    write_jsonl("operational/financeiro/contas-a-receber/ar_natural.jsonl", ar_rows)

    print("Gerado (Data natural - regras naturais):")
    print(f"- operational/financeiro/contas-a-pagar/ap_natural.jsonl (rows={len(ap_rows)})")
    print(f"- operational/financeiro/contas-a-receber/ar_natural.jsonl (rows={len(ar_rows)})")

if __name__ == "__main__":
    main()