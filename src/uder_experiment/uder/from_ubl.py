"""Parse a rendered UBL 2.1 Invoice XML document into a UDER entity graph.

Produces the graph shape described in spec Section 8:
Invoice -[hasSupplier/hasCustomer]-> Party
Invoice -[hasLine]-> InvoiceLine -[hasProduct]-> Product
Invoice -[hasTaxSummary]-> TaxSummary
Invoice -[hasPayment]-> PaymentInformation
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from uder_experiment.uder.entities import UDEREntity, UDERGraph, UDERLink

CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"


def _c(tag: str) -> str:
    return f"{{{CBC}}}{tag}"


def _a(tag: str) -> str:
    return f"{{{CAC}}}{tag}"


def _text(el, path, default=None):
    found = el.find(path)
    return found.text.strip() if found is not None and found.text else default


def _parse_party(party_el, number: str, role: str) -> UDEREntity:
    party = party_el.find(_a("Party"))
    name = _text(party, f"{_a('PartyName')}/{_c('Name')}")
    addr = party.find(_a("PostalAddress"))
    identifiers = []
    tax_scheme = party.find(_a("PartyTaxScheme"))
    if tax_scheme is not None:
        vat = _text(tax_scheme, _c("CompanyID"))
        if vat:
            identifiers.append({"scheme": "VAT", "value": vat})
    properties = {
        "name": name,
        "identifiers": identifiers,
        "address": {
            "street": _text(addr, _c("StreetName")) if addr is not None else None,
            "city": _text(addr, _c("CityName")) if addr is not None else None,
            "postalCode": _text(addr, _c("PostalZone")) if addr is not None else None,
            "country": _text(addr, f"{_a('Country')}/{_c('IdentificationCode')}") if addr is not None else None,
        },
    }
    return UDEREntity(entity_id=f"urn:party:{number}:{role}", entity_type="Party",
                       representation="ubl", source_standard="UBL-2.1", properties=properties)


def parse_ubl_to_uder(xml_text: str) -> UDERGraph:
    root = ET.fromstring(xml_text)
    number = _text(root, _c("ID"))
    invoice_id = f"urn:invoice:{number}"
    graph = UDERGraph(root_entity_id=invoice_id)

    supplier_el = root.find(_a("AccountingSupplierParty"))
    customer_el = root.find(_a("AccountingCustomerParty"))
    supplier = _parse_party(supplier_el, number, "supplier")
    customer = _parse_party(customer_el, number, "customer")
    graph.add(supplier)
    graph.add(customer)

    line_ids = []
    tax_total_amount = _text(root, f"{_a('TaxTotal')}/{_c('TaxAmount')}")
    breakdown = []
    for sub in root.findall(f"{_a('TaxTotal')}/{_a('TaxSubtotal')}"):
        cat = sub.find(_a("TaxCategory"))
        breakdown.append({
            "taxableAmount": _text(sub, _c("TaxableAmount")),
            "taxAmount": _text(sub, _c("TaxAmount")),
            "rate": _text(cat, _c("Percent")),
            "categoryId": _text(cat, _c("ID")),
        })
    tax_summary = UDEREntity(
        entity_id=f"urn:taxsummary:{number}", entity_type="TaxSummary",
        representation="ubl", source_standard="UBL-2.1",
        properties={"taxAmount": tax_total_amount, "breakdown": breakdown},
    )
    graph.add(tax_summary)

    pm = root.find(_a("PaymentMeans"))
    payment = UDEREntity(
        entity_id=f"urn:payment:{number}", entity_type="PaymentInformation",
        representation="ubl", source_standard="UBL-2.1",
        properties={
            "means": _text(pm, _c("PaymentMeansCode")) if pm is not None else None,
            "reference": _text(pm, _c("PaymentID")) if pm is not None else None,
            "account": _text(pm, f"{_a('PayeeFinancialAccount')}/{_c('ID')}") if pm is not None else None,
        },
    )
    graph.add(payment)

    for line_el in root.findall(_a("InvoiceLine")):
        line_id = _text(line_el, _c("ID"))
        item = line_el.find(_a("Item"))
        product_name = _text(item, _c("Name")) if item is not None else None
        identifiers = []
        sku = item.find(f"{_a('SellersItemIdentification')}/{_c('ID')}") if item is not None else None
        if sku is not None and sku.text:
            identifiers.append({"scheme": "SKU", "value": sku.text.strip()})
        std_id = item.find(f"{_a('StandardItemIdentification')}/{_c('ID')}") if item is not None else None
        if std_id is not None and std_id.text:
            identifiers.append({"scheme": std_id.get("schemeID", "GTIN"), "value": std_id.text.strip()})

        product_entity_id = f"urn:product:{number}:{line_id}"
        graph.add(UDEREntity(entity_id=product_entity_id, entity_type="Product",
                              representation="ubl", source_standard="UBL-2.1",
                              properties={"name": product_name, "identifiers": identifiers}))

        tax_cat = item.find(_a("ClassifiedTaxCategory")) if item is not None else None
        qty_el = line_el.find(_c("InvoicedQuantity"))
        price_el = line_el.find(f"{_a('Price')}/{_c('PriceAmount')}")
        allowances = []
        for ac in line_el.findall(_a("AllowanceCharge")):
            allowances.append({
                "isCharge": _text(ac, _c("ChargeIndicator")) == "true",
                "amount": _text(ac, _c("Amount")),
            })

        line_entity_id = f"urn:line:{number}:{line_id}"
        graph.add(UDEREntity(
            entity_id=line_entity_id, entity_type="InvoiceLine",
            representation="ubl", source_standard="UBL-2.1",
            properties={
                "quantity": qty_el.text if qty_el is not None else None,
                "unit": qty_el.get("unitCode") if qty_el is not None else None,
                "unitPrice": price_el.text if price_el is not None else None,
                "netAmount": _text(line_el, _c("LineExtensionAmount")),
                "allowanceCharge": allowances,
                "taxRate": _text(tax_cat, _c("Percent")) if tax_cat is not None else None,
                "taxCategory": _text(tax_cat, _c("ID")) if tax_cat is not None else None,
                "exemptionReason": _text(tax_cat, _c("TaxExemptionReasonCode")) if tax_cat is not None else None,
            },
            links=[UDERLink("hasProduct", product_entity_id)],
        ))
        line_ids.append(line_entity_id)

    links = [UDERLink("hasSupplier", supplier.entity_id), UDERLink("hasCustomer", customer.entity_id)]
    links += [UDERLink("hasLine", lid) for lid in line_ids]
    links.append(UDERLink("hasTaxSummary", tax_summary.entity_id))
    links.append(UDERLink("hasPayment", payment.entity_id))

    invoice_props = {
        "number": number,
        "issueDate": _text(root, _c("IssueDate")),
        "dueDate": _text(root, _c("DueDate")),
        "currency": _text(root, _c("DocumentCurrencyCode")),
        "purchaseOrderReference": _text(root, f"{_a('OrderReference')}/{_c('ID')}"),
        "contractReference": _text(root, f"{_a('ContractDocumentReference')}/{_c('ID')}"),
        "netAmount": _text(root, f"{_a('LegalMonetaryTotal')}/{_c('LineExtensionAmount')}"),
        "taxInclusiveAmount": _text(root, f"{_a('LegalMonetaryTotal')}/{_c('TaxInclusiveAmount')}"),
        "allowanceTotalAmount": _text(root, f"{_a('LegalMonetaryTotal')}/{_c('AllowanceTotalAmount')}"),
        "chargeTotalAmount": _text(root, f"{_a('LegalMonetaryTotal')}/{_c('ChargeTotalAmount')}"),
        "payableAmount": _text(root, f"{_a('LegalMonetaryTotal')}/{_c('PayableAmount')}"),
    }
    graph.add(UDEREntity(entity_id=invoice_id, entity_type="Invoice", representation="ubl",
                          source_standard="UBL-2.1", properties=invoice_props, links=links))
    return graph
