"""LDCAggregator: correlates entity fragments by X-Transaction-ID, dedups, tracks provenance,
and drives incremental vs. final transformation (spec Section 10)."""
from __future__ import annotations

from typing import Awaitable, Callable

from uder_experiment.aggregation.transaction import TransactionContext
from uder_experiment.uder.entities import UDEREntity

OnEntityCallback = Callable[[TransactionContext, UDEREntity], Awaitable[None]]


class LDCAggregator:
    def __init__(self) -> None:
        self._transactions: dict[str, TransactionContext] = {}
        self._on_entity_callbacks: dict[str, OnEntityCallback] = {}

    def start_transaction(self, transaction_id: str, ldc_response_url: str,
                           expected_entity_ids: set[str] | None = None) -> TransactionContext:
        ctx = TransactionContext(transaction_id=transaction_id, ldc_response_url=ldc_response_url,
                                  expected_entity_ids=expected_entity_ids or set())
        self._transactions[transaction_id] = ctx
        return ctx

    def get(self, transaction_id: str) -> TransactionContext | None:
        return self._transactions.get(transaction_id)

    def get_or_create(self, transaction_id: str, ldc_response_url: str = "") -> TransactionContext:
        if transaction_id not in self._transactions:
            return self.start_transaction(transaction_id, ldc_response_url)
        return self._transactions[transaction_id]

    def register_incremental_callback(self, transaction_id: str, callback: OnEntityCallback) -> None:
        """Enables 'incremental transformation with refinement': callback fires on every new entity."""
        self._on_entity_callbacks[transaction_id] = callback

    async def receive_entity(self, transaction_id: str, entity: UDEREntity, ldc_response_url: str = "") -> bool:
        ctx = self.get_or_create(transaction_id, ldc_response_url)
        is_new = ctx.record_receipt(entity)
        if is_new and transaction_id in self._on_entity_callbacks:
            await self._on_entity_callbacks[transaction_id](ctx, entity)
        return is_new

    def all_transactions(self) -> list[TransactionContext]:
        return list(self._transactions.values())
