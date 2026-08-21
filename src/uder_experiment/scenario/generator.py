"""Reproducible dataset generator: seed + scenario count + complexity distribution -> testdata/."""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from uder_experiment.scenario.render_cii import render_cii
from uder_experiment.scenario.render_ground_truth import render_ground_truth
from uder_experiment.scenario.render_source_c import render_source_c
from uder_experiment.scenario.render_ubl import render_ubl
from uder_experiment.scenario.truth_model import Complexity, InvoiceScenario, generate_scenario

DEFAULT_COMPLEXITY_DISTRIBUTION: dict[Complexity, float] = {
    "simple": 0.34,
    "medium": 0.36,
    "complex": 0.30,
}


@dataclass
class GeneratedScenario:
    scenario: InvoiceScenario
    ground_truth: dict
    ubl_xml: str
    cii_xml: str
    source_c_json: dict


def _complexity_sequence(count: int, seed: int, distribution: dict[Complexity, float]) -> list[Complexity]:
    counts: dict[Complexity, int] = {}
    remaining = count
    labels = list(distribution.keys())
    for label in labels[:-1]:
        n = round(count * distribution[label])
        counts[label] = n
        remaining -= n
    counts[labels[-1]] = remaining
    sequence: list[Complexity] = []
    for label, n in counts.items():
        sequence.extend([label] * n)
    random.Random(seed).shuffle(sequence)
    return sequence


def generate_dataset(
    count: int = 50,
    seed: int = 42,
    distribution: dict[Complexity, float] | None = None,
) -> list[GeneratedScenario]:
    distribution = distribution or DEFAULT_COMPLEXITY_DISTRIBUTION
    complexities = _complexity_sequence(count, seed, distribution)

    results: list[GeneratedScenario] = []
    for i, complexity in enumerate(complexities, start=1):
        scenario = generate_scenario(index=i, seed=seed, complexity=complexity)
        ground_truth = render_ground_truth(scenario).model_dump(by_alias=True)
        ubl_xml = render_ubl(scenario)
        cii_xml = render_cii(scenario)
        source_c_json = render_source_c(scenario)
        results.append(GeneratedScenario(scenario, ground_truth, ubl_xml, cii_xml, source_c_json))
    return results


def write_dataset(results: list[GeneratedScenario], output_dir: str | Path) -> None:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    index_rows = []
    for g in results:
        scenario_dir = root / g.scenario.scenario_id
        scenario_dir.mkdir(parents=True, exist_ok=True)
        (scenario_dir / "ground-truth.json").write_text(json.dumps(g.ground_truth, indent=2))
        (scenario_dir / "ubl.xml").write_text(g.ubl_xml)
        (scenario_dir / "cii.xml").write_text(g.cii_xml)
        (scenario_dir / "source-c.json").write_text(json.dumps(g.source_c_json, indent=2))
        index_rows.append({
            "scenario_id": g.scenario.scenario_id,
            "complexity": g.scenario.complexity,
            "seed": g.scenario.seed,
            "line_count": len(g.scenario.lines),
        })
    (root / "index.json").write_text(json.dumps(index_rows, indent=2))
