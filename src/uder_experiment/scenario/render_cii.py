"""InvoiceScenario -> UN/CEFACT Cross Industry Invoice (CII) XML (Source B).

Deliberately different structural path/naming from UBL: parties live under
ApplicableHeaderTradeAgreement (not two separate top-level AccountingParty
elements), monetary totals are one flat
SpecifiedTradeSettlementHeaderMonetarySummation block, tax categories use
CII's CategoryCode vocabulary, and dates are encoded as udt:DateTimeString
format="102" (CCYYMMDD) rather than ISO date strings.
"""
from __future__ import annotations

from xml.sax.saxutils import escape

from uder_experiment.scenario.truth_model import InvoiceScenario

_TAX_CAT_MAP = {"Standard": "S", "Reduced": "AA", "Super-Reduced": "AA", "ZeroRated": "Z"}
_PAYMENT_CODE_MAP = {"BANK_TRANSFER": "30", "SEPA_CREDIT_TRANSFER": "58", "CARD": "48"}


def _e(text) -> str:
    return escape(str(text))


def _ccyymmdd(d) -> str:
    return d.strftime("%Y%m%d")


def _party_xml(tag: str, p) -> str:
    vat = next((i for i in p.identifiers if i.scheme == "VAT"), None)
    tax_reg = (
        f'<ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">{_e(vat.value)}</ram:ID></ram:SpecifiedTaxRegistration>'
        if vat else ""
    )
    line_one = f"<ram:LineOne>{_e(p.street)}</ram:LineOne>" if p.street else ""
    return (
        f"<ram:{tag}>"
        f"<ram:Name>{_e(p.name)}</ram:Name>"
        f"{tax_reg}"
        "<ram:PostalTradeAddress>"
        f"<ram:PostcodeCode>{_e(p.postal_code)}</ram:PostcodeCode>"
        f"{line_one}"
        f"<ram:CityName>{_e(p.city)}</ram:CityName>"
        f"<ram:CountryID>{_e(p.country)}</ram:CountryID>"
        "</ram:PostalTradeAddress>"
        f"</ram:{tag}>"
    )


