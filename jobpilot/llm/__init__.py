"""Model backends.

The pipeline calls a language model in three places — tailoring a CV, writing a
cover letter, classifying an employer's reply — and each of them is a
``Protocol`` with a Claude implementation. This package adds a second backend
that runs on your own machine.

Which one is used is a config decision, per task, because the three are not
equally demanding: classifying an email into one of six labels is nothing like
writing 300 words a stranger will judge you on.
"""

from __future__ import annotations

from typing import Literal

Task = Literal["tailor", "letter", "classify"]


def blocker(task: Task) -> str:
    """Why ``task`` can't run on its configured backend, or '' if it can.

    Only local backends can be blocked in a way worth checking up front: a
    stopped ``ollama serve`` or an unpulled model is knowable *now*, and saying
    so beats a queued task that dies a minute later with the same message. The
    Claude path has nothing equivalent — a bad key is only discoverable by
    spending a request — so it always returns ''.

    Same shape and the same reason as ``ApplyCfg.inbox_blocker``.
    """
    from jobpilot.config import get_config
    from jobpilot.llm.ollama import OllamaClient, probe

    cfg = get_config().llm
    if cfg.for_task(task) != "ollama":
        return ""
    model = cfg.model_for("classify" if task == "classify" else "tailor")
    return probe(OllamaClient(model=model, host=cfg.host))
