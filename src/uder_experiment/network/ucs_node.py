"""A simulated UCS (UDER Control System) instance.

Implements the request-request propagation model (spec Section 1 / 9):
1. Receives an HTTP request (GET /uder/{entity_id}).
2. Returns the requested entity immediately in the normal HTTP response.
3. Identifies linked entities and propagates new, decoupled (fire-and-forget)
   HTTP requests to the UCS instances responsible for them, carrying
   X-Transaction-ID and X-LDC-Response-URL.
4. If the incoming request was itself a propagated one (X-Forwarded-Request:
   true), delivers this node's entity directly to X-LDC-Response-URL once
   resolved -- independently of the immediate HTTP response to its caller.

Propagation uses asyncio.create_task (not Starlette BackgroundTasks) so the
response to the caller returns before the fan-out completes, making
out-of-order / delayed / partial delivery genuinely observable rather than
serialized behind a single await chain.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from uder_experiment.uder.entities import UDEREntity

logger = logging.getLogger(__name__)

TXN_HEADER = "X-Transaction-ID"
RESPONSE_URL_HEADER = "X-LDC-Response-URL"
FORWARDED_HEADER = "X-Forwarded-Request"


@dataclass
class UCSNodeConfig:
    node_id: str
    base_url: str
    entities: dict[str, UDEREntity] = field(default_factory=dict)
    delay_seconds: float = 0.0
    fail: bool = False
    missing_entity_ids: frozenset[str] = frozenset()
    duplicate_entity_ids: frozenset[str] = frozenset()


@dataclass
class TaskRegistry:
    """Shared, network-wide bookkeeping of in-flight fire-and-forget propagation tasks."""
    tasks: list[asyncio.Task] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)

    def spawn(self, coro) -> asyncio.Task:
        task = asyncio.ensure_future(coro)
        self.tasks.append(task)
        return task

    def log(self, **event) -> None:
        self.events.append(event)

    async def drain(self, timeout: float | None = None) -> None:
        """Await all currently-known tasks, including ones they transitively spawn."""
        loop = asyncio.get_event_loop()
        deadline = (loop.time() + timeout) if timeout is not None else None
        seen: set[int] = set()
        while True:
            pending = [t for t in self.tasks if id(t) not in seen]
            if not pending:
                return
            for t in pending:
                seen.add(id(t))
            remaining = None if deadline is None else max(0.0, deadline - loop.time())
            try:
                await asyncio.wait(pending, timeout=remaining, return_when=asyncio.ALL_COMPLETED)
            except Exception:
                pass
            if deadline is not None and loop.time() >= deadline:
                return


def build_ucs_app(config: UCSNodeConfig, registry: dict[str, str], tasks: TaskRegistry) -> FastAPI:
    app = FastAPI(title=f"UCS[{config.node_id}]")
    app.state.config = config
    app.state.registry = registry  # entity_id -> owning node base_url
    app.state.tasks = tasks
    app.state.http_client = None  # injected by simulator once all apps exist

    @app.get("/uder/{entity_id}")
    async def get_entity(entity_id: str, request: Request):
        cfg: UCSNodeConfig = app.state.config
        tx_id = request.headers.get(TXN_HEADER) or str(uuid.uuid4())
        response_url = request.headers.get(RESPONSE_URL_HEADER)
        is_forwarded = (request.headers.get(FORWARDED_HEADER) or "").lower() == "true"

        tasks.log(event="request_received", node=cfg.node_id, entity_id=entity_id,
                   transaction_id=tx_id, forwarded=is_forwarded)

        if cfg.fail:
            tasks.log(event="node_failed", node=cfg.node_id, entity_id=entity_id, transaction_id=tx_id)
            raise HTTPException(status_code=503, detail=f"UCS node {cfg.node_id} unavailable")

        if cfg.delay_seconds:
            await asyncio.sleep(cfg.delay_seconds)

        if entity_id in cfg.missing_entity_ids or entity_id not in cfg.entities:
            tasks.log(event="entity_missing", node=cfg.node_id, entity_id=entity_id, transaction_id=tx_id)
            raise HTTPException(status_code=404, detail="entity not found")

        entity = cfg.entities[entity_id]

        # Fire-and-forget propagation to linked entities (does not block this response).
        tasks.spawn(_propagate_links(app, entity, tx_id, response_url))

        # If this request was itself propagated, deliver this entity to the LDC callback,
        # independently of (and possibly after) the response below.
        if is_forwarded and response_url:
            copies = 2 if entity_id in cfg.duplicate_entity_ids else 1
            for _ in range(copies):
                tasks.spawn(_deliver_to_ldc(app, entity, tx_id, response_url))

        tasks.log(event="response_sent", node=cfg.node_id, entity_id=entity_id, transaction_id=tx_id)
        return JSONResponse(content=entity.to_dict(), headers={TXN_HEADER: tx_id})

    return app


async def _propagate_links(app: FastAPI, entity: UDEREntity, tx_id: str, response_url: str | None) -> None:
    """Propagates one request per link *concurrently* (spec Section 9: parallel propagation),
    not sequentially -- a linked entity behind a slow/failed UCS must not delay or block
    delivery of sibling entities from other UCS instances."""
    registry: dict[str, str] = app.state.registry
    tasks: TaskRegistry = app.state.tasks
    client: httpx.AsyncClient = app.state.http_client
    for link in entity.links:
        target_base = registry.get(link.target_entity_id)
        if target_base is None or client is None:
            continue
        tasks.spawn(_propagate_one(client, tasks, target_base, link.target_entity_id, tx_id, response_url))


async def _propagate_one(client: httpx.AsyncClient, tasks: "TaskRegistry", target_base: str,
                          target_entity_id: str, tx_id: str, response_url: str | None) -> None:
    headers = {TXN_HEADER: tx_id, FORWARDED_HEADER: "true"}
    if response_url:
        headers[RESPONSE_URL_HEADER] = response_url
    try:
        resp = await client.get(f"{target_base}/uder/{target_entity_id}", headers=headers)
        resp.raise_for_status()
    except Exception as exc:  # a failed/unreachable downstream UCS must not break the rest of the graph
        tasks.log(event="propagation_failed", target_entity_id=target_entity_id,
                  transaction_id=tx_id, error=str(exc))


async def _deliver_to_ldc(app: FastAPI, entity: UDEREntity, tx_id: str, response_url: str) -> None:
    tasks: TaskRegistry = app.state.tasks
    client: httpx.AsyncClient = app.state.http_client
    if client is None:
        return
    try:
        resp = await client.post(response_url, json=entity.to_dict(), headers={TXN_HEADER: tx_id})
        resp.raise_for_status()
        tasks.log(event="delivered_to_ldc", entity_id=entity.entity_id, transaction_id=tx_id)
    except Exception as exc:
        tasks.log(event="delivery_failed", entity_id=entity.entity_id, transaction_id=tx_id, error=str(exc))
