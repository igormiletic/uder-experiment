"""Mode A: real AI transformer, generic OpenAI-compatible client, fully env-gated.

Reads AI_API_KEY / AI_API_BASE_URL / AI_MODEL from the environment. If
AI_API_KEY is unset (or the `openai` package is unavailable), `is_available()`
returns False and callers should fall back to the mock/deterministic
transformer -- nothing in this module is imported or required for tests/CI.
"""
from __future__ import annotations

import json
import os
import time

from uder_experiment.schema.canonical_invoice import CANONICAL_INVOICE_SCHEMA_VERSION
from uder_experiment.schema.json_schema import canonical_invoice_json_schema
from uder_experiment.transform.base import Transformer, TransformResult
from uder_experiment.transform.context import TransformationContext
from uder_experiment.uder.entities import UDEREntity

SYSTEM_PROMPT = """You are an invoice data transformation engine for a Linked Data Client (LDC).
You receive a set of UDER (Uniform Data Entity Representation) entities describing fragments
of one logical invoice, originally sourced from a heterogeneous e-invoicing standard (UBL,
UN/CEFACT CII, or an OAGIS-derived JSON representation). Transform them into the LDC's local
CanonicalInvoice model, given below as a JSON Schema.

Respond with a single JSON object of exactly this shape:
{
  "transformedData": <a CanonicalInvoice object valid against the schema>,
  "confidence": <float 0-1, your overall self-assessed confidence that transformedData is fully correct>,
  "fieldConfidences": {"<dot.path.into.transformedData>": <float 0-1>, ...}
}
Only include information present in or directly derivable from the provided UDER entities.
Do not fabricate values for fields you cannot support from the source data -- leave them null
or omit optional fields instead. These confidence values are estimates, not calibrated
probabilities."""


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
                 prompt_version: str = "v1", max_retries: int = 2) -> None:
        if not is_available():
            raise RuntimeError("RealAITransformer requires AI_API_KEY and the `openai` package; "
                                "check is_available() before constructing.")
        import openai
        self.model = model or os.environ.get("AI_MODEL", "gpt-4o-mini")
        self.temperature = temperature
        self.prompt_version = prompt_version
        self.max_retries = max_retries
        base_url = os.environ.get("AI_API_BASE_URL")
        self._client = openai.AsyncOpenAI(api_key=os.environ["AI_API_KEY"], base_url=base_url)
        self._schema = canonical_invoice_json_schema()

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

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = await self._client.chat.completions.create(
                    model=self.model, temperature=self.temperature,
                    response_format={"type": "json_object"},
                    messages=[{"role": "system", "content": SYSTEM_PROMPT},
                              {"role": "user", "content": user_prompt}],
                )
                content = resp.choices[0].message.content
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
                        "attempts": attempt + 1, "confidence_strategy": "ai_self_assessment",
                        "confidence_estimate": True,
                    },
                    latency_ms=(time.perf_counter() - start) * 1000,
                )
                result.validate()
                return result
            except Exception as exc:  # noqa: BLE001 -- retry loop, re-raised as final result below
                last_error = exc

        return TransformResult(
            transformed_data={}, confidence=0.0,
            metadata={"mode": context.mode, "transformer": "real_ai", "error": str(last_error),
                      "attempts": self.max_retries + 1, "confidence_estimate": True},
            latency_ms=(time.perf_counter() - start) * 1000,
        )
