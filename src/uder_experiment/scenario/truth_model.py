"""InvoiceScenario: the single deterministic source of truth for a logical invoice.

Every source representation (UBL, CII, Source-C/OAGIS-JSON) and the ground-truth
CanonicalInvoice are pure renderings of one InvoiceScenario instance. None is
derived from another and none is derived from AI output -- this is what makes
the ground truth independent (spec Section 5).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

Complexity = Literal["simple", "medium", "complex"]

TWOPLACES = Decimal("0.01")


def q(value: Decimal) -> Decimal:
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


_SUPPLIER_NAMES = [
    "Danube Steelworks d.o.o.", "Alpine Precision Tools AG", "Nordic Timber Supply AB",
    "Balkan Logistics d.o.o.", "Rheinland Elektronik GmbH", "Adriatic Packaging Ltd",
    "Carpathian Machinery s.r.o.", "Iberia Textiles S.A.", "Baltic Components UAB",
    "Pannonia Chemicals Kft.", "Helvetia Fine Instruments AG", "Moravia Plastics a.s.",
]
_CUSTOMER_NAMES = [
    "Northgate Retail Ltd", "Meridian Manufacturing Inc", "Solaris Energy Group",
    "Blue Harbor Trading Co", "Continental Foods AG", "Vertex Construction plc",
    "Riverside Motors GmbH", "Highland Distribution Ltd", "Orion Pharmaceuticals SA",
    "Cedar Point Logistics", "Falcon Aerospace Ltd", "Summit Retail Holdings",
]
_CITIES = [
    ("Belgrade", "RS", "11000"), ("Zurich", "CH", "8000"), ("Berlin", "DE", "10115"),
    ("Vienna", "AT", "1010"), ("Zagreb", "HR", "10000"), ("Warsaw", "PL", "00-001"),
    ("Bratislava", "SK", "81101"), ("Ljubljana", "SI", "1000"), ("Budapest", "HU", "1051"),
    ("Prague", "CZ", "11000"), ("Vilnius", "LT", "01103"), ("Lisbon", "PT", "1100"),
]
_STREETS = ["Bulevar Oslobodjenja 98", "Industriestrasse 12", "Mainstrasse 1", "Rue de Commerce 45",
            "Via Roma 22", "Ulica Kralja Petra 5", "Fabricka 8", "Hafenstrasse 3"]
_PRODUCTS = [
    "Precision Bearing Set", "Aluminium Extrusion Profile", "Industrial Filter Cartridge",
    "Hydraulic Hose Assembly", "Steel Fastener Kit", "Circuit Protection Module",
    "Insulated Copper Cable (100m)", "Pallet Wrap Film Roll", "Safety Valve Assembly",
    "PVC Conduit Pipe", "LED Panel Light", "Industrial Gear Reducer",
]
_UNITS = ["EA", "KGM", "MTR", "BOX", "LTR"]
_TAX_CATEGORIES = [("Standard", 20.0), ("Reduced", 10.0), ("Super-Reduced", 5.0), ("ZeroRated", 0.0)]
_PAYMENT_MEANS = ["BANK_TRANSFER", "SEPA_CREDIT_TRANSFER", "CARD"]


@dataclass
class Identifier:
    scheme: str
    value: str


@dataclass
class PartyTruth:
    name: str
    country: str
    city: str
    postal_code: str
    street: str | None
    identifiers: list[Identifier] = field(default_factory=list)


@dataclass
class LineTruth:
    line_id: str
    product_name: str
    product_ids: list[Identifier]
    quantity: Decimal
    unit: str
    unit_price: Decimal
    allowance: Decimal
    charge: Decimal
    tax_category: str
    tax_rate: Decimal
    exempt: bool
    exemption_reason: str | None

    @property
    def gross_line_amount(self) -> Decimal:
        return self.quantity * self.unit_price

    @property
    def net_amount(self) -> Decimal:
        return q(self.gross_line_amount - self.allowance + self.charge)

    @property
    def tax_amount(self) -> Decimal:
        if self.exempt:
            return Decimal("0.00")
        return q(self.net_amount * self.tax_rate / Decimal(100))


@dataclass
class Totals:
    net_amount: Decimal
    tax_amount: Decimal
    allowance_total: Decimal
    charge_total: Decimal
    gross_amount: Decimal
    payable_amount: Decimal
    tax_breakdown: list[tuple[str, Decimal, Decimal, Decimal]]  # category, rate, taxable, tax


@dataclass
class InvoiceScenario:
    scenario_id: str
    complexity: Complexity
    seed: int
    number: str
    issue_date: date
    due_date: date | None
    currency: str
    supplier: PartyTruth
    customer: PartyTruth
    purchase_order_ref: str | None
    contract_ref: str | None
    lines: list[LineTruth]
    document_allowance: Decimal
    document_charge: Decimal
    payment_means: str
    payment_account: str | None
    payment_reference: str | None

    def totals(self) -> Totals:
        net = q(sum((l.net_amount for l in self.lines), Decimal("0.00")) - self.document_allowance + self.document_charge)
        breakdown: dict[tuple[str, Decimal], list[Decimal]] = {}
        for l in self.lines:
            key = (l.tax_category, l.tax_rate)
            breakdown.setdefault(key, [Decimal("0.00"), Decimal("0.00")])
            breakdown[key][0] = q(breakdown[key][0] + l.net_amount)
            breakdown[key][1] = q(breakdown[key][1] + l.tax_amount)
        tax_total = q(sum((v[1] for v in breakdown.values()), Decimal("0.00")))
        gross = q(net + tax_total)
        payable = gross
        tax_breakdown = [(cat, rate, taxable, tax) for (cat, rate), (taxable, tax) in breakdown.items()]
        return Totals(
            net_amount=net,
            tax_amount=tax_total,
            allowance_total=q(sum((l.allowance for l in self.lines), self.document_allowance)),
            charge_total=q(sum((l.charge for l in self.lines), self.document_charge)),
            gross_amount=gross,
            payable_amount=payable,
            tax_breakdown=tax_breakdown,
        )


def _party(rng: random.Random, names: list[str], with_identifiers: bool, include_street: bool = True) -> PartyTruth:
    name = rng.choice(names)
    city, country, postal = rng.choice(_CITIES)
    street = rng.choice(_STREETS) if include_street else None
    ids = []
    if with_identifiers:
        ids.append(Identifier("VAT", f"{country}{rng.randint(100000000, 999999999)}"))
    return PartyTruth(name=name, country=country, city=city, postal_code=postal, street=street, identifiers=ids)


def generate_scenario(index: int, seed: int, complexity: Complexity) -> InvoiceScenario:
    rng = random.Random(seed * 100_003 + index)
    scenario_id = f"scenario-{index:03d}"
    issue = date(2026, 1, 1) + timedelta(days=rng.randint(0, 260))

    if complexity == "simple":
        n_lines = 1
        due = issue + timedelta(days=30)
        supplier = _party(rng, _SUPPLIER_NAMES, with_identifiers=True)
        customer = _party(rng, _CUSTOMER_NAMES, with_identifiers=False)
        po_ref = None
        contract_ref = None
        doc_allowance = Decimal("0.00")
        doc_charge = Decimal("0.00")
    elif complexity == "medium":
        n_lines = rng.randint(2, 4)
        due = issue + timedelta(days=rng.choice([14, 30, 45]))
        supplier = _party(rng, _SUPPLIER_NAMES, with_identifiers=True)
        customer = _party(rng, _CUSTOMER_NAMES, with_identifiers=True)
        po_ref = f"PO-{rng.randint(100000, 999999)}"
        contract_ref = None
        doc_allowance = q(Decimal(rng.uniform(0, 25))) if rng.random() < 0.5 else Decimal("0.00")
        doc_charge = q(Decimal(rng.uniform(0, 15))) if rng.random() < 0.3 else Decimal("0.00")
    else:  # complex
        n_lines = rng.randint(3, 6)
        due = issue + timedelta(days=rng.choice([14, 30, 45, 60])) if rng.random() < 0.8 else None
        supplier = _party(rng, _SUPPLIER_NAMES, with_identifiers=True, include_street=True)
        customer = _party(rng, _CUSTOMER_NAMES, with_identifiers=True, include_street=rng.random() < 0.6)
        po_ref = f"PO-{rng.randint(100000, 999999)}"
        contract_ref = f"CTR-{rng.randint(1000, 9999)}" if rng.random() < 0.7 else None
        doc_allowance = q(Decimal(rng.uniform(5, 60)))
        doc_charge = q(Decimal(rng.uniform(0, 30))) if rng.random() < 0.6 else Decimal("0.00")

    currency = "EUR"

    lines: list[LineTruth] = []
    for i in range(n_lines):
        product = rng.choice(_PRODUCTS)
        qty = Decimal(rng.randint(1, 50))
        unit = rng.choice(_UNITS)
        price = q(Decimal(rng.uniform(3.5, 480.0)) if complexity != "complex" else Decimal(rng.uniform(3.333, 480.777)))

        product_ids = [Identifier("SKU", f"SKU-{rng.randint(10000, 99999)}")]
        if complexity != "simple" and rng.random() < 0.6:
            product_ids.append(Identifier("GTIN", f"{rng.randint(10**12, 10**13 - 1)}"))

        if complexity == "simple":
            cat, rate = "Standard", Decimal("20.0")
            exempt = False
            exemption_reason = None
            allowance = Decimal("0.00")
            charge = Decimal("0.00")
        elif complexity == "medium":
            cat, rate = rng.choice(_TAX_CATEGORIES[:2])
            rate = Decimal(str(rate))
            exempt = False
            exemption_reason = None
            allowance = q(Decimal(rng.uniform(0, float(qty * price * Decimal("0.1"))))) if rng.random() < 0.3 else Decimal("0.00")
            charge = Decimal("0.00")
        else:
            cat, rate = rng.choice(_TAX_CATEGORIES)
            rate = Decimal(str(rate))
            exempt = cat == "ZeroRated" or rng.random() < 0.15
            exemption_reason = "Intra-community supply, Art. 138 VAT Directive" if exempt and cat != "ZeroRated" else None
            if exempt and rate != 0:
                rate = Decimal("0.0")
            allowance = q(Decimal(rng.uniform(0, float(qty * price) * 0.15))) if rng.random() < 0.5 else Decimal("0.00")
            charge = q(Decimal(rng.uniform(0, 20))) if rng.random() < 0.3 else Decimal("0.00")

        lines.append(LineTruth(
            line_id=str(i + 1), product_name=product, product_ids=product_ids,
            quantity=qty, unit=unit, unit_price=price, allowance=allowance, charge=charge,
            tax_category=cat, tax_rate=rate, exempt=exempt, exemption_reason=exemption_reason,
        ))

    payment_means = rng.choice(_PAYMENT_MEANS) if complexity != "simple" else "BANK_TRANSFER"
    payment_account = f"CH{rng.randint(10, 99)}00{rng.randint(1000000000000, 9999999999999)}" if complexity != "simple" or rng.random() < 0.8 else None
    payment_reference = f"RF{rng.randint(10000000, 99999999)}" if complexity == "complex" else None

    return InvoiceScenario(
        scenario_id=scenario_id, complexity=complexity, seed=seed, number=f"INV-2026-{index:04d}",
        issue_date=issue, due_date=due, currency=currency, supplier=supplier, customer=customer,
        purchase_order_ref=po_ref, contract_ref=contract_ref, lines=lines,
        document_allowance=doc_allowance, document_charge=doc_charge,
        payment_means=payment_means, payment_account=payment_account, payment_reference=payment_reference,
    )
