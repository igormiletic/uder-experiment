"""Statistical aggregation and publication-ready Tables 1-5 (spec Sections 20-21)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from uder_experiment.experiment.storage import read_jsonl
from uder_experiment.metrics.transaction_metrics import describe

_METRICS = ["semantic_preservation", "information_loss", "semantic_precision", "semantic_f1",
            "value_accuracy", "global_confidence", "brier_score", "calibration_error", "latency_total_ms"]

_GROUP_DIMENSIONS = ["source_standard", "complexity_level", "transformation_mode", "ai_model", "prompt_version"]


def load_experiments(results_dir: str | Path) -> pd.DataFrame:
    rows = read_jsonl(Path(results_dir) / "experiments.jsonl")
    return pd.DataFrame(rows)


def summary_statistics(df: pd.DataFrame, group_by: list[str] | None = None) -> pd.DataFrame:
    group_by = group_by or []
    out_rows = []
    groups = df.groupby(group_by) if group_by else [((), df)]
    for key, sub in groups:
        key = key if isinstance(key, tuple) else (key,)
        for metric in _METRICS:
            if metric not in sub:
                continue
            dist = describe(sub[metric].dropna().tolist())
            row = dict(zip(group_by, key)) if group_by else {}
            row.update({
                "metric": metric, "count": dist.count, "mean": dist.mean, "median": dist.median,
                "std": dist.std, "min": dist.minimum, "max": dist.maximum,
                "p50": dist.p50, "p95": dist.p95, "p99": dist.p99,
                "ci95_low": dist.ci95_low, "ci95_high": dist.ci95_high,
            })
            out_rows.append(row)
    return pd.DataFrame(out_rows)


def table_1_dataset_composition(testdata_dir: str | Path) -> pd.DataFrame:
    import json
    index = json.loads((Path(testdata_dir) / "index.json").read_text())
    df = pd.DataFrame(index)
    pivot = df.pivot_table(index=[], columns="complexity", values="scenario_id", aggfunc="count", fill_value=0)
    rows = []
    for standard in ["UBL", "CII", "Source-C"]:
        row = {"Standard": standard}
        for level in ["simple", "medium", "complex"]:
            row[level.capitalize()] = int(pivot[level].iloc[0]) if level in pivot else 0
        row["Total"] = sum(row[level.capitalize()] for level in ["simple", "medium", "complex"])
        rows.append(row)
    return pd.DataFrame(rows)


def table_2_transformation_quality(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["source_standard", "transformation_mode"]).agg(
        Preservation=("semantic_preservation", "mean"), **{"Information Loss": ("information_loss", "mean")},
        Precision=("semantic_precision", "mean"), F1=("semantic_f1", "mean"),
    ).reset_index()
    g.columns = ["Standard", "Mode", "Preservation", "Information Loss", "Precision", "F1"]
    return g.round(3)


def table_3_confidence_quality(df: pd.DataFrame) -> pd.DataFrame:
    def actual_accuracy(sub):
        return sub["value_accuracy"].mean()

    rows = []
    for standard, sub in df.groupby("source_standard"):
        rows.append({
            "Standard": standard,
            "Mean Confidence": round(sub["global_confidence"].mean(), 3),
            "Actual Accuracy": round(actual_accuracy(sub), 3),
            "Brier Score": round(sub["brier_score"].mean(), 3),
            "ECE": round(sub["calibration_error"].mean(), 3),
        })
    return pd.DataFrame(rows)


def table_4_performance(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (standard, mode), sub in df.groupby(["source_standard", "transformation_mode"]):
        dist = describe(sub["latency_total_ms"].tolist())
        rows.append({
            "Standard": standard, "Mode": mode, "Mean Latency (ms)": round(dist.mean, 2),
            "Median": round(dist.median, 2), "P95": round(dist.p95, 2), "P99": round(dist.p99, 2),
        })
    return pd.DataFrame(rows)


def table_5_complexity_impact(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    order = {"simple": 0, "medium": 1, "complex": 2}
    for complexity, sub in df.groupby("complexity_level"):
        rows.append({
            "Complexity": complexity,
            "Preservation": round(sub["semantic_preservation"].mean(), 3),
            "Loss": round(sub["information_loss"].mean(), 3),
            "Confidence": round(sub["global_confidence"].mean(), 3),
            "Accuracy": round(sub["value_accuracy"].mean(), 3),
        })
    rows.sort(key=lambda r: order.get(r["Complexity"], 99))
    return pd.DataFrame(rows)


def write_all_tables(results_dir: str | Path, testdata_dir: str | Path, output_dir: str | Path) -> dict[str, pd.DataFrame]:
    df = load_experiments(results_dir)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    tables = {
        "table1_dataset_composition": table_1_dataset_composition(testdata_dir),
        "table2_transformation_quality": table_2_transformation_quality(df),
        "table3_confidence_quality": table_3_confidence_quality(df),
        "table4_performance": table_4_performance(df),
        "table5_complexity_impact": table_5_complexity_impact(df),
    }
    for name, table in tables.items():
        table.to_csv(out / f"{name}.csv", index=False)
        (out / f"{name}.md").write_text(table.to_markdown(index=False))
    summary = summary_statistics(df, group_by=["source_standard", "transformation_mode"])
    summary.to_csv(out / "summary_statistics.csv", index=False)
    return tables
