"""Mode A: real AI transformer, generic OpenAI-compatible client, fully env-gated.

Reads AI_API_KEY / AI_API_BASE_URL / AI_MODEL from the environment. If
AI_API_KEY is unset (or the `openai` package is unavailable), `is_available()`
returns False and callers should fall back to the mock/deterministic
transformer -- nothing in this module is imported or required for tests/CI.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

from uder_experiment.schema.canonical_invoice import CANONICAL_INVOICE_SCHEMA_VERSION
from uder_experiment.schema.json_schema import canonical_invoice_json_schema
from uder_experiment.transform.base import Transformer, TransformResult
from uder_experiment.transform.context import TransformationContext
from uder_experiment.uder.entities import UDEREntity

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an invoice data transformation engine for a Linked Data Client (LDC).
You receive a set of UDER (Uniform Data Entity Representation) entities describing fragments
of one logical invoice, originally sourced from a heterogeneous e-invoicing standard (UBL,
UN/CEFACT CII, or an OAGIS-derived JSON representation). Transform them into the LDC's local
CanonicalInvoice model, given below as a JSON Schema. The UDER layer has already normalized
field names/entity types across source standards -- you do not need to know which standard an
entity came from to interpret it.

## Input shape

Each UDER entity has: entityId, entityType, representation, sourceStandard, properties (the
actual data, already using the field names below), and links (edges to other entities in this
same request, or -- in incremental mode -- to entities in priorAggregatedContext). Each link is
{"predicate": "<name>", "targetEntityId": "<id of another entity in this payload>"}.

## Entity types and how they map onto CanonicalInvoice

This mapping is fixed -- use it directly instead of guessing:
- Invoice (root; other entities are reached from it via links):
  properties.number -> invoice.identity.number
  properties.issueDate -> invoice.identity.issueDate
  properties.dueDate -> invoice.identity.dueDate
  properties.currency -> invoice.commercialContext.currency
  properties.purchaseOrderReference -> invoice.commercialContext.purchaseOrderReference
  properties.contractReference -> invoice.commercialContext.contractReference
  properties.netAmount -> invoice.financialSummary.netAmount
  properties.taxInclusiveAmount -> invoice.financialSummary.grossAmount
  properties.allowanceTotalAmount -> invoice.financialSummary.allowanceTotal
  properties.chargeTotalAmount -> invoice.financialSummary.chargeTotal
  properties.payableAmount -> invoice.financialSummary.payableAmount
  link hasSupplier -> invoice.parties.supplier (a Party entity)
  link hasCustomer -> invoice.parties.customer (a Party entity)
  link hasLine -> one entry in invoice.items[] (an InvoiceLine entity)
  link hasTaxSummary -> supplies invoice.financialSummary.taxAmount / .taxBreakdown (a TaxSummary entity)
  link hasPayment -> invoice.payment (a PaymentInformation entity)
- Party (supplier or customer, per which link pointed at it):
  properties.name -> .name ; properties.identifiers -> .identifiers (list of {scheme, value})
  properties.address.{street,city,postalCode,country} -> .address.{street,city,postalCode,country}
- InvoiceLine (one per invoice.items[] entry):
  properties.quantity + properties.unit -> .quantity.{value, unit}
  properties.unitPrice -> .pricing.unitPrice ; properties.netAmount -> .pricing.netAmount
  properties.allowanceCharge (list of {isCharge, amount}) -> sum amounts where isCharge is
    false into .pricing.allowanceTotal, and where isCharge is true into .pricing.chargeTotal
  properties.taxRate -> .taxation.rate ; properties.taxCategory -> .taxation.category
  properties.exemptionReason -> .taxation.exemptionReason (and set .taxation.exempt true if present)
  link hasProduct -> .product (a Product entity, contributing .product.name / .product.identifiers)
  the line's own entityId (its trailing segment, e.g. urn:line:INV-1:2 -> "2") -> .lineId
- TaxSummary: properties.taxAmount -> invoice.financialSummary.taxAmount ;
  properties.breakdown (list of {taxableAmount, taxAmount, rate, categoryId}) ->
  invoice.financialSummary.taxBreakdown[] as {category: categoryId, rate, taxableAmount, taxAmount}
- PaymentInformation: properties.means/.reference/.account -> invoice.payment.means/.reference/.account

## Transformation modes

The "transformationMode" field tells you what you're being asked to do with "uderEntities":
- "isolated": you are given ONE entity in uderEntities, with no other entities of the invoice
  available (linked entities it points to are NOT included). Populate only the CanonicalInvoice
  fields this single entity's properties directly supply; leave every other field null/omitted.
  Do not guess at fields that would require a linked entity you were not given.
- "aggregated": you are given ALL entities of the invoice in uderEntities at once. Resolve links
  between them and produce one complete CanonicalInvoice.
- "incremental": you are given ONE new entity in uderEntities, plus "priorAggregatedContext" --
  entities already processed in earlier calls for this same invoice. Treat priorAggregatedContext
  and uderEntities together as the full entity set seen so far, and return one complete, coherent
  CanonicalInvoice reflecting all of it. Preserve fields already established from
  priorAggregatedContext even when the new entity in uderEntities doesn't mention them again;
  only change a previously-set field if the new entity directly contradicts or supersedes it.

## Output

Respond with a single JSON object of exactly this shape:
{
  "transformedData": <a CanonicalInvoice object valid against the schema>,
  "confidence": <float 0-1, your overall self-assessed confidence that transformedData is fully correct>,
  "fieldConfidences": {"<path>": <float 0-1>, ...}
}
fieldConfidences keys are dot paths rooted at the invoice body (no leading "invoice."), matching
the target schema's own field names, e.g. "identity.number", "parties.supplier.name",
"financialSummary.netAmount", "items[<lineId>].pricing.netAmount",
"items[<lineId>].taxation.rate" -- using each line's own lineId, not its array index, inside the
brackets. Give a confidence entry for every field you populated.

## Data fidelity rules

- Only include information present in or directly derivable from the provided UDER entities
  (plus priorAggregatedContext in incremental mode). Never invent values, IDs, names, or amounts
  that aren't supported by the source data -- leave the field null or omit it if optional instead.
- Numeric fields (amounts, rates, quantities) must be JSON numbers, not strings, even though the
  source properties may hold them as strings.
- Copy date strings through unchanged (they are already ISO 8601 in the source).
- If an allowanceCharge, tax breakdown entry, or identifier list is empty or absent, use an empty
  list rather than fabricating an entry.
- These confidence values are estimates, not calibrated probabilities -- calibrate them to your
  actual uncertainty rather than defaulting to a high constant."""


