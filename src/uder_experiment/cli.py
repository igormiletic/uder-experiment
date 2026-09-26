"""CLI: uder-experiment generate|run|analyze|figures."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("uder_experiment.cli")


def _cmd_generate(args: argparse.Namespace) -> None:
    from uder_experiment.scenario.generator import generate_dataset, write_dataset

    logger.info("Generating %d scenarios (seed=%d) -> %s", args.scenarios, args.seed, args.output)
    results = generate_dataset(count=args.scenarios, seed=args.seed)
    write_dataset(results, args.output)
    logger.info("Wrote %d scenario directories to %s", len(results), args.output)


def _cmd_run(args: argparse.Namespace) -> None:
    import os

    from uder_experiment.experiment.runner import run_full_matrix

    modes = args.modes.split(",") if args.modes else None
    sources = args.sources.split(",") if args.sources else None
    complexities = args.complexities.split(",") if args.complexities else None
    if args.use_real_ai:
        if args.min_interval is not None:
            os.environ["AI_MIN_INTERVAL_SECONDS"] = str(args.min_interval)
        if args.request_timeout is not None:
            os.environ["AI_REQUEST_TIMEOUT_SECONDS"] = str(args.request_timeout)
        from uder_experiment.transform.real_ai import is_available
        if not is_available():
            raise SystemExit(
                "--use-real-ai requires AI_API_KEY to be set and the `openai` package installed; "
                "see README section 5."
            )
        logger.info("Real AI transformer enabled (min interval between calls: %ss, per-call timeout: %ss)",
                    os.environ.get("AI_MIN_INTERVAL_SECONDS", "5"),
                    os.environ.get("AI_REQUEST_TIMEOUT_SECONDS", "60"))
    logger.info("Running experiment matrix: sources=%s complexities=%s modes=%s", sources, complexities, modes)
    records = asyncio.run(run_full_matrix(
        args.testdata, args.output, sources=sources, complexities=complexities, modes=modes,
        error_rate=args.error_rate, ai_model=args.ai_model, prompt_version=args.prompt_version,
        temperature=args.temperature, use_real_ai=args.use_real_ai,
    ))
    logger.info("Completed %d experiment runs -> %s", len(records), args.output)


def _cmd_analyze(args: argparse.Namespace) -> None:
    from uder_experiment.experiment.analyze import write_all_tables

    tables = write_all_tables(args.results, args.testdata, args.output)
    logger.info("Wrote %d tables to %s", len(tables), args.output)


def _cmd_figures(args: argparse.Namespace) -> None:
    from uder_experiment.experiment.figures import generate_all_figures

    names = generate_all_figures(args.results, args.output)
    logger.info("Wrote %d figures to %s", len(names), args.output)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="uder-experiment")
    p.add_argument("-v", "--verbose", action="store_true",
                    help="DEBUG-level logging, including raw LLM response bodies for --use-real-ai runs")
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="generate the reproducible scenario dataset")
    g.add_argument("--output", default="testdata/scenarios")
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--scenarios", type=int, default=50)
    g.set_defaults(func=_cmd_generate)

    r = sub.add_parser("run", help="run the experiment matrix")
    r.add_argument("--testdata", default="testdata/scenarios")
    r.add_argument("--output", default="results")
    r.add_argument("--sources", default=None, help="comma-separated: ubl,cii,source-c")
    r.add_argument("--complexities", default=None, help="comma-separated: simple,medium,complex")
    r.add_argument("--modes", default=None, help="comma-separated: deterministic,isolated,aggregated,incremental")
    r.add_argument("--error-rate", type=float, default=0.15, help="mock AI transformer error rate")
    r.add_argument("--ai-model", default="mock-deterministic-v1")
    r.add_argument("--prompt-version", default="v1")
    r.add_argument("--temperature", type=float, default=0.0)
    r.add_argument("--use-real-ai", action="store_true",
                    help="use RealAITransformer (requires AI_API_KEY) instead of MockAITransformer "
                         "for AI-based modes (isolated/aggregated/incremental)")
    r.add_argument("--min-interval", type=float, default=None,
                    help="minimum seconds between real LLM calls (default: AI_MIN_INTERVAL_SECONDS env "
                         "var, or 5.0); only relevant with --use-real-ai")
    r.add_argument("--request-timeout", type=float, default=None,
                    help="max seconds to wait for a single LLM call before abandoning it and retrying/"
                         "moving on (default: AI_REQUEST_TIMEOUT_SECONDS env var, or 60.0); only "
                         "relevant with --use-real-ai")
    r.set_defaults(func=_cmd_run)

    a = sub.add_parser("analyze", help="compute statistics and Tables 1-5")
    a.add_argument("--results", default="results")
    a.add_argument("--testdata", default="testdata/scenarios")
    a.add_argument("--output", default="results/tables")
    a.set_defaults(func=_cmd_analyze)

    f = sub.add_parser("figures", help="generate the 10 required figures")
    f.add_argument("--results", default="results")
    f.add_argument("--output", default="results/figures")
    f.set_defaults(func=_cmd_figures)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "verbose", False):
        logging.getLogger("uder_experiment").setLevel(logging.DEBUG)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
