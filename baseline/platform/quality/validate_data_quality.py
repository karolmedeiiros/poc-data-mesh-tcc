#!/usr/bin/env python3
"""
Validação runtime de qualidade de dados (Data Mesh Pattern).

As regras de qualidade vivem nos data contracts (`data_contract.yaml`), como
expressões declarativas:

    valor_liquido > 0
    dsc_moeda == 'BRL'
    status IN ['ABERTO','PAGO','CANCELADO']
    REGEXP_MATCH(invoice_id, '^INV-[0-9]+$')
    ANY(status, s => s IN ['PENDENTE','CONCLUIDO'])

Este módulo interpreta essas expressões e as aplica a cada registro. O contrato
é a fonte da verdade: adicionar ou alterar uma regra no YAML passa a valer sem
tocar neste arquivo.

Organização: cinco dimensões de qualidade (integridade, validade, unicidade,
atualidade e consistência) verificadas em três camadas — validação de esquema,
perfilamento estatístico e regras de negócio declaradas no contrato.

Autoteste embutido:
    python3 platform/quality/validate_data_quality.py --self-test

Histórico: a versão anterior comparava `rule_id` contra IDs hardcoded
(`ap-amount-positive`, `ap-currency-valid`…) que nunca casavam com os IDs reais
dos contratos (`ap-k-positive-amount`, `ap-k-currency-brl`…). Nenhum ramo
casava, toda regra caía no PASS default e o relatório mostrava 100% mesmo com
dados inválidos. O autoteste acima guarda contra a volta desse bug.
"""
import ast
import json
import os
import re
import sys
import yaml
from datetime import datetime, timezone
from typing import Dict, List, Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from odcs_adapter import load_and_normalize, load_odcs


# ═══════════════════════════════════════════════════════════════════════════
# Avaliação das expressões declaradas nos contratos
# ═══════════════════════════════════════════════════════════════════════════

def get_nested(d: Dict[str, Any], keys: List[str], default: Any = None) -> Any:
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


class RuleError(Exception):
    """Expressão malformada ou não suportada."""


class MissingField(Exception):
    """Campo referenciado pela regra não existe no registro."""

    def __init__(self, field: str):
        super().__init__(f"campo ausente no registro: '{field}'")
        self.field = field


_LAMBDA = re.compile(r"(\w+)\s*=>")


def _to_python(expr: str) -> str:
    """Converte a sintaxe do contrato para sintaxe Python."""
    out = _LAMBDA.sub(r"lambda \1:", expr.strip())   # `s => corpo` → `lambda s: corpo`
    out = re.sub(r"\bIN\b", "in", out)
    out = re.sub(r"\bAND\b", "and", out)
    out = re.sub(r"\bOR\b", "or", out)
    out = re.sub(r"\bNOT\b", "not", out)
    return out


def _regexp_match(value: Any, pattern: str) -> bool:
    return False if value is None else re.match(pattern, str(value)) is not None


def _any(seq: Any, pred) -> bool:
    if seq is None:
        return False
    return any(pred(i) for i in (seq if isinstance(seq, (list, tuple)) else [seq]))


def _all(seq: Any, pred) -> bool:
    if seq is None:
        return False
    return all(pred(i) for i in (seq if isinstance(seq, (list, tuple)) else [seq]))


FUNCTIONS = {
    "REGEXP_MATCH": _regexp_match,
    "ANY": _any,
    "ALL": _all,
    "IS_NULL": lambda v: v is None or v == "",
    "NOT_NULL": lambda v: v is not None and v != "",
    "LENGTH": lambda v: len(v) if v is not None else 0,
    "ABS": abs,
}

# Allowlist de nós de AST. Não usamos eval() sobre a string: a expressão é
# parseada e cada nó validado antes da avaliação, para que um YAML malicioso
# não vire execução de código arbitrário.
_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.UnaryOp, ast.BinOp, ast.Compare, ast.Call,
    ast.Name, ast.Load, ast.Constant, ast.List, ast.Tuple, ast.Set,
    ast.Lambda, ast.arguments, ast.arg, ast.IfExp,
    ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
)