def render_cii(scenario: InvoiceScenario) -> str:
    totals = scenario.totals()

    lines_xml = ""
    for l in scenario.lines:
        global_id = next((i for i in l.product_ids if i.scheme == "GTIN"), None)
        sku_id = next((i for i in l.product_ids if i.scheme == "SKU"), None)
        global_id_xml = f'<ram:GlobalID schemeID="0160">{_e(global_id.value)}</ram:GlobalID>' if global_id else ""
        seller_id_xml = f"<ram:SellerAssignedID>{_e(sku_id.value)}</ram:SellerAssignedID>" if sku_id else ""

        allowance_charge = ""
        if l.allowance > 0:
            allowance_charge += (
                "<ram:SpecifiedTradeAllowanceCharge><ram:ChargeIndicator><udt:Indicator>false</udt:Indicator>"
                f"</ram:ChargeIndicator><ram:ActualAmount>{l.allowance}</ram:ActualAmount></ram:SpecifiedTradeAllowanceCharge>"
            )
        if l.charge > 0:
            allowance_charge += (
                "<ram:SpecifiedTradeAllowanceCharge><ram:ChargeIndicator><udt:Indicator>true</udt:Indicator>"
                f"</ram:ChargeIndicator><ram:ActualAmount>{l.charge}</ram:ActualAmount></ram:SpecifiedTradeAllowanceCharge>"
            )
        exemption = f"<ram:ExemptionReason>{_e(l.exemption_reason)}</ram:ExemptionReason>" if l.exemption_reason else ""

        lines_xml += (
            "<ram:IncludedSupplyChainTradeLineItem>"
            f"<ram:AssociatedDocumentLineDocument><ram:LineID>{_e(l.line_id)}</ram:LineID></ram:AssociatedDocumentLineDocument>"
            "<ram:SpecifiedTradeProduct>"
            f"{global_id_xml}{seller_id_xml}"
            f"<ram:Name>{_e(l.product_name)}</ram:Name>"
            "</ram:SpecifiedTradeProduct>"
            "<ram:SpecifiedLineTradeAgreement>"
            f"<ram:NetPriceProductTradePrice><ram:ChargeAmount>{l.unit_price}</ram:ChargeAmount></ram:NetPriceProductTradePrice>"
            "</ram:SpecifiedLineTradeAgreement>"
            f'<ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="{l.unit}">{l.quantity}</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>'
            "<ram:SpecifiedLineTradeSettlement>"
            "<ram:ApplicableTradeTax>"
            "<ram:TypeCode>VAT</ram:TypeCode>"
            f"<ram:CategoryCode>{_TAX_CAT_MAP.get(l.tax_category, 'S')}</ram:CategoryCode>"
            f"<ram:RateApplicablePercent>{l.tax_rate}</ram:RateApplicablePercent>"
            f"{exemption}"
            "</ram:ApplicableTradeTax>"
            f"{allowance_charge}"
            f"<ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount>{l.net_amount}</ram:LineTotalAmount>"
            "</ram:SpecifiedTradeSettlementLineMonetarySummation>"
            "</ram:SpecifiedLineTradeSettlement>"
            "</ram:IncludedSupplyChainTradeLineItem>"
        )

    buyer_ref = f"<ram:BuyerReference>{_e(scenario.purchase_order_ref)}</ram:BuyerReference>" if scenario.purchase_order_ref else ""
    order_doc = (
        f"<ram:BuyerOrderReferencedDocument><ram:IssuerAssignedID>{_e(scenario.purchase_order_ref)}</ram:IssuerAssignedID></ram:BuyerOrderReferencedDocument>"
        if scenario.purchase_order_ref else ""
    )
    contract_doc = (
        f"<ram:ContractReferencedDocument><ram:IssuerAssignedID>{_e(scenario.contract_ref)}</ram:IssuerAssignedID></ram:ContractReferencedDocument>"
        if scenario.contract_ref else ""
    )

    due_terms = (
        f'<ram:SpecifiedTradePaymentTerms><ram:DueDateDateTime><udt:DateTimeString format="102">{_ccyymmdd(scenario.due_date)}</udt:DateTimeString></ram:DueDateDateTime></ram:SpecifiedTradePaymentTerms>'
        if scenario.due_date else ""
    )
    account_xml = (
        f"<ram:PayeePartyCreditorFinancialAccount><ram:IBANID>{_e(scenario.payment_account)}</ram:IBANID></ram:PayeePartyCreditorFinancialAccount>"
        if scenario.payment_account else ""
    )
    payment_means = (
        "<ram:SpecifiedTradeSettlementPaymentMeans>"
        f"<ram:TypeCode>{_PAYMENT_CODE_MAP.get(scenario.payment_means, '30')}</ram:TypeCode>"
        f"{account_xml}"
        "</ram:SpecifiedTradeSettlementPaymentMeans>"
    )
    payment_ref = f"<ram:PaymentReference>{_e(scenario.payment_reference)}</ram:PaymentReference>" if scenario.payment_reference else ""

    doc_allowance_charge = ""
    if scenario.document_allowance > 0:
        doc_allowance_charge += (
            "<ram:SpecifiedTradeAllowanceCharge><ram:ChargeIndicator><udt:Indicator>false</udt:Indicator></ram:ChargeIndicator>"
            f"<ram:ActualAmount>{scenario.document_allowance}</ram:ActualAmount></ram:SpecifiedTradeAllowanceCharge>"
        )
    if scenario.document_charge > 0:
        doc_allowance_charge += (
            "<ram:SpecifiedTradeAllowanceCharge><ram:ChargeIndicator><udt:Indicator>true</udt:Indicator></ram:ChargeIndicator>"
            f"<ram:ActualAmount>{scenario.document_charge}</ram:ActualAmount></ram:SpecifiedTradeAllowanceCharge>"
        )

    trade_taxes = ""
    for cat, rate, taxable, tax in totals.tax_breakdown:
        trade_taxes += (
            "<ram:ApplicableTradeTax>"
            f"<ram:CalculatedAmount>{tax}</ram:CalculatedAmount>"
            "<ram:TypeCode>VAT</ram:TypeCode>"
            f"<ram:BasisAmount>{taxable}</ram:BasisAmount>"
            f"<ram:CategoryCode>{_TAX_CAT_MAP.get(cat, 'S')}</ram:CategoryCode>"
            f"<ram:RateApplicablePercent>{rate}</ram:RateApplicablePercent>"
            "</ram:ApplicableTradeTax>"
        )

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice
    xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
    xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
    xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
    <rsm:ExchangedDocumentContext>
        <ram:GuidelineSpecifiedDocumentContextParameter><ram:ID>urn:cen.eu:en16931:2017</ram:ID></ram:GuidelineSpecifiedDocumentContextParameter>
    </rsm:ExchangedDocumentContext>
    <rsm:ExchangedDocument>
        <ram:ID>{_e(scenario.number)}</ram:ID>
        <ram:TypeCode>380</ram:TypeCode>
        <ram:IssueDateTime><udt:DateTimeString format="102">{_ccyymmdd(scenario.issue_date)}</udt:DateTimeString></ram:IssueDateTime>
    </rsm:ExchangedDocument>
    <rsm:SupplyChainTradeTransaction>
        {lines_xml}
        <ram:ApplicableHeaderTradeAgreement>
            {buyer_ref}
            {_party_xml("SellerTradeParty", scenario.supplier)}
            {_party_xml("BuyerTradeParty", scenario.customer)}
            {order_doc}
            {contract_doc}
        </ram:ApplicableHeaderTradeAgreement>
        <ram:ApplicableHeaderTradeDelivery/>
        <ram:ApplicableHeaderTradeSettlement>
            <ram:InvoiceCurrencyCode>{scenario.currency}</ram:InvoiceCurrencyCode>
            {payment_means}
            {due_terms}
            {doc_allowance_charge}
            {trade_taxes}
            <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
                <ram:LineTotalAmount>{totals.net_amount}</ram:LineTotalAmount>
                <ram:AllowanceTotalAmount>{totals.allowance_total}</ram:AllowanceTotalAmount>
                <ram:ChargeTotalAmount>{totals.charge_total}</ram:ChargeTotalAmount>
                <ram:TaxBasisTotalAmount>{totals.net_amount}</ram:TaxBasisTotalAmount>
                <ram:TaxTotalAmount currencyID="{scenario.currency}">{totals.tax_amount}</ram:TaxTotalAmount>
                <ram:GrandTotalAmount>{totals.gross_amount}</ram:GrandTotalAmount>
                <ram:DuePayableAmount>{totals.payable_amount}</ram:DuePayableAmount>
            </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
            {payment_ref}
        </ram:ApplicableHeaderTradeSettlement>
    </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
"""
    return xml
