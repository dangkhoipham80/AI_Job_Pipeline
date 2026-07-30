"""Text helpers shared by scrapers & normalization (no network, pure functions)."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

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


def el_text(el: Tag | None) -> str:
    """Whitespace-collapsed text of an element, or ``""`` when it is missing.

    Every scraper needs this as the first step of reading any field, so it lives
    here rather than as a fifth private copy.
    """
    return clean_text(el.get_text(" ", strip=True)) if el else ""


def first_match(root: Tag, *selectors: str) -> Tag | None:
    """First match trying each selector *in the given order*.

    Deliberately not ``root.select_one("a, b")``: a comma-separated selector
    returns the earliest match in **document order**, throwing away the
    preference the order was meant to express. On a VietnamWorks card the logo
    anchor precedes the heading anchor, so the one-liner picked the logo — which
    has no text, only a ``title`` attribute — and the job title silently came
    from the wrong element.
    """
    for sel in selectors:
        found = root.select_one(sel)
        if found is not None:
            return found
    return None


def strip_query(url: str) -> str:
    """Drop the query string and fragment from a URL.

    Job-board listing links carry per-session tracking (TopCV's ``u_sr_id``,
    VietnamWorks' ``?source=searchResults&placement=…``). Keeping it would churn
    the stored URL on every crawl and leak a session identifier into the database
    and the apply hand-off.
    """
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def leaf_texts(root: Tag, max_len: int = 60) -> list[str]:
    """Short text nodes with no element children — the labels on a card.

    Returns a list, not a generator: callers scan it more than once, and a
    half-consumed generator silently yields nothing the second time.
    """
    out: list[str] = []
    for el in root.find_all(True):
        if el.find(True):
            continue
        text = clean_text(el.get_text(" ", strip=True))
        if text and len(text) <= max_len:
            out.append(text)
    return out


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
