"""LDC callback receiver: the X-LDC-Response-URL endpoint downstream UCS instances deliver to."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from uder_experiment.aggregation.ldc_aggregator import LDCAggregator
from uder_experiment.network.ucs_node import TXN_HEADER
from uder_experiment.uder.entities import UDEREntity


def build_ldc_callback_app(aggregator: LDCAggregator) -> FastAPI:
    app = FastAPI(title="LDC-callback")
    app.state.aggregator = aggregator

    @app.post("/callback")
    async def callback(request: Request):
        tx_id = request.headers.get(TXN_HEADER)
        body = await request.json()
        entity = UDEREntity.from_dict(body)
        await aggregator.receive_entity(tx_id, entity)
        return JSONResponse(content={"status": "received", "entityId": entity.entity_id})

    return app
