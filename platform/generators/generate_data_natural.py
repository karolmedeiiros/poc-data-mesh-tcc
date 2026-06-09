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
    """Data Product: Contas a Pagar (Domain: contas-a-pagar)"""
    
    def __init__(self):
        self.domain = "contas-a-pagar"
        self.product_name = "contas-a-pagar"
        
    def calculate_amount(self, base_amount: float, invoice_type: str) -> float:
        """Regras de negócio do domínio AP"""
        
        # Regra 1: Retenção de impostos na fonte para serviços de alto valor
        if invoice_type == "servico" and base_amount > 3000:
            # AP retém ISS/PIS/COFINS apenas acima de R$3000
            tax_rate = 0.1475  # 14.75% total
            return round(base_amount * (1 - tax_rate), 2)
        
        # Regra 2: Material de escritório sem retenção
        elif invoice_type == "material":
            return round(base_amount, 2)
        
        # Regra 3: Aluguel com taxa administrativa eventual
        elif invoice_type == "aluguel" and random.random() < 0.30:
            # AP inclui taxa administrativa de 0.2%
            admin_fee = base_amount * 0.002
            return round(base_amount + admin_fee, 2)
        
        return round(base_amount, 2)
    
    def determine_status(self, base_status: str, payment_terms: str) -> str:
        """Regras de status do domínio AP"""
        
        if base_status == "paid":
            return "PAID"  # AP usa "PAID"
        elif base_status == "cancelled":
            return "CANCELED"
        else:
            return "OPEN"

    def generate_invoice(self, invoice_id: str, base_data: dict) -> dict:
        """Gera invoice segundo regras do produto AP"""
        
        # Tipos de invoice do domínio AP
        invoice_types = ["fornecedor", "servico", "material", "aluguel", "imposto"]
        invoice_type = random.choice(invoice_types)
        
        # Aplica regras de negócio do domínio (cada domínio usa seu vocabulário)
        amount = self.calculate_amount(base_data["base_amount"], invoice_type)
        status = self.determine_status(base_data["base_status"], "standard")
        
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
            "amount": amount,
            "base_amount": base_data["base_amount"],
            "issue_date": iso_d(base_data["issue_date"]),
            "due_date": iso_d(base_data["due_date"]),
            "status": status,
            "updated_at": iso_dt(ap_updated),
            "domain": self.domain,
            "product": self.product_name
        }

class AccountsReceivableProduct:
    """Data Product: Contas a Receber (Domain: contas-a-receber)"""
    
    def __init__(self):
        self.domain = "contas-a-receber"
        self.product_name = "contas-a-receber"
        
    def calculate_amount(self, base_amount: float, customer_type: str) -> float:
        """Regras de negócio do domínio AR"""
        
        # Regra 1: Clientes corporativos têm desconto de pontualidade
        if customer_type == "corporate":
            if random.random() < 0.08:  # 8% pagam em dia com desconto
                discount = base_amount * 0.02  # 2% de desconto
                return round(base_amount - discount, 2)
        
        # Regra 2: Clientes government têm juros por atraso
        elif customer_type == "government":
            if random.random() < 0.10:  # 10% aplica juros (raro)
                interest_rate = 0.01  # 1% de juros
                return round(base_amount * (1 + interest_rate), 2)
            else:
                return round(base_amount, 2)  # Sem juros na maioria
        
        # Regra 3: Cliente B2C sem alterações
        elif customer_type == "b2c":
            return round(base_amount, 2)
        
        return round(base_amount, 2)
    
    def determine_status(self, base_status: str, customer_type: str) -> str:
        """Regras de status do domínio AR"""
        
        if base_status == "paid":
            return "SETTLED"  # AR usa "SETTLED"
        elif base_status == "cancelled":
            return "CANCELED"
        else:
            return "OPEN"

    def generate_invoice(self, invoice_id: str, base_data: dict) -> dict:
        """Gera invoice segundo regras do produto AR"""
        
        # Tipos de cliente do domínio AR
        customer_types = ["corporate", "government", "b2c"]
        customer_type = random.choice(customer_types)
        
        # Aplica regras de negócio do domínio (cada domínio usa seu vocabulário)
        amount = self.calculate_amount(base_data["base_amount"], customer_type)
        status = self.determine_status(base_data["base_status"], customer_type)
        
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
            "gross_amount": amount,
            "base_amount": base_data["base_amount"],
            "issue_date": iso_d(base_data["issue_date"]),
            "due_date": iso_d(base_data["due_date"]),
            "status": status,
            "updated_at": iso_dt(ar_updated),
            "domain": self.domain,
            "product": self.product_name
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

    write_jsonl("domains/financeiro/contas-a-pagar/operational/ap_natural.jsonl", ap_rows)
    write_jsonl("domains/financeiro/contas-a-receber/operational/ar_natural.jsonl", ar_rows)

    print("Gerado (Data natural - regras naturais):")
    print(f"- domains/financeiro/contas-a-pagar/operational/ap_natural.jsonl (rows={len(ap_rows)})")
    print(f"- domains/financeiro/contas-a-receber/operational/ar_natural.jsonl (rows={len(ar_rows)})")

if __name__ == "__main__":
    main()