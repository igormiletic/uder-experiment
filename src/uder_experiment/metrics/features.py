"""Semantic feature extraction: phi_E / phi_D (spec Section 13).

extract_features() maps one CanonicalInvoice-shaped dict (ground truth OR
transformed output) into a flat, path-keyed feature space Phi. Both phi_E
(applied to ground truth, standing in for source information) and phi_D
(applied to the transformer's output) are the *same* function, applied
independently to each side -- this is what spec Section 13 calls normalizing
both into a common semantic feature space.

List-valued substructures (invoice items, tax breakdown entries) are keyed by
their own intrinsic content (lineId, tax category) rather than array
position, so re-ordered output does not spuriously look like a mismatch.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_STATIC_SPEC: dict[str, tuple[float, bool]] = {
    "identity.number": (3.0, True),
    "identity.issueDate": (2.0, True),
    "identity.dueDate": (1.0, False),
    "commercialContext.currency": (2.5, True),
    "commercialContext.purchaseOrderReference": (1.0, False),
    "commercialContext.contractReference": (0.5, False),
    "parties.supplier.name": (3.0, True),
    "parties.supplier.address.country": (1.0, False),
    "parties.supplier.address.city": (0.5, False),
    "parties.supplier.address.street": (0.3, False),
    "parties.supplier.address.postalCode": (0.3, False),
    "parties.supplier.identifiers": (1.2, False),
    "parties.customer.name": (3.0, True),
    "parties.customer.address.country": (0.7, False),
    "parties.customer.address.city": (0.3, False),
    "parties.customer.address.street": (0.2, False),
    "parties.customer.address.postalCode": (0.2, False),
    "parties.customer.identifiers": (0.8, False),
    "financialSummary.netAmount": (3.0, True),
    "financialSummary.taxAmount": (3.0, True),
    "financialSummary.grossAmount": (3.0, True),
    "financialSummary.payableAmount": (3.5, True),
    "financialSummary.allowanceTotal": (1.0, False),
    "financialSummary.chargeTotal": (1.0, False),
    "payment.means": (1.0, False),
    "payment.account": (1.0, False),
    "payment.reference": (0.5, False),
}

_ITEM_SPEC: dict[str, tuple[float, bool]] = {
    "product.name": (2.5, True),
    "product.identifiers": (1.0, False),
    "quantity.value": (2.0, True),
    "quantity.unit": (1.0, True),
    "pricing.unitPrice": (2.0, True),
    "pricing.netAmount": (2.5, True),
    "pricing.allowanceTotal": (0.5, False),
    "pricing.chargeTotal": (0.5, False),
    "taxation.rate": (2.0, True),
    "taxation.category": (1.0, False),
    "taxation.exempt": (0.5, False),
}

_TAX_BREAKDOWN_SPEC: dict[str, tuple[float, bool]] = {
    "rate": (1.5, True),
    "taxableAmount": (1.5, True),
    "taxAmount": (1.5, True),
}

DEFAULT_SPEC = (0.3, False)


@dataclass
class SemanticFeature:
    path: str
    value: Any
    value_type: str
    weight: float
    required: bool


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str) and _DATE_RE.match(value):
        return "date"
    if isinstance(value, (set, frozenset)):
        return "set"
    return "string"


def _get(d: dict, dotted: str) -> Any:
    node: Any = d
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _identifiers_set(identifiers: list[dict] | None) -> frozenset:
    if not identifiers:
        return frozenset()
    return frozenset((i.get("scheme"), i.get("value")) for i in identifiers)


def extract_features(canonical: dict) -> dict[str, SemanticFeature]:
    invoice = canonical.get("invoice", canonical)
    features: dict[str, SemanticFeature] = {}

    for path, (weight, required) in _STATIC_SPEC.items():
        if path.endswith("identifiers"):
            value = _identifiers_set(_get(invoice, path))
            features[path] = SemanticFeature(path, value, "set", weight, required)
        else:
            value = _get(invoice, path)
            features[path] = SemanticFeature(path, value, _value_type(value), weight, required)

    for idx, item in enumerate(invoice.get("items", []) or []):
        if not isinstance(item, dict):
            continue
        key = item.get("lineId") or f"pos{idx}"
        base = f"items[{key}]"
        for sub_path, (weight, required) in _ITEM_SPEC.items():
            full_path = f"{base}.{sub_path}"
            if sub_path.endswith("identifiers"):
                value = _identifiers_set(_get(item, sub_path))
                features[full_path] = SemanticFeature(full_path, value, "set", weight, required)
            else:
                value = _get(item, sub_path)
                features[full_path] = SemanticFeature(full_path, value, _value_type(value), weight, required)

    for idx, entry in enumerate(invoice.get("financialSummary", {}).get("taxBreakdown", []) or []):
        if not isinstance(entry, dict):
            continue
        key = entry.get("category") or f"pos{idx}"
        base = f"financialSummary.taxBreakdown[{key}]"
        for sub_path, (weight, required) in _TAX_BREAKDOWN_SPEC.items():
            full_path = f"{base}.{sub_path}"
            value = entry.get(sub_path)
            features[full_path] = SemanticFeature(full_path, value, _value_type(value), weight, required)

    return features


def source_support_values(uder_entities_props: list[dict]) -> set[str]:
    """phi_E support set: every scalar value literally present anywhere in the source UDER entities.

    Used by the precision metric to decide whether an output feature is
    "supported by source" (spec Section 13.3) without any AI-based judging.
    """
    support: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif node is not None:
            support.add(str(node).strip().lower())

    for props in uder_entities_props:
        walk(props)
    return support
