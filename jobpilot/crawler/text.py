"""Text helpers shared by scrapers & normalization (no network, pure functions)."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

_WS = re.compile(r"\s+")

# Level/seniority words stripped when building a dedup title (so "Java Backend"
# and "Junior Java Backend" collapse to the same cross-source key).
_LEVEL_WORDS = frozenset(
    {
        "junior",
        "senior",
        "fresher",
        "intern",
        "internship",
        "middle",
        "mid",
        "lead",
        "principal",
        "staff",
        "sr",
        "jr",
    }
)


def clean_text(s: str | None) -> str:
    """Collapse whitespace (incl. non-breaking spaces) and trim."""
    return _WS.sub(" ", (s or "").replace("\xa0", " ")).strip()


def html_to_markdown(html: str | None) -> str:
    """Lightweight HTML → Markdown for JD bodies.

    Not a full converter — enough to keep headings, paragraphs and bullet lists
    readable for the tailor step. Falls back to flat text when no block tags are
    present.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    out: list[str] = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li"]):
        text = clean_text(el.get_text(" ", strip=True))
        if not text:
            continue
        name = el.name
        if name[0] == "h" and name[1:].isdigit():
            out.append("#" * int(name[1:]) + " " + text)
        elif name == "li":
            out.append("- " + text)
        else:
            out.append(text)

    md = "\n\n".join(out)
    if not md:  # no recognizable block tags — return flat text
        md = clean_text(soup.get_text(" ", strip=True))
    return md


def normalize_title(title: str | None) -> str:
    """Canonicalize a job title for cross-source dedup.

    Drops parentheticals, seniority words and punctuation; keeps tech tokens
    (``+``/``#``/``.`` survive so "c++"/"c#"/".net" stay distinct).
    """
    t = (title or "").lower()
    t = re.sub(r"\(.*?\)", " ", t)  # drop "(Java, Spring Boot)" etc.
    t = re.sub(r"[^a-z0-9+#. ]", " ", t)
    tokens = [w for w in t.split() if w not in _LEVEL_WORDS]
    return " ".join(tokens).strip()


def dedup_key(company: str | None, title: str | None) -> str:
    """Cross-source dedup key: normalized ``company|title`` (PLAN §3.2)."""
    return f"{clean_text(company).lower()}|{normalize_title(title)}"
