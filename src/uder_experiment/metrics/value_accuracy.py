"""Value accuracy comparison strategies (spec Section 13.5): exact / normalized / similarity.

Deliberately has zero AI involvement (spec Section 23): exact equality, string
normalization, and difflib-based sequence similarity are the only comparators.
"""
from __future__ import annotations

import difflib
import re

_WS_RE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    return _WS_RE.sub(" ", value.strip().lower())


def similarity_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def numbers_equal(expected: float, actual: float, relative_tolerance: float = 0.005, absolute_tolerance: float = 0.01) -> bool:
    diff = abs(expected - actual)
    return diff <= max(absolute_tolerance, relative_tolerance * max(1.0, abs(expected)))


def values_equal(
    expected,
    actual,
    value_type: str,
    text_strategy: str = "normalized",
    similarity_threshold: float = 0.85,
    numeric_relative_tolerance: float = 0.005,
) -> bool:
    """The single, deterministic correctness oracle used throughout the metrics engine."""
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False

    if value_type == "number":
        try:
            return numbers_equal(float(expected), float(actual), numeric_relative_tolerance)
        except (TypeError, ValueError):
            return False

    if value_type == "boolean":
        return bool(expected) == bool(actual)

    if value_type == "set":
        return set(expected) == set(actual)

    if value_type == "date":
        return str(expected).strip() == str(actual).strip()

    # string / free text
    if text_strategy == "exact":
        return str(expected) == str(actual)
    if text_strategy == "similarity":
        return similarity_ratio(str(expected), str(actual)) >= similarity_threshold
    return normalize_text(str(expected)) == normalize_text(str(actual))
