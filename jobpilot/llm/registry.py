"""Which backend runs which task.

One dict, not a chain of ``if provider == ...``. Adding a provider is adding an
entry here plus a client module — the four call sites and the config type stay
untouched. That is the whole point: the previous shape hard-coded two names into
a ``Literal`` and four factory functions, so a third backend meant editing six
places and remembering all of them.

Keyed by the string that appears in ``config.yaml`` under ``llm``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from jobpilot.llm.base import LlmError, StructuredClient
from jobpilot.llm.claude import DEFAULT_MODEL as CLAUDE_MODEL
from jobpilot.llm.claude import ClaudeClient
from jobpilot.llm.gemini import DEFAULT_MODEL as GEMINI_MODEL
from jobpilot.llm.gemini import GeminiClient
from jobpilot.llm.openai import DEFAULT_MODEL as OPENAI_MODEL
from jobpilot.llm.openai import OpenAIClient


@dataclass(frozen=True)
class Provider:
    """Everything the rest of the app needs to know about one backend."""

    key: str
    label: str
    default_model: str
    #: Attribute on ``Secrets`` holding this provider's key, and the .env name
    #: to tell the user about when it's missing.
    secret_attr: str
    env_var: str
    #: Extra to install, for the error message when the SDK is absent.
    extra: str
    #: (model, api_key, task) -> client. The task is passed because one
    #: provider's request shape depends on it: Claude's extended thinking is
    #: worth paying for on tailor and letter and pointless on classify.
    build: Callable[[str, str, str], StructuredClient]


PROVIDERS: dict[str, Provider] = {
    "claude": Provider(
        key="claude",
        label="Anthropic Claude",
        default_model=CLAUDE_MODEL,
        secret_attr="anthropic_api_key",
        env_var="ANTHROPIC_API_KEY",
        extra="tailor",
        build=lambda model, key, task: ClaudeClient(
            model=model, api_key=key, thinking=task != "classify"
        ),
    ),
    "openai": Provider(
        key="openai",
        label="OpenAI",
        default_model=OPENAI_MODEL,
        secret_attr="openai_api_key",
        env_var="OPENAI_API_KEY",
        extra="openai",
        build=lambda model, key, _task: OpenAIClient(model=model, api_key=key),
    ),
    "gemini": Provider(
        key="gemini",
        label="Google Gemini",
        default_model=GEMINI_MODEL,
        secret_attr="google_api_key",
        env_var="GOOGLE_API_KEY",
        extra="gemini",
        build=lambda model, key, _task: GeminiClient(model=model, api_key=key),
    ),
}


def provider_for(name: str) -> Provider:
    if name not in PROVIDERS:
        known = ", ".join(sorted(PROVIDERS))
        raise LlmError(f"unknown llm provider {name!r} — known providers: {known}")
    return PROVIDERS[name]


def api_key(name: str) -> str:
    from jobpilot.config import get_secrets

    return getattr(get_secrets(), provider_for(name).secret_attr, "") or ""


def client_for(task: str) -> StructuredClient:
    """The client ``llm.<task>`` (or ``llm.provider``) asks for."""
    from jobpilot.config import get_config

    cfg = get_config().llm
    name = cfg.for_task(task)
    return provider_for(name).build(cfg.model_for(task), api_key(name), task)


def list_models(name: str) -> list[str]:
    """Model ids the provider says this key can use, newest-looking last.

    Live rather than hardcoded, because a static list rots in the direction that
    hurts: it keeps offering models that have been withdrawn. It is not a
    guarantee either — Gemini happily *lists* ``gemini-2.5-flash`` and then
    answers ``generateContent`` with 404 "no longer available to new users". So
    the picker treats this as a menu, not a promise, and ``llm bench`` remains
    the thing that proves a model works.

    Returns [] rather than raising: a provider you have no key for should leave
    the other two pickers working.
    """
    key = api_key(name)
    if not key:
        return []
    try:
        if name == "claude":
            import anthropic

            return sorted(m.id for m in anthropic.Anthropic(api_key=key).models.list(limit=100))
        if name == "openai":
            import openai

            return sorted(m.id for m in openai.OpenAI(api_key=key).models.list())
        if name == "gemini":
            from google import genai

            # The client is bound to a name on purpose. Inlining it into the
            # comprehension lets it be garbage-collected while the lazy pager is
            # still iterating, and the SDK then fails with "Cannot send a
            # request, as the client has been closed" — which reads like an
            # auth problem and is not one.
            client = genai.Client(api_key=key)
            return sorted(
                m.name.removeprefix("models/")
                for m in client.models.list()
                if "generateContent" in (m.supported_actions or [])
            )
    except Exception as exc:  # network, auth, SDK absent — all "no menu right now"
        # Logged, not silent. An empty picker and a broken picker look identical
        # from the outside, and this repo has already paid once for a swallowed
        # failure nobody could see (see ``llm/usage.record``).
        #
        # Redacted, because a rejected key is the most likely thing in here and
        # a log file is as durable as a database column.
        from jobpilot.llm.redact import redact

        logging.getLogger(__name__).warning(
            "could not list %s models: %s", name, redact(str(exc))
        )
        return []
    return []
