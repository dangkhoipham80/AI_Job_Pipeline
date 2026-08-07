"""Network fetching. A *fetcher* is any callable ``(url) -> text``.

Scrapers accept one so tests can inject an offline dict-backed fetcher and never
touch the network. Two real implementations, and the choice is not cosmetic:

* :class:`PlaywrightFetcher` drives a Chromium and returns the HTML *after* the
  SPA has hydrated. Needed by ITviec and VietnamWorks, whose job lists arrive by
  XHR.
* :class:`HttpFetcher` is a plain HTTP GET. Needed by anything that serves a
  document rather than an app — above all the official RSS/JSON feeds, which a
  browser actively *corrupts*: Chromium renders a JSON response as
  ``<html><body><pre>{…}</pre></body></html>``, so ``page.content()`` hands the
  parser markup where it expected JSON.

Scrapers declare which one they want via ``BaseScraper.default_fetcher``.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class FetchError(RuntimeError):
    """A URL could not be retrieved. Caught per-page by the crawl loop."""


class PlaywrightError(FetchError):
    """Playwright missing or a page failed to load."""


class HttpFetcher:
    """Fetch a URL with a plain HTTP GET, no browser.

    Usage::

        with HttpFetcher(accept="application/json") as fetch:
            body = fetch("https://jobicy.com/api/v2/remote-jobs?tag=java")

    One ``httpx.Client`` is reused across calls so connections (and any cookies
    the site sets) are kept, the same way the browser context is.
    """

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        timeout: float = 20.0,
    ) -> None:
        self.user_agent = user_agent
        self.accept = accept
        self.timeout = timeout
        self._client = None

    def start(self) -> HttpFetcher:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - env dependent
            raise FetchError("httpx not installed. Run:\n  pip install -e '.[crawler]'") from exc
        self._client = httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": self.user_agent, "Accept": self.accept},
        )
        return self

    def get(self, url: str) -> str:
        if self._client is None:
            self.start()
        assert self._client is not None
        try:
            resp = self._client.get(url)
        except Exception as exc:  # pragma: no cover - network dependent
            raise FetchError(f"failed to load {url}: {exc}") from exc
        if resp.status_code >= 400:
            # Raised, not returned: an error body parses to zero hits, which the
            # crawl loop would otherwise read as "this page has no more jobs".
            raise FetchError(f"{url} returned HTTP {resp.status_code}")
        return resp.text

    __call__ = get

    def close(self) -> None:
        try:
            if self._client is not None:
                self._client.close()
        except Exception:  # pragma: no cover
            pass
        self._client = None

    def __enter__(self) -> HttpFetcher:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.close()


class PlaywrightFetcher:
    """Fetch fully-rendered HTML with a persistent Chromium context.

    Usage::

        with PlaywrightFetcher() as fetch:
            html = fetch("https://itviec.com/it-jobs?query=java")

    The browser is launched lazily on first ``get`` and reused across calls
    (one context = one session, kinder to anti-bot heuristics).
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_ms: int = 30_000,
        wait_until: str = "domcontentloaded",
        settle_ms: int = 6_000,
        locale: str = "vi-VN",
    ) -> None:
        self.headless = headless
        self.user_agent = user_agent
        self.timeout_ms = timeout_ms
        self.wait_until = wait_until
        self.settle_ms = settle_ms
        self.locale = locale
        self._pw = None
        self._browser = None
        self._ctx = None

    def start(self) -> PlaywrightFetcher:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - env dependent
            raise PlaywrightError(
                "Playwright not installed. Run:\n"
                "  pip install -e '.[crawler]'\n"
                "  playwright install chromium"
            ) from exc
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._ctx = self._browser.new_context(user_agent=self.user_agent, locale=self.locale)
        return self

    def get(self, url: str) -> str:
        if self._ctx is None:
            self.start()
        assert self._ctx is not None
        page = self._ctx.new_page()
        try:
            response = page.goto(url, wait_until=self.wait_until, timeout=self.timeout_ms)
            # An anti-bot interstitial is still a *page*: it parses cleanly and
            # yields zero hits, which is indistinguishable from "this search had
            # no results" once it reaches a CSS selector. TopCV's second request
            # in a session comes back as Cloudflare's "Sorry, you have been
            # blocked" — and the crawl logged "end of results" and moved on.
            # The status code is the one place the truth survives, so refusing
            # here keeps the parser from having to guess.
            if response is not None and response.status >= 400:
                raise PlaywrightError(
                    f"{url} returned HTTP {response.status}"
                    + (" (blocked — anti-bot)" if response.status in (403, 429) else "")
                )
            self._settle(page)
            return page.content()
        except PlaywrightError:
            raise
        except Exception as exc:  # pragma: no cover - network dependent
            raise PlaywrightError(f"failed to load {url}: {exc}") from exc
        finally:
            page.close()

    def _settle(self, page) -> None:  # pragma: no cover - network dependent
        """Give the SPA a chance to hydrate, but never make the fetch depend on it.

        Waiting for ``networkidle`` as the *load* condition is a trap: job boards
        run analytics beacons and open sockets that never go quiet, so the page
        renders fine while ``goto`` sits there until it times out and the whole
        crawl fails with nothing to show. ITviec did exactly that.

        So the load itself only needs the DOM, and idleness becomes a short,
        optional bonus: if the site settles we get fully hydrated HTML, and if it
        never does we still return the markup that is already there.
        """
        try:
            page.wait_for_load_state("networkidle", timeout=self.settle_ms)
        except Exception:
            page.wait_for_timeout(min(self.settle_ms, 1_500))

    __call__ = get

    def close(self) -> None:
        for obj in (self._ctx, self._browser):
            try:
                if obj is not None:
                    obj.close()
            except Exception:  # pragma: no cover
                pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:  # pragma: no cover
            pass
        self._ctx = self._browser = self._pw = None

    def __enter__(self) -> PlaywrightFetcher:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.close()
