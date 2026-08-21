"""Experiment matrix definition (spec Section 17): source x complexity x transformation mode.

Four baselines:
  deterministic -- Baseline 1, rule-based structural mapping, no AI
  isolated      -- Baseline 2, AI transformation of each UDER entity independently
  aggregated    -- Baseline 3, AI transformation after complete transaction aggregation
  incremental   -- Baseline 4, AI transformation refined as each new entity arrives
"""
from __future__ import annotations

from dataclasses import dataclass

SOURCES = ["ubl", "cii", "source-c"]
COMPLEXITIES = ["simple", "medium", "complex"]
MODES = ["deterministic", "isolated", "aggregated", "incremental"]


@dataclass(frozen=True)
class MatrixCell:
    source_standard: str
    complexity: str
    mode: str


def build_matrix(sources: list[str] | None = None, complexities: list[str] | None = None,
                  modes: list[str] | None = None) -> list[MatrixCell]:
    sources = sources or SOURCES
    complexities = complexities or COMPLEXITIES
    modes = modes or MODES
    return [MatrixCell(s, c, m) for s in sources for c in complexities for m in modes]
