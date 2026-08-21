"""InvoiceScenario -> OASIS UBL 2.1 Invoice XML (Source A)."""
from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

from uder_experiment.scenario.truth_model import InvoiceScenario

_TAX_ID_MAP = {"Standard": "S", "Reduced": "AA", "Super-Reduced": "AA", "ZeroRated": "Z"}


def _e(text) -> str:
    return escape(str(text))


def _party_xml(tag: str, p, party_tax_scheme_role: str) -> str:
    street = f"<cbc:StreetName>{_e(p.street)}</cbc:StreetName>" if p.street else ""
    vat = next((i for i in p.identifiers if i.scheme == "VAT"), None)
    tax_scheme = ""
    if vat:
        tax_scheme = (
            "<cac:PartyTaxScheme>"
            f"<cbc:CompanyID>{_e(vat.value)}</cbc:CompanyID>"
            "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>"
            "</cac:PartyTaxScheme>"
        )
    return (
        f"<cac:{tag}><cac:Party>"
        f"<cac:PartyName><cbc:Name>{_e(p.name)}</cbc:Name></cac:PartyName>"
        "<cac:PostalAddress>"
        f"{street}"
        f"<cbc:CityName>{_e(p.city)}</cbc:CityName>"
        f"<cbc:PostalZone>{_e(p.postal_code)}</cbc:PostalZone>"
        f"<cac:Country><cbc:IdentificationCode>{_e(p.country)}</cbc:IdentificationCode></cac:Country>"
        "</cac:PostalAddress>"
        f"{tax_scheme}"
        "</cac:Party></cac:" + tag + ">"
    )


