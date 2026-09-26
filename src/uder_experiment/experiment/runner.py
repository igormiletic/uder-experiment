"""Experiment runner: drives simulator + aggregator + transformer + metrics, persists results."""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

from uder_experiment.experiment.matrix import build_matrix
from uder_experiment.experiment.merge import merge_partial_canonicals
from uder_experiment.experiment.storage import ExperimentRecord, FieldResultRecord, JSONLWriter
from uder_experiment.metrics.calibration import brier_score, expected_calibration_error
from uder_experiment.metrics.consistency import check_invoice_consistency
from uder_experiment.metrics.preservation import evaluate_preservation
from uder_experiment.network.simulator import run_transaction
from uder_experiment.schema.json_schema import canonical_invoice_json_schema
from uder_experiment.transform.context import ModelConfig, TransformationContext
from uder_experiment.transform.deterministic import DeterministicTransformer
from uder_experiment.transform.mock_ai import MockAITransformer
from uder_experiment.uder.from_cii import parse_cii_to_uder
from uder_experiment.uder.from_source_c import parse_source_c_to_uder
from uder_experiment.uder.from_ubl import parse_ubl_to_uder

SOURCE_FILES = {"ubl": "ubl.xml", "cii": "cii.xml", "source-c": "source-c.json"}
_TARGET_SCHEMA = canonical_invoice_json_schema()


def _parse_source(source: str, text: str):
    if source == "ubl":
        return parse_ubl_to_uder(text)
    if source == "cii":
        return parse_cii_to_uder(text)
    if source == "source-c":
        return parse_source_c_to_uder(json.loads(text))
    raise ValueError(f"unknown source standard {source!r}")


@dataclass
class ScenarioFiles:
    scenario_id: str
    complexity: str
    ground_truth: dict
    files: dict[str, str]  # source -> raw text


def load_scenarios(testdata_dir: str | Path) -> list[ScenarioFiles]:
    root = Path(testdata_dir)
    index = json.loads((root / "index.json").read_text())
    scenarios = []
    for row in index:
        sdir = root / row["scenario_id"]
        gt = json.loads((sdir / "ground-truth.json").read_text())
        files = {src: (sdir / fname).read_text() for src, fname in SOURCE_FILES.items()}
        scenarios.append(ScenarioFiles(row["scenario_id"], row["complexity"], gt, files))
    return scenarios


def _build_transformer(mode: str, error_rate: float, ai_model: str | None, *,
                        use_real_ai: bool = False, prompt_version: str = "v1",
                        temperature: float = 0.0):
    if mode == "deterministic":
        return DeterministicTransformer()
    if use_real_ai:
        from uder_experiment.transform.real_ai import RealAITransformer, is_available
        if not is_available():
            raise RuntimeError(
                "use_real_ai=True but RealAITransformer.is_available() is False -- "
                "set AI_API_KEY (and optionally AI_API_BASE_URL / AI_MODEL) and ensure "
                "the `openai` package is installed."
            )
        # Only pass an explicit model name through when the caller set one that isn't
        # the mock-transformer default label -- otherwise let RealAITransformer resolve
        # its own default (AI_MODEL env var, then "gpt-4o-mini").
        real_model = ai_model if ai_model and ai_model != "mock-deterministic-v1" else None
        return RealAITransformer(model=real_model, temperature=temperature, prompt_version=prompt_version)
    return MockAITransformer(error_rate=error_rate)


