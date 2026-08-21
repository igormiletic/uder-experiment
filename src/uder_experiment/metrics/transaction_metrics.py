"""Transaction-level metrics (spec Section 16) and general latency/statistics helpers."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from uder_experiment.aggregation.transaction import TransactionContext
from uder_experiment.metrics.features import extract_features


def transformation_completeness(actual_canonical: dict, expected_canonical: dict) -> float:
    """Fraction of expected features that are *populated* (non-null) in the output,
    independent of whether the populated value is correct (that's `preservation`)."""
    expected = extract_features(expected_canonical)
    actual = extract_features(actual_canonical) if actual_canonical else {}
    if not expected:
        return 1.0
    populated = sum(1 for path, f in expected.items() if path in actual and actual[path].value not in (None, frozenset()))
    return populated / len(expected)


@dataclass
class TransactionMetrics:
    transaction_id: str
    completeness: float
    duplicate_rate: float
    transformation_completeness: float
    information_loss: float


def evaluate_transaction(ctx: TransactionContext, actual_canonical: dict, expected_canonical: dict,
                          preservation: float) -> TransactionMetrics:
    return TransactionMetrics(
        transaction_id=ctx.transaction_id,
        completeness=ctx.completeness,
        duplicate_rate=ctx.duplicate_rate,
        transformation_completeness=transformation_completeness(actual_canonical, expected_canonical),
        information_loss=1.0 - preservation,
    )


@dataclass
class Distribution:
    count: int
    mean: float
    median: float
    std: float
    minimum: float
    maximum: float
    p50: float
    p95: float
    p99: float
    ci95_low: float
    ci95_high: float


def describe(values: list[float]) -> Distribution:
    if not values:
        return Distribution(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    arr = np.asarray(values, dtype=float)
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
    se = std / np.sqrt(len(arr)) if len(arr) > 1 else 0.0
    return Distribution(
        count=len(arr), mean=mean, median=float(np.median(arr)), std=std,
        minimum=float(arr.min()), maximum=float(arr.max()),
        p50=float(np.percentile(arr, 50)), p95=float(np.percentile(arr, 95)), p99=float(np.percentile(arr, 99)),
        ci95_low=mean - 1.96 * se, ci95_high=mean + 1.96 * se,
    )
