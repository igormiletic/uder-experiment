# UDER Experiment: AI-Assisted Invoice Transformation Evaluation Framework

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue) ![License: MIT](https://img.shields.io/badge/license-MIT-green)


A research evaluation framework for the question:

> Can AI-assisted transformation convert heterogeneous invoice representations from multiple
> established invoice standards into a common local invoice model while preserving semantic
> information and providing reliable confidence estimates?

It simulates the **LDC / UCS / UDER** architecture (Linked Data Client / UDER Control System /
Uniform Data Entity Representation) described below, generates a reproducible multi-standard
invoice dataset with independent ground truth, and measures AI-assisted transformation quality
against that ground truth with deterministic, non-AI-judged metrics.

This is a standalone sibling of two existing prototypes: `dlds` (a Python/FastAPI UCS
implementation) and `ldc` (a Java/Spring LDC implementation, including a real SwissGPT/Nuvio
`LLMService`). This framework does not depend on either at runtime; it re-implements the same
request-request propagation protocol as an isolated, reproducible harness so experiments don't
require a live database, Kafka, or a running Java service.

## Contents

1. [Quick start](#quick-start)
2. [Architecture recap](#architecture-recap)
3. [Repository layout](#repository-layout)
4. [Setup](#setup)
5. [Dataset structure](#1-dataset-structure) · [generation](#2-how-to-generate-the-dataset) · [ground truth](#3-how-ground-truth-works)
6. [Running the test suite](#4-running-the-deterministic-test-suite)
7. [Configuring a real AI provider](#5-configuring-a-real-ai-provider-optional)
8. [Running experiments](#6-running-experiments)
9. [Metrics](#7-how-each-metric-is-calculated)
10. [Reproducing tables and figures](#8-reproducing-the-tables-and-figures)
11. [Output reference](#output-reference)
12. [Reproducibility checklist](#reproducibility-checklist)
13. [Assumptions and deviations](#assumptions-and-deviations) · [Citing](#citing) · [License](#license)

## Quick start

No AI credentials needed -- this exercises the full pipeline with the deterministic and mock transformers:

```bash
git clone <repo-url> && cd uder-experiment
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q                                                   # 37 tests
uder-experiment run --testdata testdata/scenarios --output results
uder-experiment analyze                                     # -> results/tables/
uder-experiment figures                                     # -> results/figures/
```

`python -m uder_experiment.cli ...` is equivalent to `uder-experiment ...` everywhere below.

## Architecture recap

```
LDC --request--> UCS-1 --response (Entity 1, immediate)--> LDC
UCS-1 --request (X-Transaction-ID, X-LDC-Response-URL)--> UCS-2..N
UCS-2..N --request to X-LDC-Response-URL--> LDC   (async delivery of linked entities)
LDC aggregates all entities for a transaction, then runs AI-assisted transformation
into CanonicalInvoice, its local data model.
```

`src/uder_experiment/network/` implements this over `httpx.ASGITransport` (real ASGI
request/response cycles and real headers, no real sockets), so it is fast and deterministic in
tests while still exercising genuine concurrent HTTP semantics -- see
[`network/simulator.py`](src/uder_experiment/network/simulator.py) and
[`network/ucs_node.py`](src/uder_experiment/network/ucs_node.py).

## Repository layout

```
src/uder_experiment/
  schema/        CanonicalInvoice pydantic model (versioned) + JSON Schema export
  scenario/      InvoiceScenario truth model, generator, UBL/CII/Source-C/ground-truth renderers
  uder/          UDER entity graph model + UBL/CII/Source-C -> UDER converters
  network/       simulated UCS nodes, LDC callback, propagation simulator, fault injection
  aggregation/   TransactionContext (E_tau/D_tau/P_tau) + LDCAggregator
  transform/     Transformer interface: deterministic / mock AI / real AI (OpenAI-compatible)
  metrics/       feature extraction, preservation/precision/F1, calibration, consistency checks
  experiment/    matrix definition, runner, JSONL storage, statistical analysis, figures
  cli.py         `uder-experiment generate|run|analyze|figures`
testdata/scenarios/   committed dataset (50 scenarios x {ground-truth, ubl, cii, source-c})
results/              experiment output (JSONL, tables, figures) -- git-ignored, regenerate via the CLI
tests/                pytest suite: protocol, data, transformation, metrics, integration
.env.example          template for the optional real-AI environment variables
CITATION.cff          citation metadata
```

## Setup

Requires Python >= 3.11.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # or: pip install -r requirements.txt && pip install -e .
```

## 1. Dataset structure

Every logical invoice scenario lives in `testdata/scenarios/scenario-NNN/`:

```
scenario-NNN/
  ground-truth.json   # independent CanonicalInvoice ground truth
  ubl.xml              # OASIS UBL 2.1 Invoice (Source A)
  cii.xml               # UN/CEFACT Cross Industry Invoice (Source B)
  source-c.json         # OAGIS-derived normalized JSON invoice (Source C)
```

`testdata/scenarios/index.json` lists every scenario's id/complexity/seed/line-count.

## 2. How to generate the dataset

```bash
python -m uder_experiment.cli generate --output testdata/scenarios --seed 42 --scenarios 50
```

Deterministic: the same `--seed` always produces byte-identical scenarios. Complexity is split
~34/36/30% simple/medium/complex (`scenario/generator.py::DEFAULT_COMPLEXITY_DISTRIBUTION`),
shuffled with the same seed so scenario numbering doesn't correlate with complexity.

### Why these three source standards

- **Source A -- UBL 2.1**: nests parties under invoice-specific `AccountingSupplierParty` /
  `AccountingCustomerParty`, uses `cac:`/`cbc:` namespaces, ISO dates, `LegalMonetaryTotal`.
- **Source B -- UN/CEFACT CII**: parties instead live under one
  `ApplicableHeaderTradeAgreement`, dates are `udt:DateTimeString format="102"` (CCYYMMDD), totals
  are one flat `SpecifiedTradeSettlementHeaderMonetarySummation` block -- different structural
  paths and naming for the same concepts, as required by the spec.
- **Source C -- OAGIS**, rendered as normalized JSON (see
  [`scenario/render_source_c.py`](src/uder_experiment/scenario/render_source_c.py) for the full
  rationale and field-correspondence table): a generic `ApplicationArea`/`DataArea` *messaging*
  envelope (not itself a business document root, unlike UBL/CII), generic typed `PartyIDs` lists
  instead of invoice-specific party roles, and JSON rather than XML -- so the transformer must
  generalize across data *formats*, not just XML dialects. Peppol BIS was deliberately **not**
  used as Source C because it is UBL-based and would be a trivial structural variant of Source A.

All three are rendered from one `InvoiceScenario` (`scenario/truth_model.py`) per logical
invoice, so they are guaranteed to describe the same business invoice while using genuinely
different structures.

## 3. How ground truth works

`ground-truth.json` is rendered directly from `InvoiceScenario` by
[`scenario/render_ground_truth.py`](src/uder_experiment/scenario/render_ground_truth.py) --
**not** derived from the UBL/CII/Source-C renderings, and never derived from any transformer's
output. All four artifacts (three sources + ground truth) are independent, deterministic, pure
renderings of the same underlying scenario object. This is what makes the ground truth
independent per the experimental design: nothing about evaluation ever depends on what an AI
transformer produced.

## 4. Running the deterministic test suite

No network access or AI credentials required -- everything runs against the in-process ASGI
simulator and the deterministic/mock transformers.

```bash
pytest -q
```

Covers (see `tests/`): protocol propagation/fault-injection, cross-standard data equivalence,
transformation correctness at each complexity level, and metric correctness (perfect-match
preservation=1, Brier/ECE=0 for calibrated synthetic predictions, etc.).

## 5. Configuring a real AI provider (optional)

The real transformer ([`transform/real_ai.py`](src/uder_experiment/transform/real_ai.py)) is a
generic OpenAI-compatible chat-completions client, fully optional and env-gated. Copy
[`.env.example`](.env.example) to `.env` (git-ignored) and load it, or export directly:

```bash
export AI_API_KEY=sk-...
export AI_API_BASE_URL=https://your-openai-compatible-endpoint/v1   # optional
export AI_MODEL=gpt-4o-mini                                          # optional (default)
export AI_MIN_INTERVAL_SECONDS=5                                     # optional: min gap between calls
export AI_REQUEST_TIMEOUT_SECONDS=60                                 # optional: per-call timeout
```

| Variable | Default | Meaning |
|---|---|---|
| `AI_API_KEY` | *(unset)* | Required for `--use-real-ai`. |
| `AI_API_BASE_URL` | provider default | Any OpenAI-compatible endpoint. |
| `AI_MODEL` | `gpt-4o-mini` | Model name; `--ai-model` overrides it. |
| `AI_MIN_INTERVAL_SECONDS` | `5` | Global rate limit between LLM calls (`--min-interval` overrides). |
| `AI_REQUEST_TIMEOUT_SECONDS` | `60` | Per-call timeout before retry/skip (`--request-timeout` overrides). |

If `AI_API_KEY` is unset (or `openai` isn't installed), `is_available()` returns `False`, the CLI
refuses `--use-real-ai` with a clear message, and nothing else in the framework requires it. The
model is asked to return `{"transformedData": ..., "confidence": ..., "fieldConfidences": {...}}`
in JSON-object mode; failed calls are retried (2 retries), and these confidences are explicitly
confidence *estimates* (self-assessments), not calibrated probabilities.

## 6. Running experiments

```bash
# deterministic / mock evaluation (no AI credentials needed)
uder-experiment run \
  --testdata testdata/scenarios --output results \
  --modes deterministic,isolated,aggregated,incremental \
  --error-rate 0.15

# real LLM evaluation (costs money, non-deterministic; see notes below)
uder-experiment run --use-real-ai --ai-model gpt-4o-mini --temperature 0 \
  --prompt-version v1 --modes isolated,aggregated,incremental --output results-real
```

This runs the full `{ubl,cii,source-c} x {simple,medium,complex} x {deterministic,isolated,aggregated,incremental}`
matrix (600 runs against the 50-scenario dataset) end to end: UCS propagation -> LDC aggregation
-> transform -> schema validation -> metric evaluation -> JSONL persistence.

### `run` options

| Option | Default | Description |
|---|---|---|
| `--testdata` | `testdata/scenarios` | Dataset directory. |
| `--output` | `results` | Output directory (created if missing). |
| `--sources` | all | Comma-separated subset of `ubl,cii,source-c`. |
| `--complexities` | all | Subset of `simple,medium,complex`. |
| `--modes` | all | Subset of `deterministic,isolated,aggregated,incremental`. |
| `--error-rate` | `0.15` | Simulated error rate of the **mock** AI transformer (ignored with `--use-real-ai`). |
| `--ai-model` | `mock-deterministic-v1` | Model label recorded in results; with `--use-real-ai` a real model name (falls back to `AI_MODEL`). |
| `--prompt-version` | `v1` | Label recorded with each run, for prompt A/B comparisons. |
| `--temperature` | `0.0` | Sampling temperature (real AI). |
| `--use-real-ai` | off | Use `RealAITransformer` for AI modes (`isolated`/`aggregated`/`incremental`). |
| `--min-interval` / `--request-timeout` | env / 5s / 60s | Real-AI rate limit and per-call timeout. |
| `-v` (global, before the subcommand) | off | DEBUG logging incl. raw LLM responses. |

Example: `uder-experiment -v run --sources ubl --complexities simple --modes aggregated --use-real-ai`.

The four transformation modes correspond to the four baselines the research question compares:
`deterministic` (Baseline 1, rule-based, no AI), `isolated` (Baseline 2, each UDER entity
transformed independently, then merged), `aggregated` (Baseline 3, transform after full
aggregation), `incremental` (Baseline 4, refined as each entity arrives; only the final call is
scored).

**Robustness.** If a single (scenario, source, mode) combination raises, the error is logged and a
placeholder record (`accepted=false`, zero scores, `error` populated) is written so the matrix
continues and row counts stay complete. Filter on `error` when analysing real-AI runs.

**Real-AI cost.** A full real-AI matrix is 450 AI runs (`isolated` makes one call per entity,
`incremental` one per entity as well), throttled by `AI_MIN_INTERVAL_SECONDS`. Start with a narrow
subset (`--sources`, `--complexities`) to estimate cost and time first.

**Note on the mock-transformer numbers themselves**: `MockAITransformer` seeds its simulated
error injection off `(entity ids, mode, seed_offset)` (see `transform/mock_ai.py::_seed_for`) --
including the mode label. This means "aggregated" vs. "incremental" deltas you see in
mock-generated results reflect *different simulated error draws*, not a proven architectural
capability difference. The mock transformer's job is to validate the metrics/pipeline machinery
deterministically; the actual scientific answer to the research question requires running the
matrix with `--use-real-ai` against a real model. Use a separate `--output` directory per model or
prompt version so runs are never mixed.

## 7. How each metric is calculated

- **Semantic feature extraction** (`metrics/features.py`): both the ground truth and the
  transformer output are flattened into the same path-keyed feature space. Invoice line items
  and tax-breakdown entries are keyed by their own content (`lineId`, tax `category`), not array
  position, so re-ordered output isn't penalized.
- **Preservation / Information loss** (`metrics/preservation.py`): weighted fraction of expected
  features correctly reproduced (`information_loss = 1 - preservation`); required fields
  (invoice number, totals, party names, ...) carry higher weight than optional ones.
- **Precision**: weighted fraction of *output* features that are supported -- either matching
  ground truth or literally present somewhere in the raw source UDER entity properties
  (`metrics/features.py::source_support_values`). Catches hallucinated/unsupported values without
  any AI judge.
- **F1**: harmonic mean of precision and preservation, zero-division safe.
- **Value accuracy** (`metrics/value_accuracy.py`): exact match for booleans/dates/sets;
  relative-tolerance numeric comparison for amounts; configurable exact / normalized /
  difflib-similarity comparison for free text.
- **Confidence calibration** (`metrics/calibration.py`): Brier score, Expected Calibration Error
  (configurable bin count), Pearson/Spearman confidence-correctness correlation, and
  accuracy/coverage curves at configurable confidence thresholds.
- **Arithmetic consistency** (`metrics/consistency.py`): deterministic reconciliation of
  `netAmount ~= qty*unitPrice - allowance + charge`, `taxAmount ~= taxable*rate/100`,
  `grossAmount ~= net + tax`, `payableAmount ~= grossAmount` (see that module's docstring for why
  allowances/charges don't re-apply at the payable step in this framework's convention), all with
  configurable rounding tolerance.
- **Transaction-level metrics** (`metrics/transaction_metrics.py`): entity completeness,
  duplicate rate, transformation completeness (fraction of expected features populated, whether
  or not correct), and latency percentile distributions.

No metric in `metrics/` calls an AI model (spec Section 23): correctness is always ground-truth
+ schema + deterministic feature/arithmetic comparison.

## 8. Reproducing the tables and figures

```bash
uder-experiment analyze --results results --testdata testdata/scenarios --output results/tables
uder-experiment figures --results results --output results/figures
```

Both read only the persisted JSONL in `--results` -- they never re-run experiments -- so they are
reproducible from any prior run's output.

`analyze` writes `table{1..5}_*.{csv,md}` (dataset composition, transformation quality,
confidence quality, performance, complexity impact) plus `summary_statistics.csv`
(count/mean/median/std/min/max/p50/p95/p99/95%-CI per metric, grouped by source standard and
transformation mode). `figures` writes 10 PNGs (information loss by standard, preservation by mode,
precision-vs-preservation, confidence-vs-correctness, reliability diagram, accuracy- and
coverage-vs-threshold, latency distribution, quality-by-complexity, incremental-vs-aggregated).

## Output reference

```
results/
  experiments.jsonl        one ExperimentRecord per (scenario, source, mode) run
  field_results.jsonl      one FieldResultRecord per compared feature per run
  tables/                  table1..table5 (.csv, .md) + summary_statistics.csv
  figures/                 01_*.png ... 10_*.png
```

Key `experiments.jsonl` fields: `source_standard`, `invoice_scenario_id`, `complexity_level`,
`transformation_mode`, `ai_model`, `prompt_version`, `temperature`, `semantic_preservation`,
`information_loss`, `semantic_precision`, `semantic_f1`, `value_accuracy`, `global_confidence`,
`brier_score`, `calibration_error`, `schema_valid`, `consistency_score`, `latency_*_ms`,
`accepted`, `error`. `field_results.jsonl` joins on `experiment_id` and holds per-field
`path`, `weight`, `required`, `expected_value`, `actual_value`, `correct`.

## Reproducibility checklist

- Dataset: `uder-experiment generate --seed 42 --scenarios 50` regenerates the committed dataset byte-for-byte.
- Deterministic and mock modes are fully seeded; re-running gives identical metrics (latency aside).
- For real-AI runs record `--ai-model`, `--prompt-version`, `--temperature`, the endpoint, and the date
  (model behaviour drifts); these are stored per record except endpoint/date. LLM output is not
  guaranteed reproducible even at temperature 0 -- repeat runs and report variance.
- Keep each run in its own `--output` directory and archive the JSONL files with your paper.
- Extending: add a transformer by implementing `transform/base.py::Transformer`; add a source standard
  by adding a renderer in `scenario/` and a converter in `uder/`; add a metric under `metrics/`.
  Run `pytest -q` before and after.

## Assumptions and deviations

- Header names follow the spec exactly (`X-Transaction-ID`, `X-LDC-Response-URL`), which differ
  from the sibling `dlds` prototype's existing `X-client-url`/`X-request-id` naming -- this
  framework is a separate harness, not a client of `dlds`'s live endpoints.
- The UCS network topology is fixed at 5 simulated nodes (Invoice / supplier Party / customer
  Party / Lines+Products / Tax+Payment), matching the spec's Section 9 example; entity-to-node
  assignment is deterministic by entity type, not configurable per run.
- UBL/CII tax category codes (`S`/`AA`/`Z`, per UNCL5305) genuinely collapse "Reduced" and
  "Super-Reduced" into one code (`AA`) in real-world UBL/CII -- the deterministic transformer
  disambiguates by rate (`transform/deterministic.py::_infer_category`), which is not always
  correct. This is intentional, realistic source-format lossiness, not a bug.
- Line/document allowances and charges are netted directly into `netAmount` in this framework's
  `CanonicalInvoice` convention (see `metrics/consistency.py` docstring); `payableAmount`
  reconciles against `grossAmount` rather than `grossAmount + charges - allowances`.
- "Mixed currencies" (spec Section 7, Complex level) is intentionally out of scope: every
  scenario uses one settlement currency (EUR), since CanonicalInvoice models a single
  `commercialContext.currency`; multi-currency invoices are a plausible future extension of the
  target schema, not implemented here.
- An AI-judge evaluator is intentionally **not** implemented, per spec Section 23's constraint
  that AI output must not be judged by another unvalidated AI model.

## Citing

If you use this framework in academic work, please cite it using [`CITATION.cff`](CITATION.cff)
(GitHub's "Cite this repository" button).

## License

Released under the [MIT License](LICENSE).
