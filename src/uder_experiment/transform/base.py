"""Transformer interface (spec Section 11): transform(uder_entities, target_schema, context) -> TransformResult."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from uder_experiment.schema.json_schema import validate_canonical_invoice
from uder_experiment.transform.context import TransformationContext
from uder_experiment.uder.entities import UDEREntity


@dataclass
class TransformResult:
    transformed_data: dict
    confidence: float  # C_global -- a *confidence estimate*, not a calibrated probability unless noted
    field_confidences: dict[str, float] = field(default_factory=dict)  # C_f per target feature path
    provenance: dict[str, str] = field(default_factory=dict)  # target feature path -> source UDER entity id
    metadata: dict = field(default_factory=dict)
    schema_valid: bool = False
    validation_errors: list[str] = field(default_factory=list)
    latency_ms: float = 0.0

    def validate(self) -> None:
        ok, errors = validate_canonical_invoice(self.transformed_data)
        self.schema_valid = ok
        self.validation_errors = errors


class Transformer(ABC):
    name: str = "base"

    @abstractmethod
    async def transform(self, uder_entities: list[UDEREntity], target_schema: dict,
                         context: TransformationContext) -> TransformResult:
        ...
