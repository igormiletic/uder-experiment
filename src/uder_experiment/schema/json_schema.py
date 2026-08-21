"""JSON Schema export for CanonicalInvoice, used for structured-output validation."""
from __future__ import annotations

import json
from pathlib import Path

from uder_experiment.schema.canonical_invoice import CanonicalInvoice


def canonical_invoice_json_schema() -> dict:
    return CanonicalInvoice.model_json_schema(by_alias=True)


def write_json_schema(path: str | Path) -> None:
    Path(path).write_text(json.dumps(canonical_invoice_json_schema(), indent=2))


def validate_canonical_invoice(data: dict) -> tuple[bool, list[str]]:
    """Strict pydantic validation. Returns (is_valid, error_messages)."""
    try:
        CanonicalInvoice.model_validate(data)
        return True, []
    except Exception as exc:  # pydantic.ValidationError
        return False, [str(exc)]
