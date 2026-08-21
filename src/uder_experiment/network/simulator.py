"""Wires N simulated UCS instances + one LDC callback endpoint together and drives one transaction.

Distributes the UDER entity graph across 5 UCS node roles (spec Section 9 example):
  ucs-1: Invoice (root)         ucs-2: supplier Party        ucs-3: customer Party
  ucs-4: InvoiceLine + Product  ucs-5: TaxSummary + PaymentInformation

All communication happens over httpx.ASGITransport per node (real ASGI request/response
cycle, real headers, no sockets), routed by a small multi-host transport.
"""
from __future__ import annotations

import uuid

import httpx
from fastapi import FastAPI

from uder_experiment.aggregation.ldc_aggregator import LDCAggregator
from uder_experiment.aggregation.transaction import TransactionContext
from uder_experiment.network.ldc_callback import build_ldc_callback_app
from uder_experiment.network.ucs_node import (
    RESPONSE_URL_HEADER, TXN_HEADER, TaskRegistry, UCSNodeConfig, build_ucs_app,
)
from uder_experiment.uder.entities import UDEREntity, UDERGraph

NODE_ORDER = ["ucs-1", "ucs-2", "ucs-3", "ucs-4", "ucs-5"]


class MultiASGITransport(httpx.AsyncBaseTransport):
    """Routes requests to the FastAPI app registered for request.url.host."""

    def __init__(self, apps_by_host: dict[str, FastAPI]) -> None:
        self._transports = {host: httpx.ASGITransport(app=app) for host, app in apps_by_host.items()}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        transport = self._transports.get(host)
        if transport is None:
            raise RuntimeError(f"MultiASGITransport: no UCS/LDC app registered for host {host!r}")
        return await transport.handle_async_request(request)


def partition_graph(graph: UDERGraph) -> dict[str, list[UDEREntity]]:
    buckets: dict[str, list[UDEREntity]] = {n: [] for n in NODE_ORDER}
    for entity in graph.all():
        if entity.entity_type == "Invoice":
            buckets["ucs-1"].append(entity)
        elif entity.entity_type == "Party" and entity.entity_id.endswith(":supplier"):
            buckets["ucs-2"].append(entity)
        elif entity.entity_type == "Party":
            buckets["ucs-3"].append(entity)
        elif entity.entity_type in ("InvoiceLine", "Product"):
            buckets["ucs-4"].append(entity)
        else:  # TaxSummary, PaymentInformation
            buckets["ucs-5"].append(entity)
    return buckets


class SimulatedNetwork:
    """A built, ready-to-use network for one or more transactions against the same graph."""

    def __init__(self, graph: UDERGraph, fault_config: dict[str, UCSNodeConfig] | None = None) -> None:
        self.graph = graph
        self.tasks = TaskRegistry()
        self.aggregator = LDCAggregator()

        partition = partition_graph(graph)
        base_urls = {nid: f"http://{nid}" for nid in NODE_ORDER}
        registry: dict[str, str] = {}
        configs: dict[str, UCSNodeConfig] = {}
        for nid, entities in partition.items():
            cfg = (fault_config or {}).get(nid) or UCSNodeConfig(node_id=nid, base_url=base_urls[nid])
            cfg.node_id = nid
            cfg.base_url = base_urls[nid]
            cfg.entities = {e.entity_id: e for e in entities}
            configs[nid] = cfg
            for e in entities:
                registry[e.entity_id] = base_urls[nid]
        self.registry = registry

        apps: dict[str, FastAPI] = {nid: build_ucs_app(configs[nid], registry, self.tasks) for nid in NODE_ORDER}
        callback_app = build_ldc_callback_app(self.aggregator)
        apps_by_host = dict(apps)
        apps_by_host["ldc-callback"] = callback_app

        self.client = httpx.AsyncClient(transport=MultiASGITransport(apps_by_host))
        for app in apps_by_host.values():
            app.state.http_client = self.client

        self.response_url = "http://ldc-callback/callback"

    async def send_ldc_request(self, transaction_id: str | None = None,
                                on_entity=None, timeout: float = 5.0) -> TransactionContext:
        """Simulates the LDC issuing the initial request to the UCS responsible for the root entity."""
        tx_id = transaction_id or str(uuid.uuid4())
        expected_ids = set(self.graph.entities.keys())
        self.aggregator.start_transaction(tx_id, self.response_url, expected_entity_ids=expected_ids)
        if on_entity is not None:
            self.aggregator.register_incremental_callback(tx_id, on_entity)

        root_url = self.registry[self.graph.root_entity_id]
        headers = {TXN_HEADER: tx_id, RESPONSE_URL_HEADER: self.response_url}
        resp = await self.client.get(f"{root_url}/uder/{self.graph.root_entity_id}", headers=headers)
        resp.raise_for_status()
        root_entity = UDEREntity.from_dict(resp.json())
        await self.aggregator.receive_entity(tx_id, root_entity, self.response_url)

        await self.tasks.drain(timeout=timeout)
        return self.aggregator.get(tx_id)

    async def aclose(self) -> None:
        await self.client.aclose()


async def run_transaction(graph: UDERGraph, fault_config: dict[str, UCSNodeConfig] | None = None,
                           timeout: float = 5.0, transaction_id: str | None = None,
                           on_entity=None) -> tuple[TransactionContext, TaskRegistry, LDCAggregator]:
    network = SimulatedNetwork(graph, fault_config)
    ctx = await network.send_ldc_request(transaction_id=transaction_id, on_entity=on_entity, timeout=timeout)
    await network.aclose()
    return ctx, network.tasks, network.aggregator
