"""Keeping credentials out of anything we store, print, or show.

A provider that rejects your key likes to tell you which key it rejected.
OpenAI answers a bad key with ``Incorrect API key provided: sk-proj-...``, and
that string travels: it becomes an ``LlmError``, then a ``TailorError``, then a
row in ``llm_calls.error``, then a line the CLI prints and a page the dashboard
could render. One unlucky error message and a secret is sitting in a database
column and a terminal scrollback.

So the scrub happens at the moment an error is *created*, not at each of the
places it might end up. There is one of the former and an unbounded number of
the latter, and the ones added later are exactly the ones nobody remembers to
protect.

Two layers, because they fail differently:

* **Exact values** — every credential this process holds, replaced wherever it
  appears. Total, but only covers keys we know about.
* **Shapes** — ``sk-…``, ``AIza…``, ``Bearer …``. Catches the key we don't hold:
  a partially-masked echo, a key from a different account, a provider added
  later whose secret never reached ``Secrets``.
"""

from __future__ import annotations

import re

PLACEHOLDER = "[redacted]"

#: Credential shapes worth catching even when the value is unknown to us.
#: Deliberately loose on the tail: a provider that masks the middle of a key
#: (``sk-proj-****abcd``) is still handing back key material, and a pattern that
#: only matched *well-formed* keys would sail straight past exactly that case.
_SHAPES = (
    # OpenAI (sk-, sk-proj-) and Anthropic (sk-ant-)
    re.compile(r"sk-[A-Za-z0-9_\-*]{6,}"),
    # Google AI Studio
    re.compile(r"AIza[A-Za-z0-9_\-*]{6,}"),
    # Google OAuth access token. Nothing issues one today — GOOGLE_API_KEY is an
    # AI Studio key — but a provider added later might, and the cost of carrying
    # the pattern now is one line.
    re.compile(r"ya29\.[A-Za-z0-9_\-*.]{10,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-*]{12,}"),
)

#: ``scheme://user:password@host`` — the password only, so the rest of the URL
#: still says which database refused the connection. Separate from the exact
#: values because an error can quote a DSN this process never held: a fallback
#: host, a URL typed into a config file, a connection string in a stack trace.
_URL_PASSWORD = re.compile(r"(://[^\s:/@]+:)([^\s@/]+)(@)")

#: A Secrets field is treated as a credential when its name says so. Checking
#: the name rather than listing fields means a secret added later is covered on
#: the day it is added, not on the day someone remembers this file.
_SENSITIVE_NAME = re.compile(r"(?i)key|token|password|secret")

#: Short values are skipped: scrubbing an 8-character placeholder like
#: ``changeme`` would corrupt unrelated prose without protecting anything.
_MIN_EXACT_LEN = 12


def secret_values() -> list[str]:
    """Every credential this process is holding, longest first.

    Longest first so that a value which contains another (a URL holding a
    password) is replaced whole, rather than left as a mangled remainder.
    """
    try:
        from jobpilot.config import get_secrets

        secrets = get_secrets()
    except Exception:  # pragma: no cover - config problems are not this module's job
        return []

    found = []
    for name, value in secrets.model_dump().items():
        if not isinstance(value, str) or len(value) < _MIN_EXACT_LEN:
            continue
        if _SENSITIVE_NAME.search(name) or "://" in value:
            found.append(value)
    return sorted(found, key=len, reverse=True)


def shadowed_secrets() -> list[str]:
    """Secrets where an OS environment variable overrides a *different* ``.env``.

    Cost a real debugging session: a stale ``OPENAI_API_KEY`` left in the Windows
    environment silently won over a freshly-pasted ``.env`` value of the same
    length, so the key that worked when tested by hand was never the key the app
    sent. pydantic-settings prefers the environment, which is correct and also
    invisible.

    The failure looks exactly like a bad key, which is the worst part: every
    obvious next step — re-copy the key, check for quotes, check the length —
    investigates the file that isn't being read.
    """
    import os

    from jobpilot.config import REPO_ROOT

    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return []
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:  # pragma: no cover
        return []

    shadowed = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not value or not _SENSITIVE_NAME.search(name):
            continue
        live = os.environ.get(name)
        if live is not None and live != value:
            shadowed.append(name)
    return shadowed


def redact(text: str) -> str:
    """``text`` with any credential replaced by ``[redacted]``."""
    if not text:
        return text
    for value in secret_values():
        text = text.replace(value, PLACEHOLDER)
    for shape in _SHAPES:
        text = shape.sub(PLACEHOLDER, text)
    return _URL_PASSWORD.sub(rf"\g<1>{PLACEHOLDER}\g<3>", text)