def _check_safe(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise RuleError(f"construção não permitida: {type(node).__name__}")
        if isinstance(node, ast.Call) and not isinstance(node.func, ast.Name):
            raise RuleError("só chamadas a funções nomeadas são permitidas")


def _as_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class _Evaluator(ast.NodeVisitor):
    """Avalia o AST restrito contra um registro."""

    def __init__(self, record: Dict[str, Any]):
        self.record = record
        self.scope: Dict[str, Any] = {}

    def visit_Expression(self, node):
        return self.visit(node.body)

    def visit_Constant(self, node):
        return node.value

    def visit_List(self, node):
        return [self.visit(e) for e in node.elts]

    visit_Tuple = visit_List

    def visit_Set(self, node):
        return {self.visit(e) for e in node.elts}

    def visit_Name(self, node):
        name = node.id
        if name in self.scope:
            return self.scope[name]
        if name in FUNCTIONS:
            return FUNCTIONS[name]
        if name in ("True", "False", "None"):
            return {"True": True, "False": False, "None": None}[name]
        if name in self.record:
            return self.record[name]
        raise MissingField(name)

    def visit_Lambda(self, node):
        params = [a.arg for a in node.args.args]

        def fn(*args):
            saved = dict(self.scope)
            self.scope.update(dict(zip(params, args)))
            try:
                return self.visit(node.body)
            finally:
                self.scope = saved

        return fn

    def visit_Call(self, node):
        fname = node.func.id
        if fname not in FUNCTIONS:
            raise RuleError(f"função desconhecida: {fname}()")
        return FUNCTIONS[fname](*[self.visit(a) for a in node.args])

    def visit_UnaryOp(self, node):
        val = self.visit(node.operand)
        if isinstance(node.op, ast.Not):
            return not val
        return -val if isinstance(node.op, ast.USub) else +val

    def visit_BoolOp(self, node):
        vals = (self.visit(v) for v in node.values)
        return all(vals) if isinstance(node.op, ast.And) else any(vals)

    def visit_BinOp(self, node):
        left, right, op = self.visit(node.left), self.visit(node.right), node.op
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            return left / right
        if isinstance(op, ast.Mod):
            return left % right
        raise RuleError(f"operador não suportado: {type(op).__name__}")

    def visit_IfExp(self, node):
        return self.visit(node.body) if self.visit(node.test) else self.visit(node.orelse)

    def visit_Compare(self, node):
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            right = self.visit(comparator)
            if isinstance(op, ast.Eq):
                ok = left == right
            elif isinstance(op, ast.NotEq):
                ok = left != right
            elif isinstance(op, ast.In):
                ok = left in right
            elif isinstance(op, ast.NotIn):
                ok = left not in right
            else:
                # Comparações de ordem exigem números; None nunca satisfaz.
                ln, rn = _as_number(left), _as_number(right)
                if ln is None or rn is None:
                    return False
                if isinstance(op, ast.Lt):
                    ok = ln < rn
                elif isinstance(op, ast.LtE):
                    ok = ln <= rn
                elif isinstance(op, ast.Gt):
                    ok = ln > rn
                elif isinstance(op, ast.GtE):
                    ok = ln >= rn
                else:
                    raise RuleError(f"comparador não suportado: {type(op).__name__}")
            if not ok:
                return False
            left = right
        return True

    def generic_visit(self, node):
        raise RuleError(f"nó não suportado: {type(node).__name__}")


_AST_CACHE: Dict[str, ast.Expression] = {}


def evaluate(expression: str, record: Dict[str, Any]) -> bool:
    """
    Avalia a expressão do contrato contra o registro.

    Levanta RuleError se a expressão for inválida e MissingField se referenciar
    campo ausente — os dois são falhas reais que devem aparecer no relatório,
    não virar PASS silencioso.
    """
    tree = _AST_CACHE.get(expression)
    if tree is None:
        try:
            tree = ast.parse(_to_python(expression), mode="eval")
        except SyntaxError as exc:
            raise RuleError(f"expressão inválida {expression!r}: {exc}") from exc
        _check_safe(tree)
        _AST_CACHE[expression] = tree
    return bool(_Evaluator(record).visit(tree))


# ═══════════════════════════════════════════════════════════════════════════
# Dimensões de qualidade e camadas de verificação
#
# Dimensões:
#   integridade   — campos obrigatórios preenchidos; taxa de nulos
#   validade      — conformidade a formatos, tipos, intervalos e enumerações
#   unicidade     — ausência de duplicatas na chave primária
#   atualidade    — frescor dos dados em relação ao SLA federado
#   consistência  — coerência interna entre campos do mesmo registro
#
# Camadas:
#   1. Validação de esquema     — tipos, obrigatoriedade e enumerações
#   2. Perfilamento estatístico — nulos, cardinalidade, unicidade e atualidade
#   3. Regras de negócio        — expressões declaradas no contrato
# ═══════════════════════════════════════════════════════════════════════════

DIMENSOES = {
    "integridade": "Campos obrigatórios preenchidos",
    "validade": "Conformidade a formatos, tipos, intervalos e enumerações",
    "unicidade": "Ausência de duplicatas na chave primária",
    "atualidade": "Frescor dos dados em relação ao SLA federado",
    "consistencia": "Coerência interna entre campos do mesmo registro",
}

# Dimensão declarada no contrato (vocabulário ODCS) → dimensão interna.
DIMENSAO_ODCS = {
    "completeness": "integridade",
    "conformity": "validade",
    "validity": "validade",
    "uniqueness": "unicidade",
    "timeliness": "atualidade",
    "consistency": "consistencia",
}

# Tipos lógicos ODCS e os tipos Python aceitos.
TIPOS_ACEITOS = {
    "string": (str,), "integer": (int,), "number": (int, float),
    "boolean": (bool,), "array": (list,), "date": (str,), "timestamp": (str,),
}


def _duracao_iso_para_horas(valor: str) -> float:
    """Converte duração ISO-8601 simples (P1D, PT6H, P30D) em horas."""
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", str(valor or "").strip())
    if not m:
        raise ValueError(f"duração não suportada: {valor!r}")
    d, h, mi = (int(g) if g else 0 for g in m.groups())
    return d * 24 + h + mi / 60


class DataQualityValidator:
    """Validação runtime de qualidade de dados (Data Mesh Pattern)."""

    def __init__(self, contract_path: str, policies: Dict[str, Any] = None):
        self.contract = self.load_contract(contract_path)
        self.product_name = self.contract["metadata"]["name"]
        self.domain = self.contract["metadata"]["domain"]
        self.quality_rules = self.contract.get("spec", {}).get("quality", {}).get("rules", [])
        self.policies = policies or {}

        # Propriedades e dimensões vêm do contrato ODCS bruto: o adaptador
        # normaliza as regras mas não preserva `dimension` nem os tipos.
        odcs = load_odcs(contract_path)
        schema = (odcs.get("schema") or [{}])[0]
        self.properties = schema.get("properties", []) or []
        self.dimensao_por_regra = {
            r.get("name"): DIMENSAO_ODCS.get(r.get("dimension"), "validade")
            for r in (schema.get("quality") or [])
        }
        dataset = self.contract.get("spec", {}).get("dataset", {}) or {}
        self.primary_key = dataset.get("primaryKey") or []

    def load_contract(self, path: str) -> Dict:
        # Contrato no padrão ODCS v3 (Bitol), normalizado para a visão interna.
        return load_and_normalize(path)

    # ── Camada 1 — Validação de esquema ─────────────────────────────────

    def validar_esquema(self, records: List[Dict]) -> Dict[str, Any]:
        """Verifica obrigatoriedade, tipo e enumeração de cada atributo declarado."""
        violacoes = []
        total = len(records)

        for prop in self.properties:
            nome = prop.get("name")
            if not nome:
                continue
            tipo = prop.get("logicalType")
            aceitos = TIPOS_ACEITOS.get(tipo)
            enum = (prop.get("logicalTypeOptions") or {}).get("enum")
            ausentes = nulos = tipo_invalido = fora_enum = 0

            for r in records:
                if nome not in r:
                    ausentes += 1
                    continue
                v = r[nome]
                if v is None or v == "":
                    nulos += 1
                    continue
                if aceitos and not isinstance(v, aceitos):
                    tipo_invalido += 1
                if enum:
                    valores = v if isinstance(v, list) else [v]
                    if any(x not in enum for x in valores):
                        fora_enum += 1

            if prop.get("required") and (ausentes or nulos):
                violacoes.append({
                    "dimensao": "integridade", "tipo": "campo_obrigatorio_nao_preenchido",
                    "campo": nome, "ocorrencias": ausentes + nulos,
                    "mensagem": (f"Campo obrigatório '{nome}': {ausentes} ausente(s) e "
                                 f"{nulos} nulo(s) em {total} registros"),
                })
            if tipo_invalido:
                violacoes.append({
                    "dimensao": "validade", "tipo": "tipo_incompativel",
                    "campo": nome, "esperado": tipo, "ocorrencias": tipo_invalido,
                    "mensagem": (f"Campo '{nome}' com tipo distinto de '{tipo}' em "
                                 f"{tipo_invalido} registros"),
                })
            if fora_enum:
                violacoes.append({
                    "dimensao": "validade", "tipo": "valor_fora_da_enumeracao",
                    "campo": nome, "permitidos": enum, "ocorrencias": fora_enum,
                    "mensagem": (f"Campo '{nome}' com valor fora de {enum} em "
                                 f"{fora_enum} registros"),
                })

        declarados = {p.get("name") for p in self.properties}
        nao_declarados = sorted({k for r in records for k in r} - declarados)
        if nao_declarados:
            violacoes.append({
                "dimensao": "validade", "tipo": "campo_nao_declarado",
                "campos": nao_declarados, "ocorrencias": len(nao_declarados),
                "mensagem": (f"{len(nao_declarados)} atributo(s) publicado(s) sem "
                             f"declaração no contrato: {', '.join(nao_declarados)}"),
            })

        return {"camada": "validacao_de_esquema",
                "status": "FAIL" if violacoes else "PASS", "violacoes": violacoes}

    # ── Camada 2 — Perfilamento estatístico ─────────────────────────────

    def perfilar(self, records: List[Dict]) -> Dict[str, Any]:
        """Taxa de nulos, cardinalidade, unicidade da chave e atualidade."""
        total = len(records)
        violacoes = []
        perfil = {}

        for prop in self.properties:
            nome = prop.get("name")
            if not nome:
                continue
            valores = [r.get(nome) for r in records]
            nulos = sum(1 for v in valores if v is None or v == "")
            distintos = len({json.dumps(v, sort_keys=True) if isinstance(v, (list, dict)) else v
                             for v in valores})
            perfil[nome] = {
                "taxa_nulos": round(nulos / total * 100, 2) if total else 0.0,
                "cardinalidade": distintos,
                "cardinalidade_relativa": round(distintos / total, 4) if total else 0.0,
            }

        unicidade = {}
        for campo in self.primary_key:
            chaves = [r.get(campo) for r in records if r.get(campo) is not None]
            duplicatas = len(chaves) - len(set(chaves))
            unicidade[campo] = {"registros": len(chaves), "duplicatas": duplicatas}
            if duplicatas:
                vistos, repetidos = set(), set()
                for k in chaves:
                    (repetidos if k in vistos else vistos).add(k)
                violacoes.append({
                    "dimensao": "unicidade", "tipo": "chave_primaria_duplicada",
                    "campo": campo, "ocorrencias": duplicatas,
                    "exemplos": sorted(repetidos)[:10],
                    "mensagem": f"Chave primária '{campo}' com {duplicatas} duplicata(s)",
                })

        return {"camada": "perfilamento_estatistico",
                "status": "FAIL" if violacoes else "PASS",
                "perfil_por_atributo": perfil, "unicidade": unicidade,
                "atualidade": self._avaliar_atualidade(records),
                "violacoes": violacoes}

    def _avaliar_atualidade(self, records: List[Dict]) -> Dict[str, Any]:
        """
        Compara a materialização mais recente com o SLA de freshness federado.

        Reportada como métrica informacional, não como violação: a idade é
        medida contra o relógio do momento da execução, de modo que em um
        conjunto estático cresce indefinidamente. Classificá-la como falha
        tornaria o estado de controle dependente do instante da execução. Em
        operação contínua, com materialização periódica, o mesmo cálculo
        constituiria critério legítimo de conformidade.
        """
        limite = get_nested(self.policies, ["spec", "standards", "quality", "min_freshness"])
        marcas = [r.get("dt_versao") for r in records if r.get("dt_versao")]
        if not marcas:
            return {"avaliada": False, "motivo": "atributo dt_versao ausente"}
        if not limite:
            return {"avaliada": False, "motivo": "SLA de freshness não declarado na política"}
        mais_recente = max(marcas)
        try:
            ts = datetime.fromisoformat(str(mais_recente).replace("Z", "+00:00"))
            horas_limite = _duracao_iso_para_horas(limite)
        except ValueError as exc:
            return {"avaliada": False, "motivo": f"não avaliável: {exc}"}
        idade_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        return {
            "avaliada": True, "classificacao": "informacional",
            "materializacao_mais_recente": mais_recente,
            "idade_horas": round(idade_h, 2),
            "sla_freshness": limite, "sla_horas": horas_limite,
            "dentro_do_sla": idade_h <= horas_limite,
        }

    # ── Camada 3 — Regras de negócio declaradas no contrato ─────────────

    def validate_record(self, record: Dict) -> Dict[str, Any]:
        """Valida um único registro contra as regras de qualidade do contrato."""
        results = {
            "record_id": record.get("invoice_id", record.get("operation_id", "unknown")),
            "product": self.product_name, "domain": self.domain,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "validations": [], "overall_status": "PASS", "errors": 0, "warnings": 0,
        }
        for rule in self.quality_rules:
            v = self.apply_rule(record, rule)
            results["validations"].append(v)
            if v["status"] in ("FAIL", "ERROR"):
                results["errors"] += 1
                results["overall_status"] = "FAIL"
            elif v["status"] == "WARN":
                results["warnings"] += 1
                if results["overall_status"] == "PASS":
                    results["overall_status"] = "WARN"
        return results

    def apply_rule(self, record: Dict, rule: Dict) -> Dict[str, Any]:
        """Aplica uma regra avaliando a expressão declarada no contrato."""
        expression = rule.get("expression")
        severity = rule.get("severity", "error")
        fail_status = "FAIL" if severity == "error" else "WARN"

        result = {
            "rule_id": rule["id"], "description": rule["description"],
            "dimensao": self.dimensao_por_regra.get(rule["id"], "validade"),
            "severity": severity, "status": "PASS",
            "message": "Regra satisfeita", "field_value": None, "expected": expression,
        }

        # Regra sem expressão não pode ser verificada. Marcar como ERROR em vez
        # de PASS — silenciar isso foi a causa do falso 100%.
        if not expression:
            result["status"] = "ERROR"
            result["message"] = "Regra sem expressão declarada no contrato"
            return result

        try:
            if evaluate(expression, record):
                return result
            result["status"] = fail_status
            result["message"] = f"Violação de '{expression}'"
            result["field_value"] = self._relevant_fields(expression, record)
        except MissingField as exc:
            result["status"] = fail_status
            result["message"] = f"{exc} (exigido por '{expression}')"
        except RuleError as exc:
            result["status"] = "ERROR"
            result["message"] = f"Regra malformada: {exc}"
        except Exception as exc:  # noqa: BLE001 - erro inesperado vira ERROR visível
            result["status"] = "ERROR"
            result["message"] = f"Erro na validação: {exc}"
        return result

    @staticmethod
    def _relevant_fields(expression: str, record: Dict) -> Any:
        """Extrai do registro os campos citados na expressão, para diagnóstico."""
        names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expression))
        found = {k: record[k] for k in names if k in record}
        if not found:
            return None
        return next(iter(found.values())) if len(found) == 1 else found

    # ── Consolidação ────────────────────────────────────────────────────

    def validate_dataset(self, data_path: str) -> Dict[str, Any]:
        """Executa as três camadas e consolida as métricas por dimensão."""
        records = []
        with open(data_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        total_records = len(records)

        esquema = self.validar_esquema(records)
        perfil = self.perfilar(records)

        validation_results = []
        total_errors = total_warnings = 0
        for record in records:
            r = self.validate_record(record)
            validation_results.append(r)
            total_errors += r["errors"]
            total_warnings += r["warnings"]

        records_valid = sum(1 for r in validation_results if r["overall_status"] == "PASS")

        return {
            "product": self.product_name, "domain": self.domain,
            "dataset_path": data_path,
            "validation_timestamp": datetime.now(timezone.utc).isoformat(),
            "total_records": total_records,
            "records_with_errors": sum(1 for r in validation_results if r["overall_status"] == "FAIL"),
            "records_with_warnings": sum(1 for r in validation_results if r["overall_status"] == "WARN"),
            "records_valid": records_valid,
            "total_errors": total_errors, "total_warnings": total_warnings,
            "error_rate": (total_errors / total_records) * 100 if total_records else 0,
            "warning_rate": (total_warnings / total_records) * 100 if total_records else 0,
            # Percentual de registros integralmente válidos.
            "quality_score": (records_valid / total_records) * 100 if total_records else 0,
            "camadas": {
                "validacao_de_esquema": esquema,
                "perfilamento_estatistico": perfil,
                "regras_de_negocio": {
                    "camada": "regras_de_negocio",
                    "status": "FAIL" if total_errors else "PASS",
                    "regras_avaliadas": len(self.quality_rules),
                },
            },
            "dimensoes": self._consolidar_dimensoes(esquema, perfil, validation_results),
            "rule_performance": self.analyze_rule_performance(validation_results),
            "sample_errors": [r for r in validation_results if r["overall_status"] == "FAIL"][:5],
            "sample_warnings": [r for r in validation_results if r["overall_status"] == "WARN"][:3],
        }

    def _consolidar_dimensoes(self, esquema: Dict, perfil: Dict,
                              validation_results: List[Dict]) -> Dict[str, Any]:
        """Agrega violações e cobertura por dimensão de qualidade."""
        dims = {n: {"descricao": d, "verificada": False, "violacoes": 0,
                    "origem": [], "status": "NAO_VERIFICADA"}
                for n, d in DIMENSOES.items()}

        for camada, res in (("validacao_de_esquema", esquema),
                            ("perfilamento_estatistico", perfil)):
            for v in res["violacoes"]:
                d = dims[v["dimensao"]]
                d["violacoes"] += v.get("ocorrencias", 1) or 1
                if camada not in d["origem"]:
                    d["origem"].append(camada)

        # Cobertura das camadas 1 e 2, independentemente de haver violação
        for nome in ("integridade", "validade"):
            dims[nome]["verificada"] = True
            if "validacao_de_esquema" not in dims[nome]["origem"]:
                dims[nome]["origem"].append("validacao_de_esquema")
        if self.primary_key:
            dims["unicidade"]["verificada"] = True
            if "perfilamento_estatistico" not in dims["unicidade"]["origem"]:
                dims["unicidade"]["origem"].append("perfilamento_estatistico")

        at = perfil["atualidade"]
        if at.get("avaliada"):
            dims["atualidade"].update({
                "verificada": True, "status": "INFORMACIONAL",
                "idade_horas": at["idade_horas"],
                "sla_freshness": at["sla_freshness"],
                "dentro_do_sla": at["dentro_do_sla"],
                "origem": ["perfilamento_estatistico"],
            })

        # Camada 3: regras do contrato, classificadas pela dimensão declarada
        for r in validation_results:
            for v in r["validations"]:
                d = dims.get(v.get("dimensao", "validade"))
                if d is None:
                    continue
                d["verificada"] = True
                if "regras_de_negocio" not in d["origem"]:
                    d["origem"].append("regras_de_negocio")
                if v["status"] in ("FAIL", "ERROR"):
                    d["violacoes"] += 1

        for nome, d in dims.items():
            if nome == "atualidade":
                continue
            d["status"] = ("SEM_REGRA_DECLARADA" if not d["verificada"]
                           else ("FAIL" if d["violacoes"] else "PASS"))
        return dims

    def analyze_rule_performance(self, validation_results: List[Dict]) -> Dict[str, Dict]:
        """Analisa performance de cada regra de qualidade."""
        rule_stats: Dict[str, Dict] = {}
        for result in validation_results:
            for validation in result["validations"]:
                rid = validation["rule_id"]
                if rid not in rule_stats:
                    rule_stats[rid] = {
                        "description": validation["description"],
                        "dimensao": validation.get("dimensao", "validade"),
                        "total_executions": 0, "passes": 0,
                        "failures": 0, "warnings": 0, "errors": 0,
                    }
                s = rule_stats[rid]
                s["total_executions"] += 1
                st = validation["status"]
                if st == "PASS":
                    s["passes"] += 1
                elif st == "FAIL":
                    s["failures"] += 1
                elif st == "WARN":
                    s["warnings"] += 1
                elif st == "ERROR":
                    s["errors"] += 1

        for s in rule_stats.values():
            t = s["total_executions"]
            if t > 0:
                s["pass_rate"] = (s["passes"] / t) * 100
                s["failure_rate"] = (s["failures"] / t) * 100
                s["warning_rate"] = (s["warnings"] / t) * 100
                s["error_rate"] = (s["errors"] / t) * 100
            else:
                s.update(pass_rate=0, failure_rate=0, warning_rate=0, error_rate=0)
        return rule_stats


def validate_all_products():
    """Valida qualidade de todos os produtos de dados."""
    contract_data_mapping = [
        ("domains/financeiro/contas-a-pagar/data_contract.yaml", "domains/financeiro/contas-a-pagar/data/contas_a_pagar.jsonl"),
        ("domains/financeiro/contas-a-receber/data_contract.yaml", "domains/financeiro/contas-a-receber/data/contas_a_receber.jsonl"),
        ("domains/logistica/data_contract.yaml", "domains/logistica/data/logistics.jsonl"),
    ]
    try:
        with open("governance/policies.yaml", "r", encoding="utf-8") as f:
            policies = yaml.safe_load(f)
    except FileNotFoundError:
        policies = {}

    all_results = []
    for contract_path, data_path in contract_data_mapping:
        if os.path.exists(contract_path) and os.path.exists(data_path):
            print(f"Validando qualidade do dataset: {data_path}")
            all_results.append(
                DataQualityValidator(contract_path, policies).validate_dataset(data_path))
        else:
            print(f"⚠️ Arquivos não encontrados: {data_path} ou {contract_path}")

    os.makedirs("reports", exist_ok=True)
    report_path = "reports/data_quality_validation.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print("\n🔍 Data Quality Validation Report")
    print("=" * 62)
    SIGLA = {"PASS": "✅", "FAIL": "❌", "SEM_REGRA_DECLARADA": "➖",
             "NAO_VERIFICADA": "➖", "INFORMACIONAL": "ℹ️"}

    for m in all_results:
        print(f"\n📦 Produto: {m['product']} (Domain: {m['domain']})")
        print(f"   📊 Total registros: {m['total_records']}")
        print(f"   ✅ Válidos: {m['records_valid']} ({m['quality_score']:.1f}%)")
        print(f"   ❌ Com erros: {m['records_with_errors']} ({m['error_rate']:.1f}%)")

        print("   ── Camadas de verificação")
        for nome, c in m["camadas"].items():
            print(f"      {SIGLA.get(c['status'],'?')} {nome.replace('_',' ')}: {c['status']}")
            for v in c.get("violacoes", [])[:5]:
                print(f"           • {v['mensagem']}")

        print("   ── Dimensões de qualidade")
        for nome, d in m["dimensoes"].items():
            extra = ""
            if d["status"] == "FAIL":
                extra = f" — {d['violacoes']} violação(ões)"
            elif d["status"] == "SEM_REGRA_DECLARADA":
                extra = " — sem regra declarada no contrato"
            elif d["status"] == "INFORMACIONAL":
                dentro = "dentro" if d.get("dentro_do_sla") else "acima"
                extra = (f" — {d['idade_horas']}h desde a materialização, "
                         f"{dentro} do SLA {d['sla_freshness']}")
            print(f"      {SIGLA.get(d['status'],'?')} {nome}{extra}")

    print(f"\n📄 Relatório completo em: {report_path}")
    return all_results


# ═══════════════════════════════════════════════════════════════════════════
# Autoteste — python3 platform/quality/validate_data_quality.py --self-test
# ═══════════════════════════════════════════════════════════════════════════

def _self_test() -> int:
    """Verifica que as expressões dos contratos são realmente avaliadas."""
    falhas = []

    ok_mark = "\033[32m✓\033[0m"
    bad_mark = "\033[31m✗\033[0m"

    def check(nome, cond):
        print(f"  {ok_mark if cond else bad_mark} {nome}")
        if not cond:
            falhas.append(nome)

    ap = {"invoice_id": "INV-1000", "valor_liquido": 839.16,
          "dsc_moeda": "BRL", "status": "ABERTO"}
    ar = {"invoice_id": "INV-1000", "valor_bruto": 500.0,
          "dsc_moeda": "BRL", "status": "PAGO"}
    # Amostra logística: inclui os componentes de valor, exigidos pela regra
    # de consistência `log-k-total-decomposition` (decomposição de valor_total).
    log = {"invoice_id": "INV-1", "qtd_operacoes": 3, "dsc_moeda": "BRL",
           "status": ["PENDENTE", "CONCLUIDO"],
           "valor_base": 700.00, "valor_frete": 150.00,
           "valor_seguro": 50.00, "valor_imposto": 100.00,
           "valor_total": 1000.00}

    print("\n\033[1mDados bons passam\033[0m")
    check("valor positivo", evaluate("valor_liquido > 0", ap))
    check("moeda BRL", evaluate("dsc_moeda == 'BRL'", ap))
    check("invoice_id no padrão", evaluate("REGEXP_MATCH(invoice_id, '^INV-[0-9]+$')", ap))
    check("status na lista", evaluate("status IN ['ABERTO','PAGO','CANCELADO']", ap))
    check("ANY sobre array", evaluate("ANY(status, s => s IN ['PENDENTE','CONCLUIDO'])", log))

    print("\n\033[1mDados ruins reprovam (o bug original)\033[0m")
    check("valor negativo", not evaluate("valor_liquido > 0", {**ap, "valor_liquido": -10.0}))
    check("valor zero", not evaluate("valor_liquido > 0", {**ap, "valor_liquido": 0}))
    check("moeda XXX", not evaluate("dsc_moeda == 'BRL'", {**ap, "dsc_moeda": "XXX"}))
    check("invoice_id malformado",
          not evaluate("REGEXP_MATCH(invoice_id, '^INV-[0-9]+$')", {**ap, "invoice_id": "QUEBRADO-!!"}))
    check("status inválido",
          not evaluate("status IN ['ABERTO','PAGO','CANCELADO']", {**ap, "status": "ZZZ"}))
    check("array inválido",
          not evaluate("ANY(status, s => s IN ['PENDENTE','CONCLUIDO'])", {**log, "status": ["INVALIDO"]}))
    check("contagem zero", not evaluate("qtd_operacoes >= 1", {**log, "qtd_operacoes": 0}))

    print("\n\033[1mCampo ausente não vira PASS silencioso\033[0m")
    try:
        evaluate("campo_que_nao_existe > 0", ap)
        check("levanta MissingField", False)
    except MissingField:
        check("levanta MissingField", True)

    print("\n\033[1mExpressões perigosas são rejeitadas\033[0m")
    for mau in ["__import__('os').system('ls')", "open('/etc/passwd').read()",
                "invoice_id.__class__"]:
        try:
            evaluate(mau, ap)
            check(f"rejeita {mau[:34]}", False)
        except (RuleError, MissingField):
            check(f"rejeita {mau[:34]}", True)

    print("\n\033[1mToda regra dos contratos é avaliável\033[0m")
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    cwd = os.getcwd()
    os.chdir(root)
    try:
        amostras = {"contas-a-pagar": ap, "contas-a-receber": ar,
                    "operacoes-logistica": log}
        total_regras = 0
        for path in ("domains/financeiro/contas-a-pagar/data_contract.yaml",
                     "domains/financeiro/contas-a-receber/data_contract.yaml",
                     "domains/logistica/data_contract.yaml"):
            contrato = load_and_normalize(path)
            amostra = amostras[contrato["metadata"]["name"]]
            for regra in contrato.get("spec", {}).get("quality", {}).get("rules", []):
                total_regras += 1
                expr = regra.get("expression")
                if not expr:
                    check(f"{regra['id']} tem expressão", False)
                    continue
                try:
                    check(f"{regra['id']} avalia", evaluate(expr, amostra) is True)
                except Exception as exc:  # noqa: BLE001
                    check(f"{regra['id']} — {type(exc).__name__}: {exc}", False)
    finally:
        os.chdir(cwd)

    print("\n" + "─" * 60)
    if falhas:
        print(f"\033[31m✗ {len(falhas)} checagem(ns) falharam\033[0m")
        return 1
    print(f"\033[32m✓ Todas as checagens passaram ({total_regras} regras de contrato)\033[0m")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    validate_all_products()
