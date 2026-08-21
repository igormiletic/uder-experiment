"""Parse a rendered UN/CEFACT CII XML document into a UDER entity graph (same target shape as UBL/Source-C converters)."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from uder_experiment.uder.entities import UDEREntity, UDERGraph, UDERLink

RSM = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
RAM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
UDT = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"


def _r(tag: str) -> str:
    return f"{{{RAM}}}{tag}"


def _s(tag: str) -> str:
    return f"{{{RSM}}}{tag}"


def _text(el, path, default=None):
    found = el.find(path)
    return found.text.strip() if found is not None and found.text else default


def _parse_party(party_el, number: str, role: str) -> UDEREntity:
    name = _text(party_el, _r("Name"))
    tax_reg = party_el.find(_r("SpecifiedTaxRegistration"))
    identifiers = []
    if tax_reg is not None:
        vat = _text(tax_reg, _r("ID"))
        if vat:
            identifiers.append({"scheme": "VAT", "value": vat})
    addr = party_el.find(_r("PostalTradeAddress"))
    properties = {
        "name": name,
        "identifiers": identifiers,
        "address": {
            "street": _text(addr, _r("LineOne")) if addr is not None else None,
            "city": _text(addr, _r("CityName")) if addr is not None else None,
            "postalCode": _text(addr, _r("PostcodeCode")) if addr is not None else None,
            "country": _text(addr, _r("CountryID")) if addr is not None else None,
        },
    }
    return UDEREntity(entity_id=f"urn:party:{number}:{role}", entity_type="Party",
                       representation="cii", source_standard="UNCEFACT-CII-100", properties=properties)


def parse_cii_to_uder(xml_text: str) -> UDERGraph:
    root = ET.fromstring(xml_text)
    number = _text(root, f"{_s('ExchangedDocument')}/{_r('ID')}")
    invoice_id = f"urn:invoice:{number}"
    graph = UDERGraph(root_entity_id=invoice_id)

    txn = root.find(_s("SupplyChainTradeTransaction"))
    agreement = txn.find(_r("ApplicableHeaderTradeAgreement"))
    settlement = txn.find(_r("ApplicableHeaderTradeSettlement"))

    supplier = _parse_party(agreement.find(_r("SellerTradeParty")), number, "supplier")
    customer = _parse_party(agreement.find(_r("BuyerTradeParty")), number, "customer")
    graph.add(supplier)
    graph.add(customer)

    breakdown = []
    for tt in settlement.findall(_r("ApplicableTradeTax")):
        breakdown.append({
            "taxableAmount": _text(tt, _r("BasisAmount")),
            "taxAmount": _text(tt, _r("CalculatedAmount")),
            "rate": _text(tt, _r("RateApplicablePercent")),
            "categoryId": _text(tt, _r("CategoryCode")),
        })
    summation = settlement.find(_r("SpecifiedTradeSettlementHeaderMonetarySummation"))
    tax_summary = UDEREntity(
        entity_id=f"urn:taxsummary:{number}", entity_type="TaxSummary",
        representation="cii", source_standard="UNCEFACT-CII-100",
        properties={"taxAmount": _text(summation, _r("TaxTotalAmount")), "breakdown": breakdown},
    )
    graph.add(tax_summary)

    pm = settlement.find(_r("SpecifiedTradeSettlementPaymentMeans"))
    payment = UDEREntity(
        entity_id=f"urn:payment:{number}", entity_type="PaymentInformation",
        representation="cii", source_standard="UNCEFACT-CII-100",
        properties={
            "means": _text(pm, _r("TypeCode")) if pm is not None else None,
            "reference": _text(settlement, _r("PaymentReference")),
            "account": _text(pm, f"{_r('PayeePartyCreditorFinancialAccount')}/{_r('IBANID')}") if pm is not None else None,
        },
    )
    graph.add(payment)

    line_ids = []
    for line_el in txn.findall(_r("IncludedSupplyChainTradeLineItem")):
        line_id = _text(line_el, f"{_r('AssociatedDocumentLineDocument')}/{_r('LineID')}")
        product = line_el.find(_r("SpecifiedTradeProduct"))
        identifiers = []
        global_id = product.find(_r("GlobalID")) if product is not None else None
        if global_id is not None and global_id.text:
            identifiers.append({"scheme": "GTIN", "value": global_id.text.strip()})
        seller_id = product.find(_r("SellerAssignedID")) if product is not None else None
        if seller_id is not None and seller_id.text:
            identifiers.append({"scheme": "SKU", "value": seller_id.text.strip()})

        product_entity_id = f"urn:product:{number}:{line_id}"
        graph.add(UDEREntity(entity_id=product_entity_id, entity_type="Product",
                              representation="cii", source_standard="UNCEFACT-CII-100",
                              properties={"name": _text(product, _r("Name")) if product is not None else None,
                                          "identifiers": identifiers}))

        settlement_line = line_el.find(_r("SpecifiedLineTradeSettlement"))
        tax_el = settlement_line.find(_r("ApplicableTradeTax")) if settlement_line is not None else None
        delivery = line_el.find(_r("SpecifiedLineTradeDelivery"))
        qty_el = delivery.find(_r("BilledQuantity")) if delivery is not None else None
        price_el = line_el.find(f"{_r('SpecifiedLineTradeAgreement')}/{_r('NetPriceProductTradePrice')}/{_r('ChargeAmount')}")
        line_total = settlement_line.find(f"{_r('SpecifiedTradeSettlementLineMonetarySummation')}/{_r('LineTotalAmount')}") if settlement_line is not None else None

        allowances = []
        if settlement_line is not None:
            for ac in settlement_line.findall(_r("SpecifiedTradeAllowanceCharge")):
                indicator = _text(ac, f"{_r('ChargeIndicator')}/{{{UDT}}}Indicator")
                allowances.append({"isCharge": indicator == "true", "amount": _text(ac, _r("ActualAmount"))})

        line_entity_id = f"urn:line:{number}:{line_id}"
        graph.add(UDEREntity(
            entity_id=line_entity_id, entity_type="InvoiceLine",
            representation="cii", source_standard="UNCEFACT-CII-100",
            properties={
                "quantity": qty_el.text if qty_el is not None else None,
                "unit": qty_el.get("unitCode") if qty_el is not None else None,
                "unitPrice": price_el.text if price_el is not None else None,
                "netAmount": line_total.text if line_total is not None else None,
                "allowanceCharge": allowances,
                "taxRate": _text(tax_el, _r("RateApplicablePercent")) if tax_el is not None else None,
                "taxCategory": _text(tax_el, _r("CategoryCode")) if tax_el is not None else None,
                "exemptionReason": _text(tax_el, _r("ExemptionReason")) if tax_el is not None else None,
            },
            links=[UDERLink("hasProduct", product_entity_id)],
        ))
        line_ids.append(line_entity_id)

    links = [UDERLink("hasSupplier", supplier.entity_id), UDERLink("hasCustomer", customer.entity_id)]
    links += [UDERLink("hasLine", lid) for lid in line_ids]
    links.append(UDERLink("hasTaxSummary", tax_summary.entity_id))
    links.append(UDERLink("hasPayment", payment.entity_id))

    due_date = _text(settlement, f"{_r('SpecifiedTradePaymentTerms')}/{_r('DueDateDateTime')}/{{{UDT}}}DateTimeString")
    invoice_props = {
        "number": number,
        "issueDate": _text(root, f"{_s('ExchangedDocument')}/{_r('IssueDateTime')}/{{{UDT}}}DateTimeString"),
        "dueDate": due_date,
        "currency": _text(settlement, _r("InvoiceCurrencyCode")),
        "purchaseOrderReference": _text(agreement, f"{_r('BuyerOrderReferencedDocument')}/{_r('IssuerAssignedID')}"),
        "contractReference": _text(agreement, f"{_r('ContractReferencedDocument')}/{_r('IssuerAssignedID')}"),
        "netAmount": _text(summation, _r("TaxBasisTotalAmount")),
        "taxInclusiveAmount": _text(summation, _r("GrandTotalAmount")),
        "allowanceTotalAmount": _text(summation, _r("AllowanceTotalAmount")),
        "chargeTotalAmount": _text(summation, _r("ChargeTotalAmount")),
        "payableAmount": _text(summation, _r("DuePayableAmount")),
    }
    graph.add(UDEREntity(entity_id=invoice_id, entity_type="Invoice", representation="cii",
                          source_standard="UNCEFACT-CII-100", properties=invoice_props, links=links))
    return graph
