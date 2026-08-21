import copy

import pytest

from uder_experiment.metrics.preservation import evaluate_preservation
from uder_experiment.network.simulator import run_transaction
from uder_experiment.network.ucs_node import UCSNodeConfig
from uder_experiment.schema.json_schema import validate_canonical_invoice
from uder_experiment.transform.context import TransformationContext
from uder_experiment.transform.deterministic import DeterministicTransformer
from uder_experiment.transform.mock_ai import MockAITransformer
from uder_experiment.uder.from_ubl import parse_ubl_to_uder
from conftest import make_scenario, render_all


async def _transform_scenario(complexity, index=1, fault_config=None):
    scenario = make_scenario(complexity, index=index)
    rendered = render_all(scenario)
    graph = parse_ubl_to_uder(rendered["ubl"])
    ctx, tasks, agg = await run_transaction(graph, fault_config=fault_config)
    entities = list(ctx.received_entities.values())
    tf = DeterministicTransformer()
    result = await tf.transform(entities, {}, TransformationContext(mode="deterministic"))
    return scenario, rendered, ctx, result


@pytest.mark.parametrize("complexity", ["simple", "medium", "complex"])
async def test_invoice_transforms_correctly_at_each_complexity(complexity):
    scenario, rendered, ctx, result = await _transform_scenario(complexity, index=4)
    assert result.schema_valid, result.validation_errors
    pr = evaluate_preservation(rendered["ground_truth"], result.transformed_data)
    assert pr.preservation > 0.9
    assert pr.precision > 0.9


async def test_missing_optional_fields_do_not_cause_false_errors():
    # simple-complexity scenarios never populate PO/contract references or line allowances
    scenario, rendered, ctx, result = await _transform_scenario("simple", index=2)
    assert result.transformed_data["invoice"]["commercialContext"]["purchaseOrderReference"] is None
    pr = evaluate_preservation(rendered["ground_truth"], result.transformed_data)
    # optional, absent-on-both-sides fields must not be counted as failures
    assert pr.preservation == 1.0
    assert pr.precision == 1.0


async def test_missing_required_field_reduces_preservation():
    scenario, rendered, ctx, result = await _transform_scenario(
        "medium", index=6, fault_config={"ucs-2": UCSNodeConfig(node_id="ucs-2", base_url="", fail=True)},
    )
    pr = evaluate_preservation(rendered["ground_truth"], result.transformed_data)
    assert pr.preservation < 1.0
    supplier_eval = next(e for e in pr.field_evaluations if e.path == "parties.supplier.name")
    assert not supplier_eval.correct


async def test_incorrect_monetary_values_are_detected():
    scenario, rendered, ctx, result = await _transform_scenario("medium", index=7)
    corrupted = copy.deepcopy(result.transformed_data)
    corrupted["invoice"]["financialSummary"]["netAmount"] += 999.0
    pr = evaluate_preservation(rendered["ground_truth"], corrupted)
    net_eval = next(e for e in pr.field_evaluations if e.path == "financialSummary.netAmount")
    assert not net_eval.correct
    assert pr.preservation < 1.0


async def test_hallucinated_output_reduces_precision():
    scenario, rendered, ctx, result = await _transform_scenario("simple", index=8)
    hallucinated = copy.deepcopy(result.transformed_data)
    hallucinated["invoice"]["commercialContext"]["contractReference"] = "TOTALLY-MADE-UP-REF-999"
    source_props = [e.properties for e in ctx.received_entities.values()]
    pr_clean = evaluate_preservation(rendered["ground_truth"], result.transformed_data, source_props)
    pr_hallucinated = evaluate_preservation(rendered["ground_truth"], hallucinated, source_props)
    assert pr_hallucinated.precision < pr_clean.precision


def test_invalid_target_output_is_rejected_by_schema_validation():
    ok, errors = validate_canonical_invoice({"invoice": {"identity": {"number": "X"}}})  # missing required fields
    assert not ok
    assert errors


async def test_mock_transformer_error_rate_degrades_preservation_monotonically():
    scenario = make_scenario("complex", index=10)
    rendered = render_all(scenario)
    graph = parse_ubl_to_uder(rendered["ubl"])
    ctx, tasks, agg = await run_transaction(graph)
    entities = list(ctx.received_entities.values())

    scores = []
    for rate in (0.0, 0.5):
        tf = MockAITransformer(error_rate=rate)
        result = await tf.transform(entities, {}, TransformationContext(mode="aggregated"))
        pr = evaluate_preservation(rendered["ground_truth"], result.transformed_data)
        scores.append(pr.preservation)
    assert scores[0] >= scores[1]