def render_ubl(scenario: InvoiceScenario) -> str:
    totals = scenario.totals()
    due = f"<cbc:DueDate>{scenario.due_date.isoformat()}</cbc:DueDate>" if scenario.due_date else ""
    order_ref = (
        f"<cac:OrderReference><cbc:ID>{_e(scenario.purchase_order_ref)}</cbc:ID></cac:OrderReference>"
        if scenario.purchase_order_ref else ""
    )
    contract_ref = (
        f"<cac:ContractDocumentReference><cbc:ID>{_e(scenario.contract_ref)}</cbc:ID></cac:ContractDocumentReference>"
        if scenario.contract_ref else ""
    )

    payment_id = f"<cbc:PaymentID>{_e(scenario.payment_reference)}</cbc:PaymentID>" if scenario.payment_reference else ""
    payment_account = (
        f"<cac:PayeeFinancialAccount><cbc:ID>{_e(scenario.payment_account)}</cbc:ID></cac:PayeeFinancialAccount>"
        if scenario.payment_account else ""
    )
    payment_means = (
        "<cac:PaymentMeans>"
        f"<cbc:PaymentMeansCode>{_e(scenario.payment_means)}</cbc:PaymentMeansCode>"
        f"{payment_id}{payment_account}"
        "</cac:PaymentMeans>"
    )

    doc_allowance_charge = ""
    if scenario.document_allowance > 0:
        doc_allowance_charge += (
            "<cac:AllowanceCharge><cbc:ChargeIndicator>false</cbc:ChargeIndicator>"
            f"<cbc:Amount currencyID=\"{scenario.currency}\">{scenario.document_allowance}</cbc:Amount>"
            "</cac:AllowanceCharge>"
        )
    if scenario.document_charge > 0:
        doc_allowance_charge += (
            "<cac:AllowanceCharge><cbc:ChargeIndicator>true</cbc:ChargeIndicator>"
            f"<cbc:Amount currencyID=\"{scenario.currency}\">{scenario.document_charge}</cbc:Amount>"
            "</cac:AllowanceCharge>"
        )

    tax_subtotals = ""
    for cat, rate, taxable, tax in totals.tax_breakdown:
        tax_subtotals += (
            "<cac:TaxSubtotal>"
            f"<cbc:TaxableAmount currencyID=\"{scenario.currency}\">{taxable}</cbc:TaxableAmount>"
            f"<cbc:TaxAmount currencyID=\"{scenario.currency}\">{tax}</cbc:TaxAmount>"
            "<cac:TaxCategory>"
            f"<cbc:ID>{_TAX_ID_MAP.get(cat, 'S')}</cbc:ID><cbc:Percent>{rate}</cbc:Percent>"
            "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>"
            "</cac:TaxCategory>"
            "</cac:TaxSubtotal>"
        )

    lines_xml = ""
    for l in scenario.lines:
        item_ids = ""
        for pid in l.product_ids:
            if pid.scheme == "SKU":
                item_ids += f"<cac:SellersItemIdentification><cbc:ID>{_e(pid.value)}</cbc:ID></cac:SellersItemIdentification>"
            else:
                item_ids += (
                    f"<cac:StandardItemIdentification><cbc:ID schemeID={quoteattr(pid.scheme)}>{_e(pid.value)}"
                    "</cbc:ID></cac:StandardItemIdentification>"
                )
        line_allowance = ""
        if l.allowance > 0:
            line_allowance += (
                "<cac:AllowanceCharge><cbc:ChargeIndicator>false</cbc:ChargeIndicator>"
                f"<cbc:Amount currencyID=\"{scenario.currency}\">{l.allowance}</cbc:Amount></cac:AllowanceCharge>"
            )
        if l.charge > 0:
            line_allowance += (
                "<cac:AllowanceCharge><cbc:ChargeIndicator>true</cbc:ChargeIndicator>"
                f"<cbc:Amount currencyID=\"{scenario.currency}\">{l.charge}</cbc:Amount></cac:AllowanceCharge>"
            )
        exemption = f"<cbc:TaxExemptionReasonCode>{_e(l.exemption_reason)}</cbc:TaxExemptionReasonCode>" if l.exemption_reason else ""
        lines_xml += (
            "<cac:InvoiceLine>"
            f"<cbc:ID>{_e(l.line_id)}</cbc:ID>"
            f"<cbc:InvoicedQuantity unitCode=\"{l.unit}\">{l.quantity}</cbc:InvoicedQuantity>"
            f"<cbc:LineExtensionAmount currencyID=\"{scenario.currency}\">{l.net_amount}</cbc:LineExtensionAmount>"
            f"{line_allowance}"
            "<cac:Item>"
            f"<cbc:Name>{_e(l.product_name)}</cbc:Name>"
            f"{item_ids}"
            "<cac:ClassifiedTaxCategory>"
            f"<cbc:ID>{_TAX_ID_MAP.get(l.tax_category, 'S')}</cbc:ID><cbc:Percent>{l.tax_rate}</cbc:Percent>"
            f"{exemption}"
            "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>"
            "</cac:ClassifiedTaxCategory>"
            "</cac:Item>"
            f"<cac:Price><cbc:PriceAmount currencyID=\"{scenario.currency}\">{l.unit_price}</cbc:PriceAmount></cac:Price>"
            "</cac:InvoiceLine>"
        )

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
    <cbc:ID>{_e(scenario.number)}</cbc:ID>
    <cbc:IssueDate>{scenario.issue_date.isoformat()}</cbc:IssueDate>
    {due}
    <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
    <cbc:DocumentCurrencyCode>{scenario.currency}</cbc:DocumentCurrencyCode>
    {order_ref}
    {contract_ref}
    {_party_xml("AccountingSupplierParty", scenario.supplier, "supplier")}
    {_party_xml("AccountingCustomerParty", scenario.customer, "customer")}
    {payment_means}
    {doc_allowance_charge}
    <cac:TaxTotal>
        <cbc:TaxAmount currencyID="{scenario.currency}">{totals.tax_amount}</cbc:TaxAmount>
        {tax_subtotals}
    </cac:TaxTotal>
    <cac:LegalMonetaryTotal>
        <cbc:LineExtensionAmount currencyID="{scenario.currency}">{totals.net_amount}</cbc:LineExtensionAmount>
        <cbc:TaxExclusiveAmount currencyID="{scenario.currency}">{totals.net_amount}</cbc:TaxExclusiveAmount>
        <cbc:TaxInclusiveAmount currencyID="{scenario.currency}">{totals.gross_amount}</cbc:TaxInclusiveAmount>
        <cbc:AllowanceTotalAmount currencyID="{scenario.currency}">{totals.allowance_total}</cbc:AllowanceTotalAmount>
        <cbc:ChargeTotalAmount currencyID="{scenario.currency}">{totals.charge_total}</cbc:ChargeTotalAmount>
        <cbc:PayableAmount currencyID="{scenario.currency}">{totals.payable_amount}</cbc:PayableAmount>
    </cac:LegalMonetaryTotal>
    {lines_xml}
</Invoice>
"""
    return xml
