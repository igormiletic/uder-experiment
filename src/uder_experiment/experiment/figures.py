"""The 10 required figures (spec Section 22). Reads only from persisted results -- reproducible."""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from uder_experiment.experiment.storage import read_jsonl
from uder_experiment.metrics.calibration import expected_calibration_error, selective_prediction_curve


def _save(fig, out_dir: Path, name: str) -> None:
    fig.tight_layout()
    fig.savefig(out_dir / f"{name}.png", dpi=150)
    plt.close(fig)


def generate_all_figures(results_dir: str | Path, output_dir: str | Path) -> list[str]:
    df = pd.DataFrame(read_jsonl(Path(results_dir) / "experiments.jsonl"))
    field_df = pd.DataFrame(read_jsonl(Path(results_dir) / "field_results.jsonl"))
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    if df.empty:
        return []

    names = []

    # 1. Information loss distribution by source standard
    fig, ax = plt.subplots(figsize=(6, 4))
    for standard, sub in df.groupby("source_standard"):
        ax.hist(sub["information_loss"], bins=15, alpha=0.5, label=standard)
    ax.set_xlabel("Information loss"); ax.set_ylabel("Count"); ax.set_title("Information loss by source standard")
    ax.legend()
    _save(fig, out, "01_information_loss_by_standard"); names.append("01_information_loss_by_standard")

    # 2. Semantic preservation by transformation mode
    fig, ax = plt.subplots(figsize=(6, 4))
    order = ["deterministic", "isolated", "aggregated", "incremental"]
    data = [df[df.transformation_mode == m]["semantic_preservation"].dropna().values for m in order]
    ax.boxplot(data)
    ax.set_xticks(range(1, len(order) + 1))
    ax.set_xticklabels(order)
    ax.set_ylabel("Semantic preservation"); ax.set_title("Preservation by transformation mode")
    _save(fig, out, "02_preservation_by_mode"); names.append("02_preservation_by_mode")

    # 3. Precision vs preservation scatter
    fig, ax = plt.subplots(figsize=(5, 5))
    for mode, sub in df.groupby("transformation_mode"):
        ax.scatter(sub["semantic_preservation"], sub["semantic_precision"], s=12, alpha=0.6, label=mode)
    ax.set_xlabel("Preservation (recall)"); ax.set_ylabel("Precision"); ax.set_title("Precision vs. preservation")
    ax.legend(fontsize=8)
    _save(fig, out, "03_precision_vs_preservation"); names.append("03_precision_vs_preservation")

    # 4. Confidence vs actual correctness (field-level)
    fig, ax = plt.subplots(figsize=(6, 4))
    if not field_df.empty:
        jitter = np.random.default_rng(0).normal(0, 0.01, len(field_df))
        ax.scatter(field_df["field_confidence"], field_df["correct"].astype(float) + jitter, s=6, alpha=0.25)
    ax.set_xlabel("Field confidence"); ax.set_ylabel("Correct (0/1, jittered)")
    ax.set_title("Confidence vs. actual correctness")
    _save(fig, out, "04_confidence_vs_correctness"); names.append("04_confidence_vs_correctness")

    # 5. Reliability / calibration diagram
    fig, ax = plt.subplots(figsize=(5, 5))
    if not field_df.empty:
        ece = expected_calibration_error(field_df["field_confidence"].tolist(), field_df["correct"].astype(int).tolist(), n_bins=10)
        xs = [(b.lower + b.upper) / 2 for b in ece.bins if b.count > 0]
        ys = [b.accuracy for b in ece.bins if b.count > 0]
        ax.plot([0, 1], [0, 1], "k--", alpha=0.5, label="perfect calibration")
        ax.plot(xs, ys, "o-", label=f"observed (ECE={ece.ece:.3f})")
    ax.set_xlabel("Mean predicted confidence"); ax.set_ylabel("Empirical accuracy")
    ax.set_title("Reliability diagram"); ax.legend()
    _save(fig, out, "05_reliability_diagram"); names.append("05_reliability_diagram")

    # 6. Accuracy vs confidence threshold & 7. Coverage vs confidence threshold
    if not field_df.empty:
        points = selective_prediction_curve(field_df["field_confidence"].tolist(), field_df["correct"].astype(int).tolist())
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.plot([p.threshold for p in points], [p.accuracy for p in points], "o-")
        ax.set_xlabel("Confidence threshold (gamma)"); ax.set_ylabel("Accuracy"); ax.set_title("Accuracy vs. confidence threshold")
        _save(fig, out, "06_accuracy_vs_threshold"); names.append("06_accuracy_vs_threshold")

        fig, ax = plt.subplots(figsize=(6, 4))
        ax.plot([p.threshold for p in points], [p.coverage for p in points], "o-", color="tab:orange")
        ax.set_xlabel("Confidence threshold (gamma)"); ax.set_ylabel("Coverage"); ax.set_title("Coverage vs. confidence threshold")
        _save(fig, out, "07_coverage_vs_threshold"); names.append("07_coverage_vs_threshold")

    # 8. End-to-end latency distribution
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(df["latency_total_ms"], bins=20, color="tab:green", alpha=0.7)
    ax.set_xlabel("Total latency (ms)"); ax.set_ylabel("Count"); ax.set_title("End-to-end latency distribution")
    _save(fig, out, "08_latency_distribution"); names.append("08_latency_distribution")

    # 9. Transformation quality by invoice complexity
    fig, ax = plt.subplots(figsize=(6, 4))
    order_c = ["simple", "medium", "complex"]
    means = [df[df.complexity_level == c]["semantic_preservation"].mean() for c in order_c]
    stds = [df[df.complexity_level == c]["semantic_preservation"].std() for c in order_c]
    ax.bar(order_c, means, yerr=stds, capsize=4, color="tab:blue", alpha=0.8)
    ax.set_ylabel("Mean preservation"); ax.set_title("Transformation quality by complexity")
    _save(fig, out, "09_quality_by_complexity"); names.append("09_quality_by_complexity")

    # 10. Incremental vs complete aggregation comparison
    fig, ax = plt.subplots(figsize=(6, 4))
    sub = df[df.transformation_mode.isin(["aggregated", "incremental"])]
    metrics = ["semantic_preservation", "information_loss", "semantic_f1", "global_confidence"]
    x = np.arange(len(metrics)); width = 0.35
    agg_means = [sub[sub.transformation_mode == "aggregated"][m].mean() for m in metrics]
    inc_means = [sub[sub.transformation_mode == "incremental"][m].mean() for m in metrics]
    ax.bar(x - width / 2, agg_means, width, label="aggregated")
    ax.bar(x + width / 2, inc_means, width, label="incremental")
    ax.set_xticks(x); ax.set_xticklabels(["Preservation", "Loss", "F1", "Confidence"], rotation=20)
    ax.set_title("Incremental vs. complete aggregation"); ax.legend()
    _save(fig, out, "10_incremental_vs_aggregated"); names.append("10_incremental_vs_aggregated")

    return names
