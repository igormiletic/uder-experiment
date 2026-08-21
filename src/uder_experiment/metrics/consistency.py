"""Deterministic arithmetic / invoice-consistency validation (spec Section 24).

Operates purely on a transformed CanonicalInvoice's own numbers -- no ground
truth required -- so it can contribute to transformation validation and
confidence estimation even when no reference is available.

Note on allowances/charges: in this framework's CanonicalInvoice convention,
line and document-level allowances/charges are already netted into
pricing.netAmount / financialSummary.netAmount (see
scenario/truth_model.py:InvoiceScenario.totals()). financialSummary
allowanceTotal/chargeTotal are informational sums, not amounts still to be
applied -- so PayableAmount reconciles directly against GrossAmount rather
than GrossAmount + Charges - Allowances.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from uder_experiment.metrics.value_accuracy import numbers_equal


@dataclass
class ConsistencyCheck:
    name: str
    expected: float
    actual: float
    passed: bool
    diff: float


@dataclass
class ConsistencyReport:
    checks: list[ConsistencyCheck] = field(default_factory=list)

    @property
    def score(self) -> float:
        return sum(1 for c in self.checks if c.passed) / len(self.checks) if self.checks else 1.0

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)


def _num(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def check_invoice_consistency(canonical: dict, tolerance: float = 0.02) -> ConsistencyReport:
    report = ConsistencyReport()
    invoice = canonical.get("invoice", canonical) if canonical else {}
    if not invoice:
        return report

    for item in invoice.get("items", []) or []:
        qty = _num(item.get("quantity", {}).get("value"))
        unit_price = _num(item.get("pricing", {}).get("unitPrice"))
        allowance = _num(item.get("pricing", {}).get("allowanceTotal"))
        charge = _num(item.get("pricing", {}).get("chargeTotal"))
        actual_net = _num(item.get("pricing", {}).get("netAmount"))
        expected_net = qty * unit_price - allowance + charge
        line_id = item.get("lineId", "?")
        report.checks.append(_check(f"line[{line_id}].netAmount", expected_net, actual_net, tolerance))

    fs = invoice.get("financialSummary", {}) or {}
    for entry in fs.get("taxBreakdown", []) or []:
        taxable = _num(entry.get("taxableAmount"))
        rate = _num(entry.get("rate"))
        actual_tax = _num(entry.get("taxAmount"))
        expected_tax = taxable * rate / 100.0
        cat = entry.get("category", "?")
        report.checks.append(_check(f"taxBreakdown[{cat}].taxAmount", expected_tax, actual_tax, tolerance))

    net = _num(fs.get("netAmount"))
    tax = _num(fs.get("taxAmount"))
    gross = _num(fs.get("grossAmount"))
    payable = _num(fs.get("payableAmount"))
    report.checks.append(_check("financialSummary.grossAmount", net + tax, gross, tolerance))
    report.checks.append(_check("financialSummary.payableAmount", gross, payable, tolerance))

    return report


def _check(name: str, expected: float, actual: float, tolerance: float) -> ConsistencyCheck:
    passed = numbers_equal(expected, actual, relative_tolerance=tolerance, absolute_tolerance=max(0.02, tolerance))
    return ConsistencyCheck(name=name, expected=round(expected, 2), actual=round(actual, 2),
                             passed=passed, diff=round(abs(expected - actual), 2))
