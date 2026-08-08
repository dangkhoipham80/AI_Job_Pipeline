"""What every model backend has to provide, and nothing more.

The pipeline asks a model for a Pydantic object three times — a tailor plan, a
cover letter, a verdict on one employer email — and in all three cases the rules
about *what makes the answer acceptable* live in the guardrails, not in the
backend. So the backend contract is one method: given a system prompt, a list of
turns, and a schema, come back with an instance of that schema.

Everything a provider differs in — SDK shape, how the schema is expressed, what
the usage object is called — stops at this boundary. Engines above it never
learn which company answered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LlmError(RuntimeError):
    """A model backend could not produce a usable answer.

    One error type across providers on purpose: the engines above catch this and
    re-raise as ``TailorError``, and a caller deciding what to do about a failed
    tailor does not care whether the 429 came from Anthropic or Google.

    The message is scrubbed of credentials here, at the single point where every
    provider failure becomes a string. Downstream it gets stored in
    ``llm_calls.error``, printed by the CLI, and returned by the API — and a
    rejected key is precisely the case where a provider quotes the key back at
    you. Guarding the constructor covers the destinations nobody has added yet.
    """

    def __init__(self, *args: object) -> None:
        from jobpilot.llm.redact import redact

        super().__init__(*(redact(a) if isinstance(a, str) else a for a in args))


@dataclass
class Usage:
    """What one call cost, in tokens and in wall clock.

    ``cost_usd`` is ``None`` — not ``0.0`` — when the model is missing from
    ``pricing.py``. A price table goes stale by sitting still, and the honest
    answer to "what did that cost" for an unknown model is that we don't know.
    Showing $0.00 would be a wrong answer wearing the clothes of a right one.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    latency_ms: int = 0
    provider: str = ""
    model: str = ""
    cost_usd: float | None = None


@dataclass
class Completion(Generic[T]):
    value: T
    usage: Usage = field(default_factory=Usage)


class StructuredClient(Protocol):
    """One turn of conversation that must come back as ``schema``.

    Implementations are expected to *constrain* the decoding rather than ask
    nicely and hope: all three providers behind this protocol compile the schema
    into a grammar, which is what makes an index-based plan safe to check
    afterwards. A backend that could only promise "probably JSON" would need its
    own retry here, not a looser guardrail upstream.
    """

    provider: str
    model: str

    def structured(self, *, system: str, messages: list[dict], schema: type[T]) -> Completion[T]:
        ...
