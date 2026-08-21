"""InvoiceScenario -> normalized JSON invoice representation, Source C.

Standard selected: OAGIS (Open Applications Group Integration Specification)
Invoice BOD. OAGIS is XML-native (see dlds/sample_data/oagis.xml for the
ApplicationArea/DataArea envelope this mirrors); per spec Section 3 it is
rendered here as an equivalent normalized JSON serialization while preserving
OAGIS's own semantic structure and field names.

Why OAGIS is genuinely different from UBL and CII (not a trivial variant):
- Envelope paradigm: OAGIS wraps business content in a generic
  ApplicationArea (message routing/sender metadata) + DataArea (BOD noun),
  a messaging/integration-bus style envelope. UBL and CII are themselves the
  root business document -- no outer messaging envelope.
- Party identification: OAGIS uses a generic PartyIDs list of typed IDs
  (no invoice-specific "AccountingSupplierParty"/"SellerTradeParty" wrapper);
  UBL nests parties under invoice-specific accounting-party roles, CII nests
  them under a header trade agreement.
- Amounts: OAGIS keeps a single TotalAmount block with typed sub-amounts
  rather than UBL's LegalMonetaryTotal or CII's
  SpecifiedTradeSettlementHeaderMonetarySummation -- different names, same
  concepts, forcing a real semantic (not syntactic) mapping.
- Serialization family: JSON vs. XML, so the AI transformer must generalize
  across both data formats, not just XML dialects.

Field correspondence to common invoice concepts (see also README):
  DataArea.Invoice.InvoiceHeader.DocumentID.ID      -> invoice.identity.number
  DataArea.Invoice.InvoiceHeader.DocumentDateTime    -> invoice.identity.issueDate
  DataArea.Invoice.InvoiceHeader.SellerParty         -> invoice.parties.supplier
  DataArea.Invoice.InvoiceHeader.BuyerParty          -> invoice.parties.customer
  DataArea.Invoice.InvoiceLine[].Item                -> invoice.items[].product
  DataArea.Invoice.InvoiceHeader.TotalAmount         -> invoice.financialSummary
"""
from __future__ import annotations

from uder_experiment.scenario.truth_model import InvoiceScenario


def _party(p) -> dict:
    party_ids = [{"ID": i.value, "type": i.scheme} for i in p.identifiers]
    address = {"City": p.city, "PostalCode": p.postal_code, "CountryCode": p.country}
    if p.street:
        address["Street"] = p.street
    return {"PartyIDs": party_ids, "Name": p.name, "Location": {"Address": address}}


def render_source_c(scenario: InvoiceScenario) -> dict:
    totals = scenario.totals()

    lines = []
    for l in scenario.lines:
        item_ids = [{"ID": i.value, "type": i.scheme} for i in l.product_ids]
        allowance_charge = []
        if l.allowance > 0:
            allowance_charge.append({"Indicator": "Allowance", "Amount": float(l.allowance)})
        if l.charge > 0:
            allowance_charge.append({"Indicator": "Charge", "Amount": float(l.charge)})
        lines.append({
            "LineNumber": l.line_id,
            "Item": {"ItemID": item_ids, "Description": l.product_name},
            "Quantity": {"value": float(l.quantity), "uom": l.unit},
            "UnitPrice": {"Amount": float(l.unit_price)},
            "LineExtensionAmount": float(l.net_amount),
            "AllowanceCharge": allowance_charge,
            "TaxCategory": {
                "CategoryCode": l.tax_category, "Percent": float(l.tax_rate),
                "Exempt": l.exempt, "ExemptionReason": l.exemption_reason,
            },
        })

    doc_allowance_charge = []
    if scenario.document_allowance > 0:
        doc_allowance_charge.append({"Indicator": "Allowance", "Amount": float(scenario.document_allowance)})
    if scenario.document_charge > 0:
        doc_allowance_charge.append({"Indicator": "Charge", "Amount": float(scenario.document_charge)})

    tax_summary = [
        {"CategoryCode": cat, "Percent": float(rate), "TaxableAmount": float(taxable), "TaxAmount": float(tax)}
        for cat, rate, taxable, tax in totals.tax_breakdown
    ]

    payment_term = {
        "PaymentMeansCode": scenario.payment_means,
    }
    if scenario.payment_account:
        payment_term["PayerFinancialAccount"] = {"ID": scenario.payment_account}
    if scenario.payment_reference:
        payment_term["PaymentReference"] = scenario.payment_reference

    header = {
        "DocumentID": {"ID": scenario.number},
        "DocumentDateTime": scenario.issue_date.isoformat(),
        "CurrencyCode": scenario.currency,
        "BuyerParty": _party(scenario.customer),
        "SellerParty": _party(scenario.supplier),
        "TotalAmount": {
            "LineTotalAmount": float(totals.net_amount),
            "TaxTotalAmount": float(totals.tax_amount),
            "AllowanceTotalAmount": float(totals.allowance_total),
            "ChargeTotalAmount": float(totals.charge_total),
            "GrossAmount": float(totals.gross_amount),
            "PayableAmount": float(totals.payable_amount),
        },
        "TaxSummary": tax_summary,
        "AllowanceCharge": doc_allowance_charge,
        "PaymentTerm": payment_term,
    }
    if scenario.due_date:
        header["DueDateTime"] = scenario.due_date.isoformat()
    if scenario.purchase_order_ref:
        header["ReferenceDocumentID"] = scenario.purchase_order_ref
    if scenario.contract_ref:
        header["ContractReferenceDocumentID"] = scenario.contract_ref

    return {
        "ApplicationArea": {
            "Sender": {
                "LogicalID": "ExampleSupplierSystem",
                "ComponentID": "InvoicingService",
                "TaskID": scenario.number,
            },
            "CreationDateTime": scenario.issue_date.isoformat(),
        },
        "DataArea": {
            "Invoice": {
                "InvoiceHeader": header,
                "InvoiceLine": lines,
            }
        },
    }
