"""Deterministic, seeded stand-in for an AI transformer (spec Section 11 Mode B).

Used for isolated / aggregated / incremental experiment modes (Baselines 2-4)
without requiring external AI calls. Starts from the same rule-based mapping
DeterministicTransformer produces (so behavior with error_rate=0 is a correct
transformation), then injects configurable, seeded imperfections:
  - numeric drift/omission on amounts, quantities, rates
  - string corruption on names/categories
  - hallucinated (fabricated, unsupported-by-source) optional references

field/global confidence is simulated (overconfident-with-noise, like real LLM
self-assessment tends to be) rather than a perfect correctness oracle, so
calibration metrics computed against it are non-trivial.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import random
import time

from uder_experiment.transform.base import Transformer, TransformResult
from uder_experiment.transform.context import TransformationContext
from uder_experiment.transform.deterministic import DeterministicTransformer
from uder_experiment.uder.entities import UDEREntity

_STRING_CORRUPTIONS = ["UNKNOWN", "N/A", "", "MISC"]


def _seed_for(context: TransformationContext, entities: list[UDEREntity], seed_offset: int) -> int:
    key = "|".join(sorted(e.entity_id for e in entities)) + f"|{context.mode}|{seed_offset}"
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)


def _walk_leaves(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_leaves(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_leaves(v, f"{path}[{i}]")
    else:
        yield path, obj


def _set_by_path(data: dict, path: str, value) -> None:
    parts = path.replace("]", "").replace("[", ".").split(".")
    node = data
    for p in parts[:-1]:
        node = node[int(p)] if p.isdigit() else node[p]
    last = parts[-1]
    if last.isdigit():
        node[int(last)] = value
    else:
        node[last] = value


class MockAITransformer(Transformer):
    name = "mock_ai"

    def __init__(self, error_rate: float = 0.0, seed_offset: int = 0, simulated_latency_ms: float = 0.0) -> None:
        self.error_rate = error_rate
        self.seed_offset = seed_offset
        self.simulated_latency_ms = simulated_latency_ms
        self._base = DeterministicTransformer()

    async def transform(self, uder_entities: list[UDEREntity], target_schema: dict,
                         context: TransformationContext) -> TransformResult:
        start = time.perf_counter()

        # Incremental mode: fold in previously-seen entities from context.history so the
        # "AI" refines a growing aggregate rather than starting from scratch each call.
        combined = list(uder_entities)
        if context.mode == "incremental" and context.history:
            seen = {e.entity_id for e in combined}
            for snap in context.history:
                for e in snap.get("entities", []):
                    if e.entity_id not in seen:
                        combined.append(e)
                        seen.add(e.entity_id)

        base = await self._base.transform(combined, target_schema, context)
        if self.simulated_latency_ms:
            await asyncio.sleep(self.simulated_latency_ms / 1000)

        if not base.transformed_data:
            base.metadata.update({"transformer": "mock_ai", "confidence_strategy": "simulated_self_assessment",
                                   "confidence_estimate": True, "mode": context.mode})
            base.latency_ms = (time.perf_counter() - start) * 1000
            return base

        rng = random.Random(_seed_for(context, combined, self.seed_offset))
        data = copy.deepcopy(base.transformed_data)
        field_conf: dict[str, float] = {}
        perturbed_paths: set[str] = set()

        for path, value in list(_walk_leaves(data)):
            if path in ("schemaVersion",) or path.startswith("invoice.identity.number"):
                field_conf[path] = round(min(1.0, max(0.5, rng.gauss(0.95, 0.05))), 3)
                continue
            perturb = rng.random() < self.error_rate
            if perturb:
                perturbed_paths.add(path)
                if isinstance(value, bool):
                    _set_by_path(data, path, not value)
                elif isinstance(value, (int, float)):
                    factor = rng.choice([rng.uniform(0.7, 0.95), rng.uniform(1.05, 1.3), 0.0])
                    _set_by_path(data, path, round(value * factor, 2) if value else round(rng.uniform(1, 50), 2))
                elif isinstance(value, str) and value:
                    _set_by_path(data, path, rng.choice(_STRING_CORRUPTIONS))
                elif value is None and rng.random() < 0.5:
                    # hallucinate a value where the source genuinely had none
                    _set_by_path(data, path, f"FAB-{rng.randint(1000, 9999)}")

            base_conf = rng.gauss(0.9, 0.08) if not perturb else rng.gauss(0.55, 0.2)
            field_conf[path] = round(min(0.99, max(0.05, base_conf)), 3)

        global_confidence = round(sum(field_conf.values()) / len(field_conf), 3) if field_conf else 0.0

        result = TransformResult(
            transformed_data=data, confidence=global_confidence, field_confidences=field_conf,
            provenance=base.provenance,
            metadata={
                "mode": context.mode, "transformer": "mock_ai", "error_rate": self.error_rate,
                "perturbed_field_count": len(perturbed_paths),
                "confidence_strategy": "simulated_self_assessment", "confidence_estimate": True,
                "model": context.model.model, "prompt_version": context.model.prompt_version,
                "temperature": context.model.temperature,
            },
            latency_ms=(time.perf_counter() - start) * 1000,
        )
        result.validate()
        return result
