"""Network fetching via Playwright (lazy import; only needed for live crawls).

A *fetcher* is any callable ``(url) -> html``. Scrapers accept one so tests can
inject an offline dict-backed fetcher and never touch the network. The real
implementation launches a stealth-ish Chromium and returns page HTML after the
SPA has hydrated.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class PlaywrightError(RuntimeError):
    """Playwright missing or a page failed to load."""


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
        wait_until: str = "networkidle",
        locale: str = "vi-VN",
    ) -> None:
        self.headless = headless
        self.user_agent = user_agent
        self.timeout_ms = timeout_ms
        self.wait_until = wait_until
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
            page.goto(url, wait_until=self.wait_until, timeout=self.timeout_ms)
            return page.content()
        except Exception as exc:  # pragma: no cover - network dependent
            raise PlaywrightError(f"failed to load {url}: {exc}") from exc
        finally:
            page.close()

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
