"""Parse the OAGIS-normalized JSON invoice (Source C) into a UDER entity graph."""
from __future__ import annotations

from uder_experiment.uder.entities import UDEREntity, UDERGraph, UDERLink


def _party(party: dict, number: str, role: str) -> UDEREntity:
    address = party.get("Location", {}).get("Address", {})
    properties = {
        "name": party.get("Name"),
        "identifiers": [{"scheme": pid.get("type"), "value": pid.get("ID")} for pid in party.get("PartyIDs", [])],
        "address": {
            "street": address.get("Street"),
            "city": address.get("City"),
            "postalCode": address.get("PostalCode"),
            "country": address.get("CountryCode"),
        },
    }
    return UDEREntity(entity_id=f"urn:party:{number}:{role}", entity_type="Party",
                       representation="source-c", source_standard="OAGIS-9-JSON", properties=properties)


def parse_source_c_to_uder(data: dict) -> UDERGraph:
    header = data["DataArea"]["Invoice"]["InvoiceHeader"]
    lines_data = data["DataArea"]["Invoice"]["InvoiceLine"]
    number = header["DocumentID"]["ID"]
    invoice_id = f"urn:invoice:{number}"
    graph = UDERGraph(root_entity_id=invoice_id)

    supplier = _party(header["SellerParty"], number, "supplier")
    customer = _party(header["BuyerParty"], number, "customer")
    graph.add(supplier)
    graph.add(customer)

    breakdown = [
        {"taxableAmount": t["TaxableAmount"], "taxAmount": t["TaxAmount"], "rate": t["Percent"], "categoryId": t["CategoryCode"]}
        for t in header.get("TaxSummary", [])
    ]
    tax_summary = UDEREntity(
        entity_id=f"urn:taxsummary:{number}", entity_type="TaxSummary",
        representation="source-c", source_standard="OAGIS-9-JSON",
        properties={"taxAmount": header["TotalAmount"]["TaxTotalAmount"], "breakdown": breakdown},
    )
    graph.add(tax_summary)

    pt = header.get("PaymentTerm", {})
    payment = UDEREntity(
        entity_id=f"urn:payment:{number}", entity_type="PaymentInformation",
        representation="source-c", source_standard="OAGIS-9-JSON",
        properties={
            "means": pt.get("PaymentMeansCode"),
            "account": pt.get("PayerFinancialAccount", {}).get("ID"),
            "reference": pt.get("PaymentReference"),
        },
    )
    graph.add(payment)

    line_ids = []
    for line in lines_data:
        line_id = line["LineNumber"]
        item = line["Item"]
        identifiers = [{"scheme": iid.get("type"), "value": iid.get("ID")} for iid in item.get("ItemID", [])]
        product_entity_id = f"urn:product:{number}:{line_id}"
        graph.add(UDEREntity(entity_id=product_entity_id, entity_type="Product",
                              representation="source-c", source_standard="OAGIS-9-JSON",
                              properties={"name": item.get("Description"), "identifiers": identifiers}))

        tax_cat = line.get("TaxCategory", {})
        qty = line.get("Quantity", {})
        allowances = [{"isCharge": ac["Indicator"] == "Charge", "amount": ac["Amount"]} for ac in line.get("AllowanceCharge", [])]

        line_entity_id = f"urn:line:{number}:{line_id}"
        graph.add(UDEREntity(
            entity_id=line_entity_id, entity_type="InvoiceLine",
            representation="source-c", source_standard="OAGIS-9-JSON",
            properties={
                "quantity": qty.get("value"), "unit": qty.get("uom"),
                "unitPrice": line.get("UnitPrice", {}).get("Amount"),
                "netAmount": line.get("LineExtensionAmount"),
                "allowanceCharge": allowances,
                "taxRate": tax_cat.get("Percent"), "taxCategory": tax_cat.get("CategoryCode"),
                "exempt": tax_cat.get("Exempt"), "exemptionReason": tax_cat.get("ExemptionReason"),
            },
            links=[UDERLink("hasProduct", product_entity_id)],
        ))
        line_ids.append(line_entity_id)

    links = [UDERLink("hasSupplier", supplier.entity_id), UDERLink("hasCustomer", customer.entity_id)]
    links += [UDERLink("hasLine", lid) for lid in line_ids]
    links.append(UDERLink("hasTaxSummary", tax_summary.entity_id))
    links.append(UDERLink("hasPayment", payment.entity_id))

    total = header["TotalAmount"]
    invoice_props = {
        "number": number,
        "issueDate": header.get("DocumentDateTime"),
        "dueDate": header.get("DueDateTime"),
        "currency": header.get("CurrencyCode"),
        "purchaseOrderReference": header.get("ReferenceDocumentID"),
        "contractReference": header.get("ContractReferenceDocumentID"),
        "netAmount": total.get("LineTotalAmount"),
        "taxInclusiveAmount": total.get("GrossAmount"),
        "allowanceTotalAmount": total.get("AllowanceTotalAmount"),
        "chargeTotalAmount": total.get("ChargeTotalAmount"),
        "payableAmount": total.get("PayableAmount"),
    }
    graph.add(UDEREntity(entity_id=invoice_id, entity_type="Invoice", representation="source-c",
                          source_standard="OAGIS-9-JSON", properties=invoice_props, links=links))
    return graph
