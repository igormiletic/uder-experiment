"""TransformationContext: theta = <M, S_T, I, P, H> (spec Section 12)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

TransformMode = Literal["deterministic", "isolated", "aggregated", "incremental"]


@dataclass
class ModelConfig:
    """M: AI model configuration."""
    provider: str = "mock"
    model: str = "mock-deterministic-v1"
    temperature: float = 0.0
    prompt_version: str = "v1"
    max_retries: int = 2
    structured_output: bool = True


@dataclass
class TransformationContext:
    mode: TransformMode
    model: ModelConfig = field(default_factory=ModelConfig)
    target_schema: dict = field(default_factory=dict)  # S_T
    instructions: str = ""  # I
    provenance: dict = field(default_factory=dict)  # P: transaction/source provenance info
    history: list[dict] = field(default_factory=list)  # H: previously aggregated entity context (incremental refinement)
    # Whether this call's output is the one that will actually be scored/returned, as opposed to
    # an intermediate isolated/incremental per-entity call whose output is expected to be
    # partial (by design -- see SYSTEM_PROMPT) and gets merged/superseded rather than used as-is.
    is_final: bool = True
