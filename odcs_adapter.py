"""Adaptador para o Open Data Contract Standard (ODCS) — Bitol.

Os data contracts deste repositório são escritos no padrão ODCS v3
(https://bitol-io.github.io/open-data-contract-standard/). As ferramentas de
governança, catálogo e qualidade, porém, consomem uma visão interna mais
conveniente (metadata + spec.{product,schema,dataset,quality,tests,consumers,
monitoring}).

Este módulo carrega um contrato ODCS e o normaliza para essa visão interna,
mantendo todo o ferramental existente funcional sem precisar reescrever a
lógica de validação. Campos sem equivalente nativo no ODCS (registry/subject
do schema registry, testes declarativos, consumidores, monitoring, etc.) são
modelados via `customProperties`, que é o mecanismo oficial do ODCS para
metadados específicos da organização.
"""

from typing import Any, Dict, List

import yaml


def load_odcs(path: str) -> Dict[str, Any]:
    """Carrega o arquivo YAML bruto do contrato ODCS."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _custom_props(node: Dict[str, Any]) -> Dict[str, Any]:
    """Converte a lista ODCS `customProperties` em um dicionário property->value."""
    props: Dict[str, Any] = {}
    for item in (node or {}).get("customProperties", []) or []:
        if isinstance(item, dict) and "property" in item:
            props[item["property"]] = item.get("value")
    return props


def _owner_from_team(odcs: Dict[str, Any]) -> str:
    """Extrai o owner a partir da seção ODCS `team`."""
    team = odcs.get("team", []) or []
    for member in team:
        if isinstance(member, dict) and member.get("role") == "owner":
            return member.get("username", "")
    if team and isinstance(team[0], dict):
        return team[0].get("username", "")
    return ""


def _slas(odcs: Dict[str, Any]) -> Dict[str, Any]:
    """Converte `slaProperties` (lista ODCS) em dicionário property->value."""
    sla: Dict[str, Any] = {}
    for item in odcs.get("slaProperties", []) or []:
        if isinstance(item, dict) and "property" in item:
            sla[item["property"]] = item.get("value")
    return sla


def _fields_from_properties(properties: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Converte `schema[].properties` (ODCS) na lista interna de fields."""
    fields: List[Dict[str, Any]] = []
    for prop in properties or []:
        if not isinstance(prop, dict):
            continue
        field: Dict[str, Any] = {
            "name": prop.get("name"),
            "type": prop.get("logicalType"),
            "required": bool(prop.get("required", False)),
        }
        opts = prop.get("logicalTypeOptions") or {}
        if "enum" in opts:
            field["enum"] = opts["enum"]
        constraints: Dict[str, Any] = {}
        if "minimum" in opts:
            constraints["minInclusive"] = opts["minimum"]
        if "maximum" in opts:
            constraints["maxInclusive"] = opts["maximum"]
        if constraints:
            field["constraints"] = constraints
        if prop.get("description"):
            field["description"] = prop["description"]
        fields.append(field)
    return fields


def _primary_key(properties: List[Dict[str, Any]]) -> List[str]:
    """Deriva a primaryKey a partir das propriedades marcadas no ODCS."""
    keyed = [
        p for p in (properties or [])
        if isinstance(p, dict) and p.get("primaryKey")
    ]
    keyed.sort(key=lambda p: p.get("primaryKeyPosition", 0))
    return [p.get("name") for p in keyed]


def _quality_rules(schema_obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Converte `schema[].quality` (ODCS) na lista interna de regras."""
    rules: List[Dict[str, Any]] = []
    for q in (schema_obj or {}).get("quality", []) or []:
        if not isinstance(q, dict):
            continue
        rule: Dict[str, Any] = {
            "id": q.get("name"),
            "description": q.get("description"),
            "severity": q.get("severity"),
        }
        cp = _custom_props(q)
        if "expression" in cp:
            rule["expression"] = cp["expression"]
        elif q.get("rule"):
            rule["expression"] = q["rule"]
        applies_to = cp.get("applies_to")
        if applies_to:
            rule["applies_to"] = applies_to
        rules.append(rule)
    return rules


def normalize(odcs: Dict[str, Any]) -> Dict[str, Any]:
    """Converte um contrato ODCS v3 para a visão interna metadata/spec."""
    top_cp = _custom_props(odcs)
    schema_list = odcs.get("schema", []) or []
    schema_obj = schema_list[0] if schema_list else {}
    properties = schema_obj.get("properties", []) or []

    registry_cfg = top_cp.get("schema_registry", {}) or {}
    evolution = registry_cfg.get("evolution", {}) or {}

    metadata: Dict[str, Any] = {
        "name": odcs.get("name"),
        "domain": odcs.get("domain"),
        "owner": _owner_from_team(odcs),
        "version": str(odcs.get("version", "")),
        "tags": odcs.get("tags", []) or [],
    }
    for key in ("product_type", "output_port_kind", "master_entity",
                "created_at", "last_modified", "upstream"):
        if key in top_cp:
            metadata[key] = top_cp[key]

    description = odcs.get("description", {}) or {}

    spec: Dict[str, Any] = {
        "product": {
            "id": odcs.get("id"),
            "description": description.get("purpose", ""),
            "sla": _slas(odcs),
        },
        "schema": {
            "registry": registry_cfg.get("registry", ""),
            "subject": registry_cfg.get("subject", ""),
            "format": registry_cfg.get("format", ""),
            "evolution": {
                "policy": evolution.get("policy", ""),
                "breaking_changes": evolution.get("breaking_changes", ""),
                "deprecation_period": evolution.get("deprecation_period", ""),
            },
        },
        "dataset": {
            "name": schema_obj.get("name", ""),
            "primaryKey": _primary_key(properties),
            "fields": _fields_from_properties(properties),
        },
        "quality": {
            "rules": _quality_rules(schema_obj),
        },
        "tests": top_cp.get("tests", {}) or {},
        "consumers": top_cp.get("consumers", []) or [],
        "monitoring": top_cp.get("monitoring", {}) or {},
    }

    return {
        "apiVersion": odcs.get("apiVersion"),
        "kind": odcs.get("kind"),
        "metadata": metadata,
        "spec": spec,
    }


def load_and_normalize(path: str) -> Dict[str, Any]:
    """Carrega um contrato ODCS e retorna a visão interna normalizada."""
    return normalize(load_odcs(path))
