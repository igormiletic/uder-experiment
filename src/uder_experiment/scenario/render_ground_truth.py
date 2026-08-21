"""InvoiceScenario -> ground-truth CanonicalInvoice.

This is an independent rendering, not derived from the AI transformer and not
derived from any of the source XML/JSON renderings (spec Section 5).
"""
from __future__ import annotations

from uder_experiment.scenario.truth_model import InvoiceScenario
from uder_experiment.schema.canonical_invoice import (
    Address, CanonicalInvoice, CommercialContext, FinancialSummary, Identifier,
    Identity, InvoiceBody, InvoiceLine, Parties, Party, Payment, Pricing, Product,
    Quantity, TaxBreakdownEntry, Taxation,
)


def _party(p) -> Party:
    return Party(
        name=p.name,
        identifiers=[Identifier(scheme=i.scheme, value=i.value) for i in p.identifiers],
        address=Address(street=p.street, city=p.city, postal_code=p.postal_code, country=p.country),
    )


def render_ground_truth(scenario: InvoiceScenario) -> CanonicalInvoice:
    totals = scenario.totals()

    items = []
    for l in scenario.lines:
        items.append(InvoiceLine(
            line_id=l.line_id,
            product=Product(name=l.product_name, identifiers=[Identifier(scheme=i.scheme, value=i.value) for i in l.product_ids]),
            quantity=Quantity(value=float(l.quantity), unit=l.unit),
            pricing=Pricing(unit_price=float(l.unit_price), net_amount=float(l.net_amount),
                             allowance_total=float(l.allowance), charge_total=float(l.charge)),
            taxation=Taxation(rate=float(l.tax_rate), category=l.tax_category, exempt=l.exempt,
                               exemption_reason=l.exemption_reason),
        ))

    body = InvoiceBody(
        identity=Identity(number=scenario.number, issue_date=scenario.issue_date.isoformat(),
                           due_date=scenario.due_date.isoformat() if scenario.due_date else None),
        commercial_context=CommercialContext(currency=scenario.currency,
                                              purchase_order_reference=scenario.purchase_order_ref,
                                              contract_reference=scenario.contract_ref),
        parties=Parties(supplier=_party(scenario.supplier), customer=_party(scenario.customer)),
        items=items,
        financial_summary=FinancialSummary(
            net_amount=float(totals.net_amount), tax_amount=float(totals.tax_amount),
            allowance_total=float(totals.allowance_total), charge_total=float(totals.charge_total),
            gross_amount=float(totals.gross_amount), payable_amount=float(totals.payable_amount),
            tax_breakdown=[TaxBreakdownEntry(category=c, rate=float(r), taxable_amount=float(t), tax_amount=float(x))
                           for c, r, t, x in totals.tax_breakdown],
        ),
        payment=Payment(means=scenario.payment_means, account=scenario.payment_account,
                         reference=scenario.payment_reference),
    )
    return CanonicalInvoice(invoice=body)
