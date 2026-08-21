"""Merges independent per-entity transform outputs for the 'isolated' experiment mode (Baseline 2).

Each UDER entity is transformed on its own, with no context from linked
entities (spec Section 12, Experiment A). Only a call that included the
Invoice root entity can produce a structurally complete CanonicalInvoice; the
rest legitimately contribute nothing, which is itself the finding this
baseline is meant to surface (isolated transformation loses everything an
aggregated context would have supplied). Merging simply prefers whichever
partial is more informative field-by-field.
"""
from __future__ import annotations

_PLACEHOLDER_STRINGS = {"UNKNOWN", ""}


def _is_informative(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value not in _PLACEHOLDER_STRINGS
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


def merge_values(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return {k: merge_values(a.get(k), b.get(k)) for k in (set(a) | set(b))}
    if isinstance(a, list) and isinstance(b, list):
        return b if len(b) > len(a) else a
    if _is_informative(b) and not _is_informative(a):
        return b
    return a


def merge_partial_canonicals(partials: list[dict]) -> dict:
    non_empty = [p for p in partials if p]
    if not non_empty:
        return {}
    merged = non_empty[0]
    for p in non_empty[1:]:
        merged = merge_values(merged, p)
    return merged
