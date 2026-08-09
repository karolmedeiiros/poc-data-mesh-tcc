"""Gera os output ports (datasets publicados) de cada produto de dados.

Padrão Data Mesh (datamesh-architecture.com):
- Entrada: dados operacionais brutos em `operational/<domain>/<product>/*.jsonl`
- Saída : output port entity em `<domain>/<product>/data/*.jsonl`

Cada produto transforma seus próprios dados operacionais conforme as regras do
domínio (ETL descentralizado), publicando uma linha por `invoice_id` para
permitir reconciliação fatura-a-fatura entre produtos — sem depender de
transformações centrais (autonomia + governança federativa).

As regras de negócio de cada domínio (retenção de impostos no AP, descontos/juros
no AR, cálculo de valores na Logística e o vocabulário de status) são aplicadas
AQUI, na transformação analítica. A camada operacional guarda apenas o evento
bruto compartilhado (base_amount, base_status), servindo como base de dados única.
"""

import json
import os
import random
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

# Semente fixa para reprodutibilidade das regras estocásticas de domínio.
random.seed(7)


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: str, rows: Iterable[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def month_of(date_str: str) -> str:
    """Extrai YYYY-MM de uma data ISO (date ou datetime)."""
    if not date_str:
        return "unknown"
    return date_str[:7]


# ----------------------------------------------------------------------------
# Regras de negócio por domínio (aplicadas na camada analítica).
# Cada função recebe o evento bruto (base_amount/base_status) e devolve o valor
# ou status já no vocabulário do domínio. As divergências entre produtos são,
# portanto, geradas AQUI — a camada operacional permanece uma base única.
# ----------------------------------------------------------------------------

def calcula_valor_liquido_ap(base_amount: float, invoice_type: str) -> float:
    """Regra de negócio AP: retenção de impostos e taxa administrativa."""
    # Regra 1: Retenção de ISS/PIS/COFINS em serviços de alto valor (> R$3000)
    if invoice_type == "servico" and base_amount > 3000:
        tax_rate = 0.1475  # 14.75% total
        return round(base_amount * (1 - tax_rate), 2)
    # Regra 2: Aluguel com taxa administrativa eventual (0.2% em 30% dos casos)
    if invoice_type == "aluguel" and random.random() < 0.30:
        return round(base_amount * 1.002, 2)
    # Demais tipos preservam o valor base
    return round(base_amount, 2)


def calcula_valor_bruto_ar(base_amount: float, customer_type: str) -> float:
    """Regra de negócio AR: desconto de pontualidade e juros por atraso."""
    # Regra 1: Cliente corporate pode receber desconto de 2% (8% dos casos)
    if customer_type == "corporate" and random.random() < 0.08:
        return round(base_amount * 0.98, 2)
    # Regra 2: Cliente government pode sofrer juros de 1% (10% dos casos)
    if customer_type == "government" and random.random() < 0.10:
        return round(base_amount * 1.01, 2)
    # Cliente b2c e demais preservam o valor base
    return round(base_amount, 2)


def status_financeiro(base_status: str) -> str:
    """Vocabulário de status padronizado do domínio financeiro (AP e AR).

    O domínio financeiro é o dono de contas-a-pagar e contas-a-receber e
    governa UM único vocabulário para ambos os produtos — por isso não há
    divergência de vocabulário intra-domínio. Divergências de vocabulário
    ocorrem apenas ENTRE domínios (ex.: financeiro vs logística).
    """
    return {
        "paid": "PAGO",
        "cancelled": "CANCELADO",
        "open": "ABERTO",
    }.get(base_status, "ABERTO")


def status_logistics(base_status: str) -> str:
    """Vocabulário de status do domínio Logística (em português)."""
    return {
        "pending": "PENDENTE",
        "processing": "EM_PROCESSAMENTO",
        "completed": "CONCLUIDO",
        "cancelled": "CANCELADO",
    }.get(base_status, "PENDENTE")


# ----------------------------------------------------------------------------
# entity output ports (chave compartilhada `invoice_id`).
# Cada domínio publica UMA linha por fatura/operação ligada à fatura,
# mantendo seu próprio vocabulário e regras de cálculo. Permite reconciliação
# fatura-a-fatura entre produtos sob a master_entity `invoice` da política
# federada — preservando, por desenho, divergências de domínio.
# ----------------------------------------------------------------------------

def ap(operational: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    generated_at = now_iso()
    out: List[Dict[str, Any]] = []
    for row in operational:
        invoice_id = row.get("invoice_id")
        if not invoice_id:
            continue
        base_amount = float(row.get("base_amount", 0) or 0)
        invoice_type = row.get("invoice_type")
        out.append({
            "invoice_id": invoice_id,
            "mes_emissao": month_of(row.get("issue_date", "")),
            "status": status_financeiro(row.get("base_status")),
            "tipo_fatura": invoice_type,
            "id_fornecedor": row.get("supplier_id"),
            "valor_liquido": calcula_valor_liquido_ap(base_amount, invoice_type),
            "valor_base": base_amount,
            "dsc_moeda": row.get("currency", "BRL"),
            "dsc_dominio": "financeiro",
            "dsc_produto": "contas-a-pagar",
            "dt_versao": generated_at,
        })
    return out


def ar(operational: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    generated_at = now_iso()
    out: List[Dict[str, Any]] = []
    for row in operational:
        invoice_id = row.get("invoice_id")
        if not invoice_id:
            continue
        base_amount = float(row.get("base_amount", 0) or 0)
        customer_type = row.get("customer_type")
        out.append({
            "invoice_id": invoice_id,
            "mes_emissao": month_of(row.get("issue_date", "")),
            "status": status_financeiro(row.get("base_status")),
            "tipo_cliente": customer_type,
            "id_cliente": row.get("customer_id"),
            "valor_bruto": calcula_valor_bruto_ar(base_amount, customer_type),
            "valor_base": base_amount,
            "dsc_moeda": row.get("currency", "BRL"),
            "dsc_dominio": "financeiro",
            "dsc_produto": "contas-a-receber",
            "dt_versao": generated_at,
        })
    return out


# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║ INÍCIO — ATRIBUTOS DE DESTINO (dsc_cidade, dsc_uf) no output port         ║
# ║                                                                           ║
# ║ Bloco autocontido. Para desativar, troque a constante para False: o       ║
# ║ output port volta a ser publicado exatamente como antes.                  ║
# ║                                                                           ║
# ║ O grão do produto é a fatura, e uma fatura agrega N operações que podem   ║
# ║ ter destinos distintos. Como o contrato declara os dois atributos como    ║
# ║ string (não array), publica-se o destino predominante da fatura, com      ║
# ║ desempate alfabético para que a saída seja determinística.                ║
# ║                                                                           ║
# ║ A origem dos dados está em platform/generators/generate_logistics.py,     ║
# ║ sob marcação equivalente. Se lá o bloco estiver desativado, os atributos  ║
# ║ não existem no operacional e aqui são simplesmente omitidos.              ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
INCLUIR_DESTINO = False


def _acumular_destino(bucket: Dict[str, Any], row: Dict[str, Any]) -> None:
    """Registra o par (cidade, UF) da operação no bucket da fatura."""
    if not INCLUIR_DESTINO:
        return
    cidade, uf = row.get("dsc_cidade"), row.get("dsc_uf")
    if cidade and uf:
        bucket["destinos"][(cidade, uf)] = bucket["destinos"].get((cidade, uf), 0) + 1


def _destino_predominante(bucket: Dict[str, Any]) -> Dict[str, str]:
    """Destino mais frequente da fatura; vazio se o bloco estiver desativado."""
    if not INCLUIR_DESTINO or not bucket.get("destinos"):
        return {}
    # Maior contagem primeiro; empate resolvido em ordem alfabética.
    (cidade, uf), _ = sorted(bucket["destinos"].items(),
                             key=lambda kv: (-kv[1], kv[0]))[0]
    return {"dsc_cidade": cidade, "dsc_uf": uf}

# ╚═══════════════════ FIM — ATRIBUTOS DE DESTINO ════════════════════════════╝


def logistics(operational: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Logística agrupa por invoice_id (uma fatura pode ter N operações).

    Cada operação logística decompõe o seu valor total em:
    - valor_base (custo do item/serviço)
    - valor_frete
    - valor_seguro
    - valor_imposto
    Garantindo que: valor_total = valor_base + valor_frete + valor_seguro + valor_imposto.
    """
    generated_at = now_iso()
    buckets: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "operation_count": 0,
        "valor_base": 0.0,
        "valor_frete": 0.0,
        "valor_seguro": 0.0,
        "valor_imposto": 0.0,
        "operation_types": set(),
        "statuses": set(),
        "operation_months": set(),
        # ── INÍCIO — ATRIBUTOS DE DESTINO ───────────────────────────────────
        # Contagem por par (cidade, UF). Fica vazio quando o bloco está
        # desativado ou quando o operacional não traz os atributos.
        "destinos": {},
        # ── FIM — ATRIBUTOS DE DESTINO ─────────────────────────────────────
    })
    for row in operational:
        invoice_id = row.get("related_invoice_id")
        if not invoice_id:
            continue
        b = buckets[invoice_id]
        b["operation_count"] += 1
        # Cálculo do valor bruto da operação
        quantity = float(row.get("quantity", 0) or 0)
        unit_price = float(row.get("unit_price", 0) or 0)
        line_total = round(quantity * unit_price, 2)

        # Decomposição do valor total em componentes (regras de negócio Logística)
        base = round(line_total * 0.70, 2)
        freight = round(line_total * 0.15, 2)
        insurance = round(line_total * 0.05, 2)
        # Imposto é o residual para garantir soma exata
        tax = round(line_total - base - freight - insurance, 2)

        b["valor_base"] += base
        b["valor_frete"] += freight
        b["valor_seguro"] += insurance
        b["valor_imposto"] += tax

        b["operation_types"].add(row.get("operation_type", ""))
        b["statuses"].add(status_logistics(row.get("base_status", "")))
        op_date = row.get("operation_date") or row.get("updated_at", "")
        b["operation_months"].add(month_of(op_date))
        # ── INÍCIO — ATRIBUTOS DE DESTINO ───────────────────────────────────
        _acumular_destino(b, row)
        # ── FIM — ATRIBUTOS DE DESTINO ─────────────────────────────────────

    out: List[Dict[str, Any]] = []
    for invoice_id, b in sorted(buckets.items()):
        valor_base = round(b["valor_base"], 2)
        valor_frete = round(b["valor_frete"], 2)
        valor_seguro = round(b["valor_seguro"], 2)
        valor_imposto = round(b["valor_imposto"], 2)
        valor_total = round(valor_base + valor_frete + valor_seguro + valor_imposto, 2)
        out.append({
            "invoice_id": invoice_id,
            "qtd_operacoes": b["operation_count"],
            "valor_base": valor_base,
            "valor_frete": valor_frete,
            "valor_seguro": valor_seguro,
            "valor_imposto": valor_imposto,
            "valor_total": valor_total,
            "dsc_tipo_operacao": sorted(b["operation_types"]),
            "status": sorted(b["statuses"]),
            "meses_operacao": sorted(b["operation_months"]),
            "dsc_moeda": "BRL",
            # ── INÍCIO — ATRIBUTOS DE DESTINO (dsc_cidade, dsc_uf) ──────────
            # Desativar em INCLUIR_DESTINO, no topo da seção. Com o bloco
            # desligado, _destino_predominante() devolve {} e o registro
            # publicado fica idêntico ao original.
            **_destino_predominante(b),
            # ── FIM — ATRIBUTOS DE DESTINO ─────────────────────────────────
            "dsc_dominio": "logistica",
            "dsc_produto": "operacoes-logistica",
            "dt_versao": generated_at,
        })
    return out


PRODUCTS = [
    {
        "name": "contas-a-pagar",
        "operational": "operational/financeiro/contas-a-pagar/ap_natural.jsonl",
        "keyed": "domains/financeiro/contas-a-pagar/data/contas_a_pagar.jsonl",
        "keyed_builder": ap,
    },
    {
        "name": "contas-a-receber",
        "operational": "operational/financeiro/contas-a-receber/ar_natural.jsonl",
        "keyed": "domains/financeiro/contas-a-receber/data/contas_a_receber.jsonl",
        "keyed_builder": ar,
    },
    {
        "name": "operacoes-logistica",
        "operational": "operational/logistica/logistics_natural.jsonl",
        "keyed": "domains/logistica/data/logistics.jsonl",
        "keyed_builder": logistics,
    },
]


def main() -> None:
    print("Gerando output ports analíticos a partir dos dados operacionais...")
    for product in PRODUCTS:
        operational = read_jsonl(product["operational"])
        if not operational:
            print(f"  ! {product['name']}: operacional vazio em {product['operational']}")
            continue

        keyed = product["keyed_builder"](operational)
        write_jsonl(product["keyed"], keyed)

        print(
            f"  - {product['name']}: {len(operational)} operacionais "
            f"-> {len(keyed)} entity ({product['keyed']})"
        )


if __name__ == "__main__":
    main()
