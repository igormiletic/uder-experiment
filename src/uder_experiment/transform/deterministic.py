"""Baseline 1: deterministic, rule-based structural mapping from UDER entities to CanonicalInvoice. No AI involved."""
from __future__ import annotations

import time

from uder_experiment.schema.canonical_invoice import CANONICAL_INVOICE_SCHEMA_VERSION
from uder_experiment.transform.base import Transformer, TransformResult
from uder_experiment.transform.context import TransformationContext
from uder_experiment.uder.entities import UDEREntity

_REVERSE_CATEGORY = {"S": "Standard", "Z": "ZeroRated"}


def _infer_category(code: str | None, rate: float) -> str:
    if code in _REVERSE_CATEGORY:
        return _REVERSE_CATEGORY[code]
    if code == "AA":
        # UBL/CII UNCL5305 codes collapse Reduced/Super-Reduced into one code ("AA") --
        # a genuine, real-world source-format information loss. Disambiguate via rate.
        return "Reduced" if rate >= 7.5 else "Super-Reduced"
    return code or "Standard"


def _f(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class DeterministicTransformer(Transformer):
    name = "deterministic"

    async def transform(self, uder_entities: list[UDEREntity], target_schema: dict,
                         context: TransformationContext) -> TransformResult:
        start = time.perf_counter()
        entities = {e.entity_id: e for e in uder_entities}
        field_conf: dict[str, float] = {}
        provenance: dict[str, str] = {}
        resolved = 0
        total = 0

        def mark(path: str, ok: bool, source_entity_id: str | None) -> None:
            nonlocal resolved, total
            total += 1
            field_conf[path] = 1.0 if ok else 0.15
            if ok:
                resolved += 1
                if source_entity_id:
                    provenance[path] = source_entity_id

        invoice = next((e for e in uder_entities if e.entity_type == "Invoice"), None)
        if invoice is None:
            return TransformResult(
                transformed_data={}, confidence=0.0,
                metadata={"error": "no Invoice root entity present", "confidence_strategy": "rule_based_completeness"},
                latency_ms=(time.perf_counter() - start) * 1000,
            )

        def linked(predicate: str) -> UDEREntity | None:
            for link in invoice.links:
                if link.predicate == predicate and link.target_entity_id in entities:
                    return entities[link.target_entity_id]
            return None

        def linked_all(predicate: str) -> list[UDEREntity]:
            return [entities[l.target_entity_id] for l in invoice.links
                    if l.predicate == predicate and l.target_entity_id in entities]

        supplier = linked("hasSupplier")
        customer = linked("hasCustomer")
        tax_summary = linked("hasTaxSummary")
        payment = linked("hasPayment")
        lines = linked_all("hasLine")

        def party_dict(prefix: str, party: UDEREntity | None) -> dict:
            mark(f"{prefix}.name", party is not None, party.entity_id if party else None)
            if party is None:
                return {"name": "UNKNOWN", "identifiers": [], "address": {"country": "XX"}}
            addr = party.properties.get("address") or {}
            mark(f"{prefix}.address.country", bool(addr.get("country")), party.entity_id)
            return {
                "name": party.properties.get("name") or "UNKNOWN",
                "identifiers": party.properties.get("identifiers") or [],
                "address": {
                    "street": addr.get("street"), "city": addr.get("city"),
                    "postalCode": addr.get("postalCode"), "country": addr.get("country") or "XX",
                },
            }

        items = []
        for idx, line in enumerate(lines):
            product = None
            for l in line.links:
                if l.predicate == "hasProduct" and l.target_entity_id in entities:
                    product = entities[l.target_entity_id]
            mark(f"items[{idx}].product.name", product is not None, line.entity_id)
            allowance_charges = line.properties.get("allowanceCharge") or []
            allowance_total = sum(_f(a["amount"]) for a in allowance_charges if not a.get("isCharge"))
            charge_total = sum(_f(a["amount"]) for a in allowance_charges if a.get("isCharge"))
            rate = _f(line.properties.get("taxRate"))
            items.append({
                "lineId": line.entity_id.rsplit(":", 1)[-1],
                "product": {
                    "name": (product.properties.get("name") if product else None) or "UNKNOWN",
                    "identifiers": (product.properties.get("identifiers") if product else None) or [],
                },
                "quantity": {"value": _f(line.properties.get("quantity")), "unit": line.properties.get("unit") or "EA"},
                "pricing": {
                    "unitPrice": _f(line.properties.get("unitPrice")),
                    "netAmount": _f(line.properties.get("netAmount")),
                    "allowanceTotal": allowance_total, "chargeTotal": charge_total,
                },
                "taxation": {
                    "rate": rate,
                    "category": _infer_category(line.properties.get("taxCategory"), rate),
                    "exempt": bool(line.properties.get("exempt")) or bool(line.properties.get("exemptionReason")) or rate == 0.0,
                    "exemptionReason": line.properties.get("exemptionReason"),
                },
            })
        mark("items", len(lines) > 0, invoice.entity_id)

        tax_breakdown = []
        if tax_summary is not None:
            for entry in tax_summary.properties.get("breakdown", []):
                rate = _f(entry.get("rate"))
                tax_breakdown.append({
                    "category": _infer_category(entry.get("categoryId"), rate),
                    "rate": rate, "taxableAmount": _f(entry.get("taxableAmount")), "taxAmount": _f(entry.get("taxAmount")),
                })
        mark("financialSummary.taxBreakdown", tax_summary is not None, tax_summary.entity_id if tax_summary else None)
        mark("financialSummary.taxAmount", tax_summary is not None, tax_summary.entity_id if tax_summary else None)

        payment_dict = {"means": "BANK_TRANSFER", "account": None, "reference": None}
        if payment is not None:
            payment_dict = {
                "means": payment.properties.get("means") or "BANK_TRANSFER",
                "account": payment.properties.get("account"),
                "reference": payment.properties.get("reference"),
            }
        mark("payment.means", payment is not None, payment.entity_id if payment else None)

        mark("identity.number", bool(invoice.properties.get("number")), invoice.entity_id)
        mark("identity.issueDate", bool(invoice.properties.get("issueDate")), invoice.entity_id)
        mark("commercialContext.currency", bool(invoice.properties.get("currency")), invoice.entity_id)
        mark("financialSummary.netAmount", invoice.properties.get("netAmount") is not None, invoice.entity_id)
        mark("financialSummary.payableAmount", invoice.properties.get("payableAmount") is not None, invoice.entity_id)

        data = {
            "schemaVersion": CANONICAL_INVOICE_SCHEMA_VERSION,
            "invoice": {
                "identity": {
                    "number": invoice.properties.get("number") or "UNKNOWN",
                    "issueDate": invoice.properties.get("issueDate") or "1970-01-01",
                    "dueDate": invoice.properties.get("dueDate"),
                },
                "commercialContext": {
                    "currency": invoice.properties.get("currency") or "EUR",
                    "purchaseOrderReference": invoice.properties.get("purchaseOrderReference"),
                    "contractReference": invoice.properties.get("contractReference"),
                },
                "parties": {"supplier": party_dict("parties.supplier", supplier), "customer": party_dict("parties.customer", customer)},
                "items": items,
                "financialSummary": {
                    "netAmount": _f(invoice.properties.get("netAmount")),
                    "taxAmount": _f(tax_summary.properties.get("taxAmount")) if tax_summary else 0.0,
                    "allowanceTotal": _f(invoice.properties.get("allowanceTotalAmount")),
                    "chargeTotal": _f(invoice.properties.get("chargeTotalAmount")),
                    "grossAmount": _f(invoice.properties.get("taxInclusiveAmount")),
                    "payableAmount": _f(invoice.properties.get("payableAmount")),
                    "taxBreakdown": tax_breakdown,
                },
                "payment": payment_dict,
            },
        }

        global_confidence = resolved / total if total else 0.0
        result = TransformResult(
            transformed_data=data, confidence=global_confidence, field_confidences=field_conf,
            provenance=provenance,
            metadata={
                "mode": context.mode, "transformer": "deterministic",
                "confidence_strategy": "rule_based_completeness",
                "confidence_estimate": True,
            },
            latency_ms=(time.perf_counter() - start) * 1000,
        )
        result.validate()
        return result
