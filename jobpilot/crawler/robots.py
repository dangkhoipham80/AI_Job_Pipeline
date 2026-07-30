"""robots.txt policy check (PLAN §5.1: respect robots.txt).

Fetches and caches ``/robots.txt`` per host, then answers ``allowed(url)``. The
fetch callable is injectable for tests; on any fetch/parse error the policy
defaults to *allow* (``allow_on_error``) so a flaky robots endpoint never blocks
a whole crawl — the per-site rate limit and manual review still apply.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

log = logging.getLogger(__name__)


def _http_fetch(url: str) -> str | None:
    try:
        import httpx

        resp = httpx.get(url, timeout=10.0, follow_redirects=True)
        if resp.status_code == 200:
            return resp.text
        # 4xx/5xx on robots.txt is conventionally "no restrictions".
        return None
    except Exception as exc:  # pragma: no cover - network dependent
        log.debug("robots fetch failed for %s: %s", url, exc)
        return None


class RobotsPolicy:
    def __init__(
        self,
        user_agent: str = "*",
        *,
        fetch: Callable[[str], str | None] | None = None,
        allow_on_error: bool = True,
    ) -> None:
        self.user_agent = user_agent
        self._fetch = fetch or _http_fetch
        self.allow_on_error = allow_on_error
        self._cache: dict[tuple[str, str], RobotFileParser | None] = {}

    def _parser_for(self, url: str) -> RobotFileParser | None:
        parts = urlsplit(url)
        host_key = (parts.scheme, parts.netloc)
        if host_key in self._cache:
            return self._cache[host_key]

        robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
        content = self._fetch(robots_url)
        parser: RobotFileParser | None = None
        if content is not None:
            parser = RobotFileParser()
            parser.parse(content.splitlines())
        self._cache[host_key] = parser
        return parser

    def allowed(self, url: str) -> bool:
        try:
            parser = self._parser_for(url)
            if parser is None:  # no robots.txt / unreachable → unrestricted
                return self.allow_on_error
            return parser.can_fetch(self.user_agent, url)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("robots check errored for %s: %s", url, exc)
            return self.allow_on_error
