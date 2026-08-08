"""Gemini, behind the ``StructuredClient`` contract.

The package is ``google-genai`` (``from google import genai``).
``google-generativeai`` is a different, **deprecated** package — support ended
2025-08-31 — and importing the wrong one produces code that looks right and
calls an API that is going away.

Two things differ from the other two backends and both are handled here rather
than leaking upward:

* **Roles.** Gemini calls the assistant turn ``model``, and takes the system
  prompt out of band as ``system_instruction`` rather than as a first turn.
* **Schema dialect.** Gemini documents a *subset* of JSON Schema and warns that
  large or deeply nested schemas may be rejected; multi-definition ``$defs`` of
  the kind Pydantic emits is not among the documented features. So the schema
  goes through ``flatten_schema`` first — the same treatment, for the same
  reason, that made a local grammar compiler workable.

If a schema is rejected anyway, that surfaces as a plain ``LlmError`` naming the
schema. Better a loud "Gemini would not take TailorPlan" than a backend that
silently only works for the easy call.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from jobpilot.llm.base import Completion, LlmError, Usage
from jobpilot.llm.pricing import estimate_cost
from jobpilot.llm.schema import flatten_schema

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "gemini-3.5-flash"


@dataclass
class GeminiClient:
    model: str = DEFAULT_MODEL
    api_key: str = ""
    client: Any = None

    provider: str = "gemini"

    def _sdk(self) -> Any:
        if self.client is None:
            try:
                from google import genai
            except ImportError as exc:  # pragma: no cover - env dependent
                raise LlmError(
                    "google-genai SDK not installed — run: pip install -e '.[gemini]' "
                    "(note: NOT the deprecated google-generativeai package)"
                ) from exc
            self.client = genai.Client(api_key=self.api_key) if self.api_key else genai.Client()
        return self.client

    def structured(self, *, system: str, messages: list[dict], schema: type[T]) -> Completion[T]:
        started = time.monotonic()
        try:
            response = self._sdk().models.generate_content(
                model=self.model,
                contents=[_turn(m) for m in messages],
                config={
                    "system_instruction": system,
                    "response_mime_type": "application/json",
                    "response_json_schema": flatten_schema(schema.model_json_schema()),
                    "temperature": 0,
                },
            )
        except Exception as exc:
            raise LlmError(f"Gemini request failed ({schema.__name__}): {exc}") from exc

        text = (getattr(response, "text", None) or "").strip()
        if not text:
            raise LlmError("Gemini returned an empty response")
        try:
            value = schema.model_validate_json(text)
        except ValidationError as exc:
            raise LlmError(f"Gemini's reply did not fit {schema.__name__}: {exc}") from exc
        return Completion(value=value, usage=self._usage(response, started))

    def _usage(self, response: Any, started: float) -> Usage:
        raw = getattr(response, "usage_metadata", None)
        cached = _int(raw, "cached_content_token_count")
        inp = _int(raw, "prompt_token_count")
        # Thinking tokens are billed at the output rate, so they belong in the
        # output count rather than in a column nobody adds up.
        out = _int(raw, "candidates_token_count") + _int(raw, "thoughts_token_count")
        return Usage(
            input_tokens=inp,
            output_tokens=out,
            cached_input_tokens=cached,
            latency_ms=int((time.monotonic() - started) * 1000),
            provider=self.provider,
            model=self.model,
            cost_usd=estimate_cost(self.provider, self.model, inp, out),
        )


def _turn(message: dict) -> dict:
    """One chat turn in Gemini's shape. ``assistant`` is spelled ``model`` here."""
    role = "model" if message.get("role") == "assistant" else "user"
    return {"role": role, "parts": [{"text": message.get("content") or ""}]}


def _int(obj: Any, name: str) -> int:
    """A usage field, or 0 — Gemini leaves these as ``None`` more often than not."""
    value = getattr(obj, name, None)
    return int(value) if isinstance(value, int) else 0
