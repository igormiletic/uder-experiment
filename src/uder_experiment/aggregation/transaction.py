"""TransactionContext: C*(tau) = <E_tau, D_tau, P_tau> (spec Section 10)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from uder_experiment.uder.entities import UDEREntity


@dataclass
class ReceiptRecord:
    entity_id: str
    received_at: float
    is_duplicate: bool
    entity_type: str
    source_standard: str


@dataclass
class TransactionContext:
    transaction_id: str
    ldc_response_url: str
    expected_entity_ids: set[str] = field(default_factory=set)

    received_entities: dict[str, UDEREntity] = field(default_factory=dict)  # E_tau, deduped
    transformed_results: list[dict] = field(default_factory=list)  # D_tau (one per transform call)
    provenance: dict[str, list[ReceiptRecord]] = field(default_factory=dict)  # P_tau, includes duplicate receipts

    created_at: float = field(default_factory=time.monotonic)
    last_update_at: float = field(default_factory=time.monotonic)
    first_response_at: float | None = None
    last_entity_at: float | None = None

    total_received_count: int = 0  # includes duplicates
    duplicate_count: int = 0

    def record_receipt(self, entity: UDEREntity) -> bool:
        """Register an incoming entity. Returns True if this was a *new* (non-duplicate) entity."""
        now = time.monotonic()
        self.last_update_at = now
        self.total_received_count += 1
        is_duplicate = entity.entity_id in self.received_entities
        if is_duplicate:
            self.duplicate_count += 1
        else:
            self.received_entities[entity.entity_id] = entity
            self.last_entity_at = now
        self.provenance.setdefault(entity.entity_id, []).append(ReceiptRecord(
            entity_id=entity.entity_id, received_at=now, is_duplicate=is_duplicate,
            entity_type=entity.entity_type, source_standard=entity.source_standard,
        ))
        return not is_duplicate

    @property
    def completeness(self) -> float:
        if not self.expected_entity_ids:
            return 1.0 if self.received_entities else 0.0
        received_expected = len(set(self.received_entities) & self.expected_entity_ids)
        return received_expected / len(self.expected_entity_ids)

    @property
    def duplicate_rate(self) -> float:
        if self.total_received_count == 0:
            return 0.0
        unique = self.total_received_count - self.duplicate_count
        return (self.total_received_count - unique) / self.total_received_count

    @property
    def is_complete(self) -> bool:
        return self.completeness >= 1.0
