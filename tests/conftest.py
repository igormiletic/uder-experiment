import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from uder_experiment.scenario.generator import GeneratedScenario, generate_dataset  # noqa: E402
from uder_experiment.scenario.truth_model import generate_scenario  # noqa: E402
from uder_experiment.scenario.render_cii import render_cii  # noqa: E402
from uder_experiment.scenario.render_ground_truth import render_ground_truth  # noqa: E402
from uder_experiment.scenario.render_source_c import render_source_c  # noqa: E402
from uder_experiment.scenario.render_ubl import render_ubl  # noqa: E402


@pytest.fixture(scope="session")
def dataset() -> list[GeneratedScenario]:
    return generate_dataset(count=12, seed=7)


def make_scenario(complexity="medium", index=1, seed=7):
    return generate_scenario(index=index, seed=seed, complexity=complexity)


def render_all(scenario):
    gt = render_ground_truth(scenario).model_dump(by_alias=True)
    return {
        "ground_truth": gt,
        "ubl": render_ubl(scenario),
        "cii": render_cii(scenario),
        "source_c": json.dumps(render_source_c(scenario)),
    }
