"""Portal and external channels — prepare, then hand off to the human.

Neither channel ever submits on its own (CLAUDE.md rule 2). What they produce is
a **handoff package**: the apply URL, the tailored CV on disk, and the exact
field values to paste. That works with no browser automation at all, which
matters because it is the fallback whenever Playwright isn't installed or the
site's form defeats the heuristics.

Optional browser pre-fill lives in ``prefill_with_browser``. It opens a visible
window, fills what it recognises, and blocks until the user closes it — so it is
wired to the CLI only, never to an API request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from jobpilot.cv.schema import CvDocument

# Label phrases -> the handoff key that fills them, most specific first so
# "full name" wins over "name" and "first name" never falls through to it.
# Matched as whole words, never as substrings: "phone" contains "ho", and
# "họ" (Vietnamese for surname) would otherwise claim every phone field.
_FIELD_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("full name", "fullname", "your name", "ho va ten", "họ và tên", "họ tên"), "full_name"),
    (("first name", "firstname", "given name", "tên"), "first_name"),
    (("last name", "lastname", "surname", "family name", "họ"), "last_name"),
    (("email", "e mail", "your email"), "email"),
    (("phone", "phone number", "mobile", "tel", "sdt", "điện thoại", "số điện thoại"), "phone"),
    (("linkedin", "linkedin url"), "linkedin"),
    (("github", "github url"), "github"),
    (("portfolio", "website", "personal site"), "portfolio"),
    (("name",), "full_name"),
]

# Split on anything that isn't a letter or digit, so "first_name", "your-email"
# and "Số điện thoại" all tokenise the same way.
_WORDS_RE = re.compile(r"[^\w]+|_", re.UNICODE)


@dataclass
class Handoff:
    """Everything the user needs to finish an application by hand."""

    url: str
    cv_path: Path | None
    fields: dict[str, str] = field(default_factory=dict)
    cover_letter: str = ""
    prefilled: bool = False
    note: str = ""

    def summary(self) -> dict:
        return {
            "url": self.url,
            "cv_path": str(self.cv_path) if self.cv_path else None,
            "fields": self.fields,
            "prefilled": self.prefilled,
            "note": self.note,
        }


def _person_case(name: str) -> str:
    """The CV header stores names in caps for the LaTeX header styling; a web
    form wants them the way a person writes them."""
    name = name.strip()
    return name.title() if name.isupper() else name


def contact_fields(master: CvDocument) -> dict[str, str]:
    """Contact details pulled from the CV header — the answers most forms want."""
    h = master.header
    first, last = _person_case(h.first_name), _person_case(h.last_name)
    out = {
        "first_name": first,
        "last_name": last,
        "full_name": " ".join(p for p in (first, last) if p),
        "email": h.email or "",
        "phone": h.mobile or "",
        "github": f"https://github.com/{h.github}" if h.github else "",
        "linkedin": f"https://linkedin.com/in/{h.linkedin}" if h.linkedin else "",
        "portfolio": h.extra_info.url if h.extra_info else "",
    }
    return {k: v for k, v in out.items() if v}


def prepare_handoff(
    *, url: str, master: CvDocument, cv_path: Path | None, cover_letter: str = ""
) -> Handoff:
    """Build the package. Always succeeds — this is the no-automation baseline."""
    return Handoff(
        url=url,
        cv_path=cv_path,
        fields=contact_fields(master),
        cover_letter=cover_letter,
        note="Nothing was submitted. Open the link, paste the fields, attach the CV.",
    )


def _words(text: str) -> list[str]:
    return [w for w in _WORDS_RE.split(text.strip().lower()) if w]


def _contains_phrase(words: list[str], phrase: str) -> bool:
    """Whole-word subsequence match: ['your','email'] contains 'email'."""
    target = _words(phrase)
    if not target:
        return False
    return any(words[i : i + len(target)] == target for i in range(len(words) - len(target) + 1))


def match_field(label: str) -> str | None:
    """Which handoff key a form label is asking for, if any."""
    words = _words(label)
    for phrases, key in _FIELD_HINTS:
        if any(_contains_phrase(words, phrase) for phrase in phrases):
            return key
    return None


def prefill_with_browser(handoff: Handoff, timeout_ms: int = 30_000) -> Handoff:  # pragma: no cover
    """Open the posting in a visible browser and fill what we recognise.

    Blocks until the user closes the window; they submit, not us. Degrades to the
    plain handoff if Playwright isn't installed or the page won't load.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        handoff.note = (
            "Playwright is not installed, so the form was not pre-filled — "
            "run: pip install -e '.[crawler]' && playwright install chromium"
        )
        return handoff

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            page.goto(handoff.url, timeout=timeout_ms)

            filled: list[str] = []
            for element in page.query_selector_all("input, textarea"):
                label = " ".join(
                    filter(
                        None,
                        (
                            element.get_attribute("name"),
                            element.get_attribute("placeholder"),
                            element.get_attribute("aria-label"),
                            element.get_attribute("id"),
                        ),
                    )
                )
                key = match_field(label)
                if key and handoff.fields.get(key):
                    try:
                        element.fill(handoff.fields[key])
                        filled.append(key)
                    except Exception:
                        continue

            if handoff.cv_path and handoff.cv_path.is_file():
                for uploader in page.query_selector_all("input[type=file]"):
                    try:
                        uploader.set_input_files(str(handoff.cv_path))
                        filled.append("cv")
                        break
                    except Exception:
                        continue

            handoff.prefilled = bool(filled)
            handoff.note = (
                f"Pre-filled {', '.join(sorted(set(filled)))}. Check every field, then submit "
                "yourself — JobPilot never presses Submit."
                if filled
                else "Could not recognise any fields on this form; fill it by hand."
            )
            input("Browser is open. Submit the form, then press Enter here to continue... ")
            browser.close()
    except Exception as exc:
        handoff.note = f"Browser pre-fill failed ({exc}); apply by hand using the fields above."
    return handoff
