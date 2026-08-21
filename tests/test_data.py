import json
import xml.etree.ElementTree as ET

from uder_experiment.schema.json_schema import validate_canonical_invoice
from uder_experiment.uder.from_cii import parse_cii_to_uder
from uder_experiment.uder.from_source_c import parse_source_c_to_uder
from uder_experiment.uder.from_ubl import parse_ubl_to_uder
from conftest import make_scenario, render_all


def test_ground_truth_is_valid_against_canonical_invoice_schema(dataset):
    for g in dataset:
        ok, errors = validate_canonical_invoice(g.ground_truth)
        assert ok, errors


def test_source_invoice_structures_are_well_formed(dataset):
    for g in dataset:
        ET.fromstring(g.ubl_xml)
        ET.fromstring(g.cii_xml)
        json.dumps(g.source_c_json)  # must be JSON-serializable


def test_equivalent_ubl_cii_source_c_represent_same_logical_invoice():
    for complexity in ("simple", "medium", "complex"):
        scenario = make_scenario(complexity, index=3)
        rendered = render_all(scenario)
        ubl = parse_ubl_to_uder(rendered["ubl"])
        cii = parse_cii_to_uder(rendered["cii"])
        source_c = parse_source_c_to_uder(json.loads(rendered["source_c"]) if isinstance(rendered["source_c"], str) else rendered["source_c"])

        for graph in (ubl, cii, source_c):
            invoice = graph.get(graph.root_entity_id)
            assert invoice.properties["number"] == scenario.number
            assert float(invoice.properties["payableAmount"]) == float(scenario.totals().payable_amount)
            supplier = graph.get(f"urn:party:{scenario.number}:supplier")
            assert supplier.properties["name"] == scenario.supplier.name


def test_uder_entities_preserve_links():
    scenario = make_scenario("complex", index=5)
    rendered = render_all(scenario)
    graph = parse_ubl_to_uder(rendered["ubl"])
    invoice = graph.get(graph.root_entity_id)
    predicates = {l.predicate for l in invoice.links}
    assert {"hasSupplier", "hasCustomer", "hasLine", "hasTaxSummary", "hasPayment"} <= predicates
    for link in invoice.links:
        assert graph.get(link.target_entity_id) is not None, f"dangling link to {link.target_entity_id}"
    for line_entity in [e for e in graph.all() if e.entity_type == "InvoiceLine"]:
        product_links = [l for l in line_entity.links if l.predicate == "hasProduct"]
        assert product_links
        assert graph.get(product_links[0].target_entity_id) is not None


def test_semantic_feature_extraction_paths_are_deterministic():
    from uder_experiment.metrics.features import extract_features

    scenario = make_scenario("medium", index=2)
    rendered = render_all(scenario)
    f1 = extract_features(rendered["ground_truth"])
    f2 = extract_features(rendered["ground_truth"])
    assert set(f1.keys()) == set(f2.keys())
    for path in f1:
        assert f1[path].value == f2[path].value
        assert f1[path].weight == f2[path].weight


def test_feature_extraction_is_order_independent_for_items():
    from uder_experiment.metrics.features import extract_features

    scenario = make_scenario("complex", index=9)
    rendered = render_all(scenario)
    gt = rendered["ground_truth"]
    reordered = dict(gt)
    reordered_invoice = dict(gt["invoice"])
    reordered_invoice["items"] = list(reversed(gt["invoice"]["items"]))
    reordered["invoice"] = reordered_invoice

    f_original = extract_features(gt)
    f_reordered = extract_features(reordered)
    assert set(f_original.keys()) == set(f_reordered.keys())