async def _execute_transform(transformer, mode: str, entities_ordered: list, model_cfg: ModelConfig):
    """Executes the transform call(s) appropriate to `mode` and returns a single TransformResult-like object."""
    from uder_experiment.transform.base import TransformResult

    if mode == "isolated":
        partials = []
        for e in entities_ordered:
            # Each per-entity call is intentionally partial (system prompt: populate only this
            # entity's fields, leave the rest null) -- only the merged result below is "final".
            ctx = TransformationContext(mode="isolated", model=model_cfg, target_schema=_TARGET_SCHEMA,
                                         is_final=False)
            partials.append(await transformer.transform([e], _TARGET_SCHEMA, ctx))
        merged_data = merge_partial_canonicals([p.transformed_data for p in partials])
        field_conf: dict[str, float] = {}
        for p in partials:
            field_conf.update(p.field_confidences)
        confidences = [p.confidence for p in partials if p.transformed_data]
        result = TransformResult(
            transformed_data=merged_data,
            confidence=sum(confidences) / len(confidences) if confidences else 0.0,
            field_confidences=field_conf,
            metadata={"mode": "isolated", "transformer": transformer.name, "partial_count": len(partials)},
            latency_ms=sum(p.latency_ms for p in partials),
        )
        result.validate()
        return result

    if mode == "incremental":
        history: list[dict] = []
        result = None
        last_index = len(entities_ordered) - 1
        for i, e in enumerate(entities_ordered):
            # Only the call over the last entity produces the result that's actually scored --
            # earlier calls are expected to be incomplete until all entities have streamed in.
            ctx = TransformationContext(mode="incremental", model=model_cfg, target_schema=_TARGET_SCHEMA,
                                         history=history, is_final=(i == last_index))
            result = await transformer.transform([e], _TARGET_SCHEMA, ctx)
            history = history + [{"entities": [e.to_dict()]}]
        return result

    ctx = TransformationContext(mode=mode, model=model_cfg, target_schema=_TARGET_SCHEMA)
    return await transformer.transform(entities_ordered, _TARGET_SCHEMA, ctx)


async def run_single_experiment(scenario: ScenarioFiles, source: str, mode: str, *, error_rate: float,
                                 ai_model: str, prompt_version: str, temperature: float,
                                 writer: JSONLWriter, field_writer: JSONLWriter,
                                 use_real_ai: bool = False) -> ExperimentRecord:
    logger.info("experiment start: scenario=%s source=%s mode=%s", scenario.scenario_id, source, mode)
    graph = _parse_source(source, scenario.files[source])
    ctx, tasks, aggregator = await run_transaction(graph)

    entities_ordered = sorted(ctx.received_entities.values(),
                               key=lambda e: ctx.provenance[e.entity_id][0].received_at)

    transformer = _build_transformer(mode, error_rate, ai_model, use_real_ai=use_real_ai,
                                      prompt_version=prompt_version, temperature=temperature)
    resolved_model = getattr(transformer, "model", ai_model)
    model_cfg = ModelConfig(provider="deterministic" if mode == "deterministic"
                             else ("real" if use_real_ai else "mock"),
                             model="deterministic-rule-mapper" if mode == "deterministic" else resolved_model,
                             temperature=temperature, prompt_version=prompt_version)

    t0 = time.perf_counter()
    result = await _execute_transform(transformer, mode, entities_ordered, model_cfg)
    transform_wall_ms = (time.perf_counter() - t0) * 1000

    source_props = [e.properties for e in ctx.received_entities.values()]
    pr = evaluate_preservation(scenario.ground_truth, result.transformed_data, source_props)
    consistency = check_invoice_consistency(result.transformed_data)
    experiment_id = f"{scenario.scenario_id}-{source}-{mode}-{uuid.uuid4().hex[:8]}"

    confidences, correctness = [], []
    for fe in pr.field_evaluations:
        if not fe.present_in_expected:
            continue
        conf = result.field_confidences.get(fe.path, result.confidence)
        confidences.append(conf)
        correctness.append(1 if fe.correct else 0)
        field_writer.write(FieldResultRecord(
            experiment_id=experiment_id, path=fe.path, weight=fe.weight, required=fe.required,
            expected_value=repr(fe.expected_value), actual_value=repr(fe.actual_value),
            correct=fe.correct, field_confidence=conf,
        ))

    bs = brier_score(confidences, correctness)
    ece = expected_calibration_error(confidences, correctness, n_bins=10).ece
    latency_aggregation_ms = ((ctx.last_entity_at or ctx.created_at) - ctx.created_at) * 1000

    record = ExperimentRecord(
        experiment_id=experiment_id, timestamp=datetime.now(timezone.utc).isoformat(),
        source_standard=source, invoice_scenario_id=scenario.scenario_id, complexity_level=scenario.complexity,
        transaction_id=ctx.transaction_id, transformation_mode=mode,
        ai_model=model_cfg.model, prompt_version=prompt_version, temperature=temperature,
        source_entity_count=len(graph.all()), received_entity_count=len(ctx.received_entities),
        duplicate_count=ctx.duplicate_count,
        missing_entity_count=len(graph.all()) - len(ctx.received_entities),
        semantic_preservation=pr.preservation, information_loss=pr.information_loss,
        semantic_precision=pr.precision, semantic_f1=pr.f1, value_accuracy=pr.value_accuracy,
        global_confidence=result.confidence, brier_score=bs, calibration_error=ece,
        schema_valid=result.schema_valid, consistency_score=consistency.score,
        latency_total_ms=latency_aggregation_ms + transform_wall_ms,
        latency_aggregation_ms=latency_aggregation_ms, latency_ai_ms=result.latency_ms,
        accepted=bool(result.transformed_data) and result.schema_valid,
        error=result.metadata.get("error"),
    )
    writer.write(record)
    logger.info(
        "experiment done: scenario=%s source=%s mode=%s accepted=%s preservation=%.2f error=%s",
        scenario.scenario_id, source, mode, record.accepted, record.semantic_preservation, record.error,
    )
    return record


