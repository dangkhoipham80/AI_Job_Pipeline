"""Model backends.

The pipeline calls a language model in three places — tailoring a CV, writing a
cover letter, classifying an employer's reply — and each of them is a
``Protocol`` with one implementation that takes a
:class:`~jobpilot.llm.base.StructuredClient`. Which company answers is a config
decision, per task, because the three are not equally demanding: classifying an
email into one of six labels is nothing like writing 300 words a stranger will
judge you on.

The split between *how you call a model* and *what makes the answer acceptable*
is the load-bearing one. Providers live here; guardrails live with the task they
guard, and every backend goes through the same ones.
"""

from __future__ import annotations

from typing import Literal

Task = Literal["tailor", "letter", "classify"]

#: The two tasks whose prompt contains the Master CV — see
#: ``tailor/prompt.py:system_prompt`` and ``apply/letter.py:ModelLetterEngine``.
SENDS_MASTER_CV: tuple[str, ...] = ("tailor", "letter")


def blocker(task: Task) -> str:
    """Why ``task`` can't run on its configured backend, or '' if it can.

    A missing API key is knowable *now*, and saying so beats a queued task that
    dies a minute later with the same message — the same courtesy
    ``ApplyCfg.inbox_blocker`` extends, and the same shape.

    It is deliberately only that check. Whether the key is *valid*, or whether
    the account has credit, can only be discovered by spending a request; a
    pre-flight that pretended otherwise would just be a slower way to be wrong.
    """
    from jobpilot.config import get_config
    from jobpilot.llm.base import LlmError
    from jobpilot.llm.registry import api_key, provider_for

    name = get_config().llm.for_task(task)
    try:
        provider = provider_for(name)
    except LlmError as exc:
        return str(exc)
    if not api_key(name):
        return (
            f"{provider.label} is configured for {task}, but {provider.env_var} is not set in .env"
        )
    return ""


def warnings(task: Task) -> list[str]:
    """Notes about what the configured provider may do with this task's input.

    Separate from :func:`blocker` on purpose: a blocker stops the work, a
    warning does not. Tailoring puts the entire Master CV in the prompt, so the
    user is entitled to know a provider's terms before it goes — and entitled to
    send it anyway. This returns the sentences; it never decides.
    """
    from jobpilot.config import get_config
    from jobpilot.llm.pricing import CHECKED_ON, policy_for

    cfg = get_config().llm
    name = cfg.for_task(task)
    payload = (
        "your entire Master CV - name, phone number, employment history"
        if task in SENDS_MASTER_CV
        else "the text of employer emails that matched one of your applications"
    )

    note = policy_for(name, paid_tier=cfg.paid_tier(name))
    if note is None:
        return [
            f"No data-use note on record for provider {name!r}. This task sends {payload} - "
            "read its terms before enabling it."
        ]
    if not note.trains_on_input:
        return []
    return [f"{name}: {note.summary} This task sends {payload}. {note.url} (checked {CHECKED_ON})."]
