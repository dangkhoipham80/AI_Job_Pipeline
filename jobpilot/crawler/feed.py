"""Shared base for sources that publish an official machine-readable feed.

Tier-2 sources (PLAN §5.1.1) differ from the tier-1 job boards in three ways
that are worth encoding once rather than per-site:

1. **No browser.** They serve RSS or JSON, so :class:`~jobpilot.crawler.fetch.
   HttpFetcher` is both faster and *more correct* than Playwright, which would
   wrap a JSON body in ``<pre>`` before the parser ever saw it.
2. **No detail page.** The feed already carries the full description, so
   ``needs_detail`` is False and a 25-job crawl costs one request instead of 26.
3. **No server-side search.** A feed serves whatever it serves; asking it for
   "java" changes nothing. So relevance has to be applied here, in
   :meth:`matches_query` — and *not* by scanning the job description, which on
   any real posting mentions half the industry as a nice-to-have. Matching the
   title and the source's own tags keeps the filter meaningful. Sources that do
   have a real server-side filter (Jobicy's ``tag=``) simply don't override it.
"""

from __future__ import annotations

import json
import re
from xml.etree import ElementTree

from jobpilot.crawler.base import BaseScraper, Fetcher
from jobpilot.crawler.types import SearchHit

# A "word" for query matching. The optional leading dot and the trailing +/#
# keep tech names whole, so ".net", "c++" and "c#" stay distinct tokens instead
# of collapsing into "net"/"c" and matching everything.
_TOKEN_RE = re.compile(r"\.?[a-z0-9][a-z0-9+#]*")


def tokens(text: str) -> set[str]:
    """Lowercased word tokens of ``text``."""
    return set(_TOKEN_RE.findall((text or "").lower()))


def load_json(text: str):
    """Parse a JSON body, with an error that says what actually arrived.

    A bare ``JSONDecodeError`` here is nearly always one of two things: the site
    answered with an HTML error page, or the scraper was handed a browser
    fetcher and got the JSON wrapped in markup. Both are much easier to
    recognise with the first bytes in the message.
    """
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ValueError(f"expected JSON, got {text[:80]!r}") from exc


def parse_json_feed(text: str) -> dict:
    """:func:`load_json`, for the feeds whose top level is an object.

    Lever's board API answers with a bare array, so the array case is a
    legitimate shape rather than an error — callers that expect one use
    :func:`load_json` directly.
    """
    data = load_json(text)
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    return data


def parse_rss_items(text: str) -> list[dict[str, str]]:
    """RSS/Atom ``<item>`` elements as plain ``{tag: text}`` dicts.

    Uses the stdlib XML parser rather than the HTML one: an RSS feed is XML, and
    an HTML parser silently "fixes" mismatched tags instead of telling you the
    feed is broken. Namespaces are stripped from tag names (``{ns}pubDate`` →
    ``pubDate``) so callers don't have to care which prefix a site chose.
    """
    root = ElementTree.fromstring(text.strip())
    items: list[dict[str, str]] = []
    for item in root.iter():
        if item.tag.split("}")[-1] not in ("item", "entry"):
            continue
        fields: dict[str, str] = {}
        for child in item:
            name = child.tag.split("}")[-1]
            value = (child.text or "").strip()
            if value and name not in fields:  # first occurrence wins
                fields[name] = value
        if fields:
            items.append(fields)
    return items


class FeedScraper(BaseScraper):
    """A source read from an official RSS/JSON feed rather than scraped HTML."""

    #: The feed carries the whole job — there is no detail page to fetch.
    needs_detail = False

    #: Sent as ``Accept``; feeds are content-negotiated by some hosts.
    accept = "application/json, application/rss+xml, application/xml;q=0.9, */*;q=0.8"

    def default_fetcher(self) -> Fetcher:
        from jobpilot.crawler.fetch import HttpFetcher

        return HttpFetcher(accept=self.accept)

    # -- relevance ---------------------------------------------------------- #
    def match_haystack(self, hit: SearchHit) -> str:
        """The text a query is matched against — title plus the source's tags.

        Deliberately *not* the job description. Overridden by sources that carry
        their own categories.
        """
        return hit.title

    def matches_query(self, hit: SearchHit, query: str) -> bool:
        """Keep a hit when any query word appears as a word in the haystack.

        Any-word rather than all-words: the configured query is a stack list
        ("Java Spring Boot"), and requiring every word would reject
        "Java Backend Engineer". An empty query keeps everything.
        """
        wanted = tokens(query)
        if not wanted:
            return True
        return bool(wanted & tokens(self.match_haystack(hit)))

    def query_score(self, hit: SearchHit, query: str) -> int:
        """How many distinct query words the hit answers."""
        return len(tokens(query) & tokens(self.match_haystack(hit)))

    def rank_hits(self, hits: list[SearchHit], query: str) -> list[SearchHit]:
        """Best match first, so ``limit`` is spent on the closest jobs.

        Any-word matching is deliberately generous, and on a big board that
        generosity is expensive: querying "backend engineer java" against a
        184-job Greenhouse board matched 44 postings, and the six that ``limit``
        actually kept were "AI Engineer" and four "Customer Success Engineer"
        roles — every one of them on the strength of the word *engineer* alone,
        while the real "Backend Engineer" sat further down the board.

        Filtering harder would have thrown away good jobs; ordering costs
        nothing and puts the ones matching the most of the query first. Python's
        sort is stable, so equally-good hits keep the source's own order.
        """
        if not tokens(query):
            return hits
        return sorted(hits, key=lambda h: -self.query_score(h, query))