class _GlobalRateLimiter:
    """Process-wide throttle enforcing a minimum gap between LLM calls.

    Shared at module scope (not per-instance) because the experiment runner
    constructs a fresh RealAITransformer per scenario/source/mode run -- an
    instance-level limiter would reset on every construction and stop
    protecting the real bottleneck, which is calls-per-wall-clock-second
    against the provider.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last_call: float | None = None

    async def wait(self, min_interval: float) -> None:
        if min_interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            if self._last_call is not None:
                elapsed = now - self._last_call
                remaining = min_interval - elapsed
                if remaining > 0:
                    await asyncio.sleep(remaining)
            self._last_call = time.monotonic()


_rate_limiter = _GlobalRateLimiter()


def is_available() -> bool:
    if not os.environ.get("AI_API_KEY"):
        return False
    try:
        import openai  # noqa: F401
    except ImportError:
        return False
    return True


class RealAITransformer(Transformer):
    name = "real_ai"

    def __init__(self, model: str | None = None, temperature: float = 0.0,
                 prompt_version: str = "v1", max_retries: int = 2,
                 min_interval_seconds: float | None = None,
                 request_timeout_seconds: float | None = None) -> None:
        if not is_available():
            raise RuntimeError("RealAITransformer requires AI_API_KEY and the `openai` package; "
                                "check is_available() before constructing.")
        import openai
        self.model = model or os.environ.get("AI_MODEL", "gpt-4o-mini")
        self.temperature = temperature
        self.prompt_version = prompt_version
        self.max_retries = max_retries
        self.min_interval_seconds = (
            min_interval_seconds if min_interval_seconds is not None
            else float(os.environ.get("AI_MIN_INTERVAL_SECONDS", "5"))
        )
        # Bounds how long a single LLM call may hang before we give up on it and
        # retry/skip -- without this, a stalled connection (dead proxy, network
        # partition, provider outage) blocks the whole matrix indefinitely since
        # nothing above this layer imposes its own deadline.
        self.request_timeout_seconds = (
            request_timeout_seconds if request_timeout_seconds is not None
            else float(os.environ.get("AI_REQUEST_TIMEOUT_SECONDS", "60"))
        )
        base_url = os.environ.get("AI_API_BASE_URL")
        self._client = openai.AsyncOpenAI(api_key=os.environ["AI_API_KEY"], base_url=base_url,
                                           timeout=self.request_timeout_seconds)
        self._schema = canonical_invoice_json_schema()
        logger.info(
            "RealAITransformer ready: model=%s temperature=%s prompt_version=%s "
            "max_retries=%d min_interval_seconds=%.1f request_timeout_seconds=%.1f base_url=%s",
            self.model, self.temperature, self.prompt_version, self.max_retries,
            self.min_interval_seconds, self.request_timeout_seconds, base_url or "<default>",
        )

    async def transform(self, uder_entities: list[UDEREntity], target_schema: dict,
                         context: TransformationContext) -> TransformResult:
        start = time.perf_counter()
        entities_payload = [e.to_dict() for e in uder_entities]
        user_prompt = json.dumps({
            "targetSchema": target_schema or self._schema,
            "instructions": context.instructions or "Transform the following UDER entities into a CanonicalInvoice.",
            "transformationMode": context.mode,
            "uderEntities": entities_payload,
            "priorAggregatedContext": context.history,
        })

        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        last_error: str | None = None
        last_result: TransformResult | None = None
        entity_ids = [e.entity_id for e in uder_entities]

        for attempt in range(self.max_retries + 1):
            attempt_no = attempt + 1
            total_attempts = self.max_retries + 1
            logger.info(
                "LLM call start: mode=%s entities=%s model=%s attempt=%d/%d",
                context.mode, entity_ids, self.model, attempt_no, total_attempts,
            )
            call_start = time.perf_counter()
            try:
                await _rate_limiter.wait(self.min_interval_seconds)
                # Hard wall-clock cap on top of the client/request-level timeout: guards
                # against connections that stall without ever raising (seen in practice
                # as an indefinite hang inside the TLS read), which would otherwise block
                # this call -- and the whole experiment matrix behind it -- forever.
                resp = await asyncio.wait_for(
                    self._client.chat.completions.create(
                        model=self.model, temperature=self.temperature,
                        response_format={"type": "json_object"},
                        messages=messages, timeout=self.request_timeout_seconds,
                    ),
                    timeout=self.request_timeout_seconds + 15,
                )
                call_elapsed = time.perf_counter() - call_start
                content = resp.choices[0].message.content
                logger.info(
                    "LLM call finished: mode=%s attempt=%d/%d elapsed=%.1fs response_chars=%d",
                    context.mode, attempt_no, total_attempts, call_elapsed, len(content or ""),
                )
                logger.debug("LLM raw response (mode=%s attempt=%d): %s", context.mode, attempt_no, content)

                parsed = json.loads(content)
                data = parsed.get("transformedData", {})
                data.setdefault("schemaVersion", CANONICAL_INVOICE_SCHEMA_VERSION)
                result = TransformResult(
                    transformed_data=data,
                    confidence=float(parsed.get("confidence", 0.0)),
                    field_confidences={k: float(v) for k, v in (parsed.get("fieldConfidences") or {}).items()},
                    metadata={
                        "mode": context.mode, "transformer": "real_ai", "model": self.model,
                        "temperature": self.temperature, "prompt_version": self.prompt_version,
                        "attempts": attempt_no, "confidence_strategy": "ai_self_assessment",
                        "confidence_estimate": True,
                    },
                    latency_ms=(time.perf_counter() - start) * 1000,
                )
                result.validate()
                logger.info(
                    "LLM result parsed: mode=%s attempt=%d/%d confidence=%.2f schema_valid=%s "
                    "field_count=%d",
                    context.mode, attempt_no, total_attempts, result.confidence,
                    result.schema_valid, len(result.field_confidences),
                )
                if result.schema_valid:
                    return result

                last_result = result
                last_error = "; ".join(result.validation_errors) or "schema validation failed"

                if not context.is_final:
                    # This call's output is an intermediate isolated/incremental partial --
                    # it is expected to be missing fields the model hasn't been given source
                    # data for yet, so it will always fail full-schema validation until the
                    # caller has merged/accumulated enough entities. Retrying can't fix that
                    # (the model still won't have the missing data), so don't burn attempts on
                    # it -- just return what we got.
                    logger.info(
                        "LLM result incomplete on non-final %s call (expected -- not all "
                        "entities available yet): attempt=%d/%d errors=%s",
                        context.mode, attempt_no, total_attempts, last_error,
                    )
                    return result

                logger.warning(
                    "LLM result failed schema validation: mode=%s attempt=%d/%d errors=%s",
                    context.mode, attempt_no, total_attempts, last_error,
                )
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": (
                    "Your transformedData failed CanonicalInvoice schema validation:\n"
                    f"{last_error}\n\n"
                    "Reply again with the full JSON object (transformedData, confidence, "
                    "fieldConfidences), correcting only the invalid parts."
                )})
            except asyncio.TimeoutError:
                call_elapsed = time.perf_counter() - call_start
                last_error = f"stalled/timed out after {call_elapsed:.1f}s (limit {self.request_timeout_seconds:.0f}s)"
                logger.warning(
                    "LLM call timed out and was abandoned: mode=%s entities=%s attempt=%d/%d elapsed=%.1fs",
                    context.mode, entity_ids, attempt_no, total_attempts, call_elapsed,
                )
                # Don't append anything to `messages` -- there is no assistant content to
                # react to, so the next attempt just re-sends the same request as-is.
            except Exception as exc:  # noqa: BLE001 -- retry loop, re-raised as final result below
                last_error = str(exc)
                logger.warning(
                    "LLM call failed: mode=%s attempt=%d/%d error=%s",
                    context.mode, attempt_no, total_attempts, last_error,
                )
                messages.append({"role": "user", "content": (
                    f"Your previous reply could not be parsed: {last_error}. Reply again with "
                    "ONLY a single valid JSON object in the shape described in the system prompt."
                )})

        if last_result is not None:
            logger.error(
                "LLM transform giving up after %d attempts (schema still invalid): mode=%s entities=%s error=%s",
                self.max_retries + 1, context.mode, entity_ids, last_error,
            )
            last_result.metadata["error"] = f"schema_invalid_after_retries: {last_error}"
            return last_result

        logger.error(
            "LLM transform giving up after %d attempts (no usable response): mode=%s entities=%s error=%s",
            self.max_retries + 1, context.mode, entity_ids, last_error,
        )
        return TransformResult(
            transformed_data={}, confidence=0.0,
            metadata={"mode": context.mode, "transformer": "real_ai", "error": last_error,
                      "attempts": self.max_retries + 1, "confidence_estimate": True},
            latency_ms=(time.perf_counter() - start) * 1000,
        )
