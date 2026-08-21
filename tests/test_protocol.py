import pytest

from uder_experiment.network.simulator import SimulatedNetwork, run_transaction
from uder_experiment.network.ucs_node import UCSNodeConfig
from uder_experiment.uder.from_ubl import parse_ubl_to_uder
from conftest import make_scenario, render_all


@pytest.fixture
def graph():
    scenario = make_scenario("medium", index=1)
    rendered = render_all(scenario)
    return parse_ubl_to_uder(rendered["ubl"])


async def test_initial_response_returns_requested_entity(graph):
    ctx, tasks, agg = await run_transaction(graph)
    root = ctx.received_entities[graph.root_entity_id]
    assert root.entity_type == "Invoice"


async def test_transaction_id_is_preserved_across_propagation(graph):
    ctx, tasks, agg = await run_transaction(graph)
    tx_ids = {ev["transaction_id"] for ev in tasks.events if "transaction_id" in ev}
    assert tx_ids == {ctx.transaction_id}


async def test_linked_entities_trigger_propagated_requests(graph):
    ctx, tasks, agg = await run_transaction(graph)
    forwarded = [ev for ev in tasks.events if ev["event"] == "request_received" and ev["forwarded"]]
    # every non-root entity should have been reached via a forwarded (propagated) request
    assert len(forwarded) == len(graph.all()) - 1


async def test_ldc_response_url_preserved_and_downstream_delivers_to_callback(graph):
    ctx, tasks, agg = await run_transaction(graph)
    delivered = [ev for ev in tasks.events if ev["event"] == "delivered_to_ldc"]
    # every non-root entity must be delivered to the LDC callback exactly once (no faults injected)
    assert len(delivered) == len(graph.all()) - 1
    assert ctx.completeness == 1.0


async def test_out_of_order_responses_are_correctly_aggregated(graph):
    # ucs-4 (lines/products) delayed relative to ucs-2/ucs-3/ucs-5 -> arrives later, still aggregates correctly
    ctx, tasks, agg = await run_transaction(graph, fault_config={
        "ucs-4": UCSNodeConfig(node_id="ucs-4", base_url="", delay_seconds=0.15),
    })
    assert ctx.completeness == 1.0
    line_events = [r for r in ctx.provenance if r.startswith("urn:line:")]
    other_events = [r for r in ctx.provenance if not r.startswith("urn:line:") and not r.startswith("urn:product:")
                     and not r.startswith("urn:invoice:")]
    earliest_line_delay = min(ctx.provenance[r][0].received_at for r in line_events) - ctx.created_at
    latest_other_delay = max(ctx.provenance[r][0].received_at for r in other_events) - ctx.created_at
    # generous margin around scheduling jitter: the delayed node's entities must still land
    # clearly after the non-delayed nodes', without asserting on tight absolute timings
    assert earliest_line_delay >= 0.1  # respected the configured 0.15s delay on ucs-4
    assert latest_other_delay < 0.1  # non-delayed nodes resolved well before the delayed one, in parallel


async def test_duplicate_entities_are_deduplicated(graph):
    dup_id = next(e.entity_id for e in graph.all() if e.entity_type == "Party")
    ctx, tasks, agg = await run_transaction(graph, fault_config={
        "ucs-2": UCSNodeConfig(node_id="ucs-2", base_url="", duplicate_entity_ids=frozenset([dup_id])),
        "ucs-3": UCSNodeConfig(node_id="ucs-3", base_url=""),
    })
    assert len(ctx.received_entities) == len(graph.all())  # deduped down to unique count
    assert ctx.duplicate_count >= 1
    assert ctx.duplicate_rate > 0


async def test_failed_ucs_does_not_destroy_already_collected_data(graph):
    ctx, tasks, agg = await run_transaction(graph, fault_config={
        "ucs-2": UCSNodeConfig(node_id="ucs-2", base_url="", fail=True),
    })
    assert 0 < ctx.completeness < 1.0
    # entities from healthy nodes are still present
    assert any(e.entity_type == "InvoiceLine" for e in ctx.received_entities.values())
    assert any(e.entity_type == "TaxSummary" for e in ctx.received_entities.values())
    # the failed node's entity is genuinely missing, not silently substituted
    assert not any(e.entity_id.endswith(":supplier") for e in ctx.received_entities.values())


async def test_timeout_produces_partial_transaction_state(graph):
    ctx, tasks, agg = await run_transaction(
        graph, fault_config={"ucs-4": UCSNodeConfig(node_id="ucs-4", base_url="", delay_seconds=2.0)},
        timeout=0.2,
    )
    assert ctx.completeness < 1.0
    assert ctx.received_entities  # root + fast branches still collected


async def test_missing_linked_entity(graph):
    missing_id = next(e.entity_id for e in graph.all() if e.entity_type == "PaymentInformation")
    ctx, tasks, agg = await run_transaction(graph, fault_config={
        "ucs-5": UCSNodeConfig(node_id="ucs-5", base_url="", missing_entity_ids=frozenset([missing_id])),
    })
    assert missing_id not in ctx.received_entities
    assert ctx.completeness < 1.0
