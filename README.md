# UDER Experiment: AI-Assisted Invoice Transformation Evaluation Framework

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
testdata/scenarios/   generated dataset (50 scenarios x {ground-truth, ubl, cii, source-c})
results/              generated experiment output (JSONL, tables, figures)
tests/                pytest suite: protocol, data, transformation, metrics, integration
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
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
generic OpenAI-compatible client, fully optional and env-gated:

```bash
export AI_API_KEY=sk-...
export AI_API_BASE_URL=https://your-openai-compatible-endpoint/v1   # optional
export AI_MODEL=gpt-4o-mini                                          # optional
```

If `AI_API_KEY` is unset (or the `openai` package isn't installed), `RealAITransformer.is_available()`
returns `False` and nothing in the framework requires it -- the experiment runner and all tests
use `DeterministicTransformer` / `MockAITransformer` by default. The model is asked to return
`{"transformedData": ..., "confidence": ..., "fieldConfidences": {...}}`; these are explicitly
labeled confidence *estimates*, not calibrated probabilities, per the experimental design.

## 6. Running experiments

```bash
# deterministic / mock evaluation (no AI credentials needed)
python -m uder_experiment.cli run \
  --testdata testdata/scenarios --output results \
  --modes deterministic,isolated,aggregated,incremental \
  --error-rate 0.15
```

This runs the full `{ubl,cii,source-c} x {simple,medium,complex} x {deterministic,isolated,aggregated,incremental}`
matrix (600 runs against the 50-scenario dataset) end to end: UCS propagation -> LDC aggregation
-> transform -> schema validation -> metric evaluation -> JSONL persistence. `--sources`,
`--complexities`, and `--modes` accept comma-separated subsets to narrow the matrix.

The four transformation modes correspond to the four baselines the research question compares:
`deterministic` (Baseline 1, rule-based, no AI), `isolated` (Baseline 2, each UDER entity
transformed independently), `aggregated` (Baseline 3, transform after full aggregation),
`incremental` (Baseline 4, refined as each entity arrives).

To use the real AI transformer instead of the mock, set the environment variables from step 5
and swap the transformer construction in `experiment/runner.py::_build_transformer`
(kept as an explicit, reviewable code change rather than a silent runtime auto-switch, since
real-AI runs cost money and produce non-deterministic output).

**Note on the mock-transformer numbers themselves**: `MockAITransformer` seeds its simulated
error injection off `(entity ids, mode, seed_offset)` (see `transform/mock_ai.py::_seed_for`) --
including the mode label. This means "aggregated" vs. "incremental" deltas you see in
mock-generated results reflect *different simulated error draws*, not a proven architectural
capability difference. The mock transformer's job is to validate the metrics/pipeline machinery
deterministically (Section 11 Mode B); the actual scientific answer to the research question
requires running the matrix with `RealAITransformer` against a real model.

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
python -m uder_experiment.cli analyze --results results --testdata testdata/scenarios --output results/tables
python -m uder_experiment.cli figures --results results --output results/figures
```

Both read only from the persisted `results/experiments.jsonl` / `results/field_results.jsonl` --
never re-run experiments -- so they're reproducible from any prior run's output.

`results/tables/` gets `table{1..5}_*.{csv,md}` (dataset composition, transformation quality,
confidence quality, performance, complexity impact) plus `summary_statistics.csv`
(count/mean/median/std/min/max/p50/p95/p99/95%-CI per metric, grouped by source standard and
transformation mode). `results/figures/` gets the 10 required PNGs (loss distribution,
preservation by mode, precision-vs-preservation, confidence-vs-correctness, reliability diagram,
accuracy/coverage-vs-threshold, latency distribution, quality-by-complexity, incremental-vs-aggregated).

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
