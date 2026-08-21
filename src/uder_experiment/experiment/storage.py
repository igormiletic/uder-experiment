"""Result persistence: JSONL (spec Section 19). Source of truth for reproducible analysis/figures."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class ExperimentRecord:
    experiment_id: str
    timestamp: str
    source_standard: str
    invoice_scenario_id: str
    complexity_level: str
    transaction_id: str
    transformation_mode: str
    ai_model: str
    prompt_version: str
    temperature: float
    source_entity_count: int
    received_entity_count: int
    duplicate_count: int
    missing_entity_count: int
    semantic_preservation: float
    information_loss: float
    semantic_precision: float
    semantic_f1: float
    value_accuracy: float
    global_confidence: float
    brier_score: float
    calibration_error: float
    schema_valid: bool
    consistency_score: float
    latency_total_ms: float
    latency_aggregation_ms: float
    latency_ai_ms: float
    accepted: bool
    error: str | None = None


@dataclass
class FieldResultRecord:
    experiment_id: str
    path: str
    weight: float
    required: bool
    expected_value: str
    actual_value: str
    correct: bool
    field_confidence: float | None


class JSONLWriter:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")

    def write(self, record) -> None:
        payload = asdict(record) if not isinstance(record, dict) else record
        self._fh.write(json.dumps(payload, default=str) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def read_jsonl(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
