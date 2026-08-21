"""Confidence calibration metrics (spec Section 15): Brier score, ECE, correlation, selective prediction."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats


def brier_score(confidences: list[float], correctness: list[int]) -> float:
    """Lower is better; 0.0 for a perfectly confident-and-correct (or confident-and-wrong-never) predictor."""
    if not confidences:
        return 0.0
    c = np.asarray(confidences, dtype=float)
    y = np.asarray(correctness, dtype=float)
    return float(np.mean((c - y) ** 2))


@dataclass
class ECEBin:
    lower: float
    upper: float
    count: int
    avg_confidence: float
    accuracy: float


@dataclass
class ECEResult:
    ece: float
    bins: list[ECEBin]


def expected_calibration_error(confidences: list[float], correctness: list[int], n_bins: int = 10) -> ECEResult:
    if not confidences:
        return ECEResult(ece=0.0, bins=[])
    c = np.asarray(confidences, dtype=float)
    y = np.asarray(correctness, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    n = len(c)
    ece = 0.0
    bins: list[ECEBin] = []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (c >= lo) & (c <= hi) if i == n_bins - 1 else (c >= lo) & (c < hi)
        count = int(mask.sum())
        if count == 0:
            bins.append(ECEBin(lo, hi, 0, 0.0, 0.0))
            continue
        avg_conf = float(c[mask].mean())
        acc = float(y[mask].mean())
        ece += (count / n) * abs(acc - avg_conf)
        bins.append(ECEBin(lo, hi, count, avg_conf, acc))
    return ECEResult(ece=float(ece), bins=bins)


@dataclass
class CorrelationResult:
    pearson: float | None
    pearson_p: float | None
    spearman: float | None
    spearman_p: float | None


def confidence_correctness_correlation(confidences: list[float], correctness: list[int]) -> CorrelationResult:
    if len(confidences) < 3 or len(set(correctness)) < 2 or len(set(confidences)) < 2:
        return CorrelationResult(None, None, None, None)
    pear = stats.pearsonr(confidences, correctness)
    spear = stats.spearmanr(confidences, correctness)
    return CorrelationResult(
        pearson=float(pear.statistic), pearson_p=float(pear.pvalue),
        spearman=float(spear.statistic), spearman_p=float(spear.pvalue),
    )


@dataclass
class SelectivePredictionPoint:
    threshold: float
    coverage: float
    accuracy: float
    mean_preservation: float | None
    information_loss: float | None


def selective_prediction_curve(
    confidences: list[float],
    correctness: list[int],
    preservation_scores: list[float] | None = None,
    thresholds: list[float] | None = None,
) -> list[SelectivePredictionPoint]:
    thresholds = thresholds or [0.50, 0.60, 0.70, 0.80, 0.90, 0.95]
    c = np.asarray(confidences, dtype=float)
    y = np.asarray(correctness, dtype=float)
    p = np.asarray(preservation_scores, dtype=float) if preservation_scores else None
    n = len(c)
    points = []
    for gamma in thresholds:
        mask = c >= gamma
        count = int(mask.sum())
        coverage = count / n if n else 0.0
        accuracy = float(y[mask].mean()) if count else 0.0
        mean_pres = float(p[mask].mean()) if (p is not None and count) else None
        loss = (1.0 - mean_pres) if mean_pres is not None else None
        points.append(SelectivePredictionPoint(gamma, coverage, accuracy, mean_pres, loss))
    return points
