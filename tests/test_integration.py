from pathlib import Path

from uder_experiment.experiment.analyze import load_experiments, table_2_transformation_quality, write_all_tables
from uder_experiment.experiment.figures import generate_all_figures
from uder_experiment.experiment.runner import ScenarioFiles, run_single_experiment
from uder_experiment.experiment.storage import JSONLWriter, read_jsonl
from conftest import make_scenario, render_all


async def test_full_pipeline_request_to_persisted_result(tmp_path):
    scenario = make_scenario("complex", index=42)
    rendered = render_all(scenario)
    sf = ScenarioFiles(
        scenario_id=scenario.scenario_id, complexity=scenario.complexity, ground_truth=rendered["ground_truth"],
        files={"ubl": rendered["ubl"], "cii": rendered["cii"], "source-c": rendered["source_c"]},
    )

    exp_writer = JSONLWriter(tmp_path / "experiments.jsonl")
    field_writer = JSONLWriter(tmp_path / "field_results.jsonl")
    try:
        record = await run_single_experiment(
            sf, "ubl", "aggregated", error_rate=0.1, ai_model="mock-v1", prompt_version="v1",
            temperature=0.0, writer=exp_writer, field_writer=field_writer,
        )
    finally:
        exp_writer.close()
        field_writer.close()

    # request -> propagation -> aggregation
    assert record.source_entity_count > 0
    assert record.received_entity_count == record.source_entity_count
    # AI transformation + schema validation
    assert record.schema_valid
    # metric evaluation
    assert 0.0 <= record.semantic_preservation <= 1.0
    assert 0.0 <= record.brier_score <= 1.0
    # result persistence
    persisted = read_jsonl(tmp_path / "experiments.jsonl")
    assert len(persisted) == 1
    assert persisted[0]["experiment_id"] == record.experiment_id
    field_rows = read_jsonl(tmp_path / "field_results.jsonl")
    assert all(r["experiment_id"] == record.experiment_id for r in field_rows)
    assert len(field_rows) > 0


async def test_analyze_and_figures_run_end_to_end_on_persisted_results(tmp_path):
    scenario = make_scenario("simple", index=43)
    rendered = render_all(scenario)
    sf = ScenarioFiles(scenario.scenario_id, scenario.complexity, rendered["ground_truth"],
                        {"ubl": rendered["ubl"], "cii": rendered["cii"], "source-c": rendered["source_c"]})

    results_dir = tmp_path / "results"
    exp_writer = JSONLWriter(results_dir / "experiments.jsonl")
    field_writer = JSONLWriter(results_dir / "field_results.jsonl")
    for source in ("ubl", "cii", "source-c"):
        for mode in ("deterministic", "aggregated"):
            await run_single_experiment(sf, source, mode, error_rate=0.1, ai_model="mock-v1",
                                         prompt_version="v1", temperature=0.0, writer=exp_writer, field_writer=field_writer)
    exp_writer.close()
    field_writer.close()

    df = load_experiments(results_dir)
    assert len(df) == 6
    quality = table_2_transformation_quality(df)
    assert not quality.empty

    testdata_dir = tmp_path / "testdata"
    (testdata_dir / scenario.scenario_id).mkdir(parents=True)
    import json
    (testdata_dir / "index.json").write_text(json.dumps(
        [{"scenario_id": scenario.scenario_id, "complexity": scenario.complexity, "seed": 7, "line_count": 1}]
    ))

    tables_dir = tmp_path / "tables"
    tables = write_all_tables(results_dir, testdata_dir, tables_dir)
    assert (tables_dir / "table2_transformation_quality.csv").exists()
    assert len(tables) == 5

    figures_dir = tmp_path / "figures"
    names = generate_all_figures(results_dir, figures_dir)
    assert len(names) == 10
    for name in names:
        assert (figures_dir / f"{name}.png").exists()