def _failed_experiment_record(scenario: ScenarioFiles, source: str, mode: str, ai_model: str,
                               prompt_version: str, temperature: float, exc: Exception) -> ExperimentRecord:
    """Placeholder record for an experiment that raised instead of returning a result.

    Keeps the run's row count/order legible in the output files instead of silently
    dropping the (scenario, source, mode) combination when we skip past it.
    """
    return ExperimentRecord(
        experiment_id=f"{scenario.scenario_id}-{source}-{mode}-{uuid.uuid4().hex[:8]}",
        timestamp=datetime.now(timezone.utc).isoformat(),
        source_standard=source, invoice_scenario_id=scenario.scenario_id, complexity_level=scenario.complexity,
        transaction_id="", transformation_mode=mode, ai_model=ai_model, prompt_version=prompt_version,
        temperature=temperature, source_entity_count=0, received_entity_count=0, duplicate_count=0,
        missing_entity_count=0, semantic_preservation=0.0, information_loss=1.0, semantic_precision=0.0,
        semantic_f1=0.0, value_accuracy=0.0, global_confidence=0.0, brier_score=0.0, calibration_error=0.0,
        schema_valid=False, consistency_score=0.0, latency_total_ms=0.0, latency_aggregation_ms=0.0,
        latency_ai_ms=0.0, accepted=False, error=f"{type(exc).__name__}: {exc}",
    )


async def run_full_matrix(testdata_dir: str | Path, output_dir: str | Path, *,
                           sources: list[str] | None = None, complexities: list[str] | None = None,
                           modes: list[str] | None = None, error_rate: float = 0.15,
                           ai_model: str = "mock-deterministic-v1", prompt_version: str = "v1",
                           temperature: float = 0.0, use_real_ai: bool = False) -> list[ExperimentRecord]:
    scenarios = load_scenarios(testdata_dir)
    matrix = build_matrix(sources, complexities, modes)
    allowed = {(c.source_standard, c.mode) for c in matrix}
    complexity_filter = {c.complexity for c in matrix}

    out = Path(output_dir)
    writer = JSONLWriter(out / "experiments.jsonl")
    field_writer = JSONLWriter(out / "field_results.jsonl")

    records = []
    try:
        for scenario in scenarios:
            if scenario.complexity not in complexity_filter:
                continue
            for source, mode in sorted(allowed):
                try:
                    record = await run_single_experiment(
                        scenario, source, mode, error_rate=error_rate, ai_model=ai_model,
                        prompt_version=prompt_version, temperature=temperature,
                        writer=writer, field_writer=field_writer, use_real_ai=use_real_ai,
                    )
                except Exception as exc:  # noqa: BLE001 -- one bad combination must not abort the matrix
                    logger.error(
                        "experiment raised, skipping and continuing with next: scenario=%s source=%s "
                        "mode=%s error=%s: %s",
                        scenario.scenario_id, source, mode, type(exc).__name__, exc, exc_info=True,
                    )
                    record = _failed_experiment_record(scenario, source, mode, ai_model, prompt_version,
                                                        temperature, exc)
                    writer.write(record)
                records.append(record)
    finally:
        writer.close()
        field_writer.close()
    return records
