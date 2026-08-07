"""Structured output from a model running on your own machine.

Ollama speaks plain HTTP and takes a JSON Schema in ``format``, which it turns
into a decoding grammar — the model is physically unable to emit a token that
breaks the schema. That matters more here than model size: every prompt in this
repo already asks for a Pydantic object, and the guardrails then check the
*content* of that object. Constrained decoding removes the failure mode a small
model would otherwise be worst at, and leaves the one the guardrails were built
for.

No SDK and no new dependency — ``httpx`` is already in the crawler extra.

**The privacy argument is the real one.** Running locally means the Master CV —
full name, phone number, employment history — never leaves the machine. That is
strictly better than any hosted API for principle 3, and it is the reason this
backend exists at all; being free is a side effect.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

DEFAULT_HOST = "http://127.0.0.1:11434"

#: Local models are slow and this runs on the task queue, where slow is fine.
#: A tailor round on a 14B spilling into system RAM can genuinely take minutes;
#: a short timeout here would look like a broken backend rather than a patient one.
DEFAULT_TIMEOUT = 900.0

T = TypeVar("T", bound=BaseModel)


class OllamaError(RuntimeError):
    """Could not reach or parse a reply from the local model server."""


def flatten_schema(schema: dict) -> dict:
    """Inline ``$ref``/``$defs`` so the grammar compiler sees one plain tree.

    Pydantic hoists every nested model into ``$defs`` and refers to it by
    ``$ref``. Ollama's schema-to-grammar step handles the common cases, but
    support for references is the shakiest corner of it, and a schema it can't
    compile fails at request time with a message about the grammar rather than
    about the model. Inlining costs nothing here — these schemas are small,
    two levels deep, and non-recursive by construction.
    """
    defs = schema.get("$defs") or {}

    def resolve(node: Any, seen: frozenset[str]) -> Any:
        if isinstance(node, list):
            return [resolve(n, seen) for n in node]
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            name = ref.split("/")[-1]
            if name in seen:
                # Recursive schema — leave the ref alone rather than expand it
                # forever. None of ours are, so this is a guard, not a path.
                return node
            target = defs.get(name)
            if target is None:
                return node
            return resolve(target, seen | {name})
        return {k: resolve(v, seen) for k, v in node.items() if k != "$defs"}

    return resolve({k: v for k, v in schema.items() if k != "$defs"}, frozenset())


@dataclass
class OllamaClient:
    """One local model, asked for one validated object at a time.

    ``transport`` exists so tests can drive the whole engine without a model
    server — the same trick ``slack/client.py`` uses with an injected
    ``httpx.Client``.
    """

    model: str
    host: str = DEFAULT_HOST
    timeout: float = DEFAULT_TIMEOUT
    transport: Any | None = None
    #: Every request made, for tests and for the "what did it actually send" question.
    calls: list[dict] = field(default_factory=list)

    def _client(self):
        if self.transport is not None:
            return self.transport
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - env dependent
            raise OllamaError("httpx not installed — run: pip install -e '.[crawler]'") from exc
        return httpx.Client(timeout=self.timeout)

    def structured(
        self,
        *,
        system: str,
        messages: list[dict],
        schema: type[T],
    ) -> T:
        """Ask for one instance of ``schema``. Raises :class:`OllamaError`.

        ``temperature`` is pinned to 0: this is extraction and ranking, not
        prose, and a model that samples creatively inside a grammar mostly
        produces creative index choices.
        """
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "format": flatten_schema(schema.model_json_schema()),
            "stream": False,
            "options": {"temperature": 0},
        }
        self.calls.append(payload)

        client = self._client()
        try:
            response = client.post(f"{self.host.rstrip('/')}/api/chat", json=payload)
        except Exception as exc:
            raise OllamaError(
                f"cannot reach the local model at {self.host} — is `ollama serve` running? ({exc})"
            ) from exc

        if response.status_code == 404:
            raise OllamaError(
                f"model {self.model!r} is not present locally — run: ollama pull {self.model}"
            )
        if response.status_code >= 400:
            raise OllamaError(f"ollama returned {response.status_code}: {response.text[:400]}")

        try:
            body = response.json()
        except Exception as exc:
            raise OllamaError(f"ollama returned a non-JSON body: {response.text[:200]}") from exc

        content = ((body.get("message") or {}).get("content") or "").strip()
        if not content:
            raise OllamaError("the local model returned an empty message")

        try:
            return schema.model_validate_json(content)
        except ValidationError as exc:
            # The grammar guarantees shape, not that every required field was
            # populated sensibly. Report what came back so a bad local model is
            # visibly a bad local model, not a mysterious failure.
            raise OllamaError(
                f"the local model's reply did not fit {schema.__name__}: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:  # pragma: no cover - grammar should prevent
            raise OllamaError(f"the local model returned invalid JSON: {content[:200]}") from exc


def probe(client: OllamaClient) -> str:
    """Why the local backend can't run, or '' if it can.

    Called by :func:`jobpilot.llm.blocker`, which the inbox route checks before
    queueing — so a stopped server is a 409 now rather than a task that dies a
    minute later, the same courtesy ``apply.email`` extends with its gates.
    """
    try:
        http = client._client()
        response = http.get(f"{client.host.rstrip('/')}/api/tags")
    except OllamaError as exc:
        return str(exc)
    except Exception as exc:
        return f"cannot reach ollama at {client.host} — is `ollama serve` running? ({exc})"

    if response.status_code >= 400:
        return f"ollama returned {response.status_code} for /api/tags"
    names = {m.get("name", "") for m in (response.json().get("models") or [])}
    # `ollama pull qwen2.5:7b` lands as "qwen2.5:7b"; asking for "qwen2.5" should
    # still count as present.
    # No `names and ...` guard: a server with nothing pulled would otherwise
    # read as "all good" and fail on the first real request.
    if not any(n == client.model or n.startswith(f"{client.model}:") for n in names):
        return f"model {client.model!r} is not pulled — run: ollama pull {client.model}"
    return ""
