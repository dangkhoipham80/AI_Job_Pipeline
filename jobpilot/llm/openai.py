"""OpenAI, behind the ``StructuredClient`` contract.

``chat.completions.parse`` takes the Pydantic class directly and turns strict
mode on for us, which is the same guarantee the Anthropic path gives: the schema
constrains decoding rather than merely being described in the prompt.

Strict mode is fussier about the schema than Anthropic is — every object needs
``additionalProperties: false`` and every property in ``required`` — but the SDK
applies that conversion itself when it is handed a model class. ``strictify`` in
``schema.py`` exists for the case where a raw dict has to be sent instead, and
for the test that pins what strict mode actually demands.

Note the module name shadows the SDK's. Python 3 resolves ``import openai``
below to the installed package, not to this file.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel

from jobpilot.llm.base import Completion, LlmError, Usage
from jobpilot.llm.pricing import estimate_cost

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "gpt-4.1"
MAX_TOKENS = 16000


@dataclass
class OpenAIClient:
    model: str = DEFAULT_MODEL
    api_key: str = ""
    #: Lets this class also drive anything that speaks the same API — an
    #: OpenAI-compatible endpoint is a base_url, not a second client class.
    base_url: str = ""
    client: Any = None

    provider: str = "openai"

    def _sdk(self) -> Any:
        if self.client is None:
            try:
                import openai
            except ImportError as exc:  # pragma: no cover - env dependent
                raise LlmError(
                    "openai SDK not installed — run: pip install -e '.[openai]'"
                ) from exc
            kwargs: dict[str, Any] = {}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self.client = openai.OpenAI(**kwargs)
        return self.client

    def structured(self, *, system: str, messages: list[dict], schema: type[T]) -> Completion[T]:
        started = time.monotonic()
        try:
            response = self._sdk().chat.completions.parse(
                model=self.model,
                max_completion_tokens=MAX_TOKENS,
                messages=[{"role": "system", "content": system}, *messages],
                response_format=schema,
            )
        except Exception as exc:
            raise LlmError(f"OpenAI request failed: {exc}") from exc

        choices = getattr(response, "choices", None) or []
        if not choices:
            raise LlmError("OpenAI returned no choices")
        message = choices[0].message
        # A refusal is a populated field rather than a status code, and it is
        # the one failure worth naming: it means the request was understood and
        # declined, which is not something a retry fixes.
        refusal = getattr(message, "refusal", None)
        if refusal:
            raise LlmError(f"OpenAI declined this request: {refusal}")
        value = getattr(message, "parsed", None)
        if value is None:
            raise LlmError(f"OpenAI returned no parsable {schema.__name__}")
        return Completion(value=value, usage=self._usage(response, started))

    def _usage(self, response: Any, started: float) -> Usage:
        raw = getattr(response, "usage", None)
        inp = _int(raw, "prompt_tokens")
        out = _int(raw, "completion_tokens")
        cached = 0
        details = getattr(raw, "prompt_tokens_details", None)
        if details is not None:
            cached = _int(details, "cached_tokens")
        return Usage(
            input_tokens=inp,
            output_tokens=out,
            cached_input_tokens=cached,
            latency_ms=int((time.monotonic() - started) * 1000),
            provider=self.provider,
            model=self.model,
            cost_usd=estimate_cost(self.provider, self.model, inp, out),
        )


def _int(obj: Any, name: str) -> int:
    value = getattr(obj, name, None)
    return int(value) if isinstance(value, int) else 0
