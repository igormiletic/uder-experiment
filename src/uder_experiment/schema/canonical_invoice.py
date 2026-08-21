"""CanonicalInvoice: the LDC's local data model (target of AI transformation).

Deliberately organized differently from UBL/CII/OAGIS: grouped by business
concern (identity, commercialContext, parties, items, financialSummary,
payment) rather than by document/party/line XML nesting. Versioned via
CANONICAL_INVOICE_SCHEMA_VERSION so experiment records can pin the schema
revision they were evaluated against.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


def _to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


class CanonicalModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel, extra="forbid")


CANONICAL_INVOICE_SCHEMA_VERSION = "1.0"


class Identifier(CanonicalModel):
    scheme: str
    value: str


class Address(CanonicalModel):
    street: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    country: str


class Party(CanonicalModel):
    name: str
    identifiers: list[Identifier] = Field(default_factory=list)
    address: Optional[Address] = None


class Parties(CanonicalModel):
    supplier: Party
    customer: Party


class Identity(CanonicalModel):
    number: str
    issue_date: str
    due_date: Optional[str] = None


class CommercialContext(CanonicalModel):
    currency: str
    purchase_order_reference: Optional[str] = None
    contract_reference: Optional[str] = None


class Quantity(CanonicalModel):
    value: float
    unit: str


class Product(CanonicalModel):
    name: str
    identifiers: list[Identifier] = Field(default_factory=list)


class Pricing(CanonicalModel):
    unit_price: float
    net_amount: float
    allowance_total: float = 0.0
    charge_total: float = 0.0


class Taxation(CanonicalModel):
    rate: float
    category: str = "VAT"
    exempt: bool = False
    exemption_reason: Optional[str] = None


class InvoiceLine(CanonicalModel):
    line_id: str
    product: Product
    quantity: Quantity
    pricing: Pricing
    taxation: Taxation


class TaxBreakdownEntry(CanonicalModel):
    category: str
    rate: float
    taxable_amount: float
    tax_amount: float


class FinancialSummary(CanonicalModel):
    net_amount: float
    tax_amount: float
    allowance_total: float = 0.0
    charge_total: float = 0.0
    gross_amount: float
    payable_amount: float
    tax_breakdown: list[TaxBreakdownEntry] = Field(default_factory=list)


class Payment(CanonicalModel):
    means: str = "BANK_TRANSFER"
    account: Optional[str] = None
    reference: Optional[str] = None


class InvoiceBody(CanonicalModel):
    identity: Identity
    commercial_context: CommercialContext
    parties: Parties
    items: list[InvoiceLine]
    financial_summary: FinancialSummary
    payment: Payment


class CanonicalInvoice(CanonicalModel):
    schema_version: str = CANONICAL_INVOICE_SCHEMA_VERSION
    invoice: InvoiceBody
