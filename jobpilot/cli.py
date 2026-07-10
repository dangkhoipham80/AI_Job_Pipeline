"""JobPilot CLI. Zero extra deps (argparse). Subcommands grow per phase.

python -m jobpilot.cli config    # validate + print resolved config (Phase 0)
python -m jobpilot.cli crawl     # Phase 3
python -m jobpilot.cli serve     # Phase 2+ (API)
"""

from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import urlsplit, urlunsplit

from jobpilot import __version__
from jobpilot.config import CONFIG_PATH, get_config, get_secrets


def _redact(value: str) -> str:
    if not value:
        return "(empty)"
    return f"set ({len(value)} chars)"


def _redact_url(url: str) -> str:
    """Mask credentials in a connection URL (never print user/password)."""
    if not url:
        return "(empty)"
    try:
        parts = urlsplit(url)
        if parts.username or parts.password:
            host = parts.hostname or ""
            if parts.port:
                host = f"{host}:{parts.port}"
            parts = parts._replace(netloc=f"***:***@{host}")
        return urlunsplit(parts)
    except Exception:
        return "(set, redacted)"


def cmd_config(_: argparse.Namespace) -> int:
    cfg = get_config()
    sec = get_secrets()
    print(f"JobPilot v{__version__}")
    print(f"config file: {CONFIG_PATH}")
    print("\n[config.yaml]")
    print(json.dumps(cfg.model_dump(), indent=2, ensure_ascii=False))
    enabled = ", ".join(s.key for s in cfg.enabled_sources()) or "(none)"
    print(f"\nenabled sources: {enabled}")
    print("\n[secrets] (redacted)")
    print(f"  database_url        : {_redact_url(sec.database_url)}")
    print(f"  anthropic_api_key   : {_redact(sec.anthropic_api_key)}")
    print(f"  jobpilot_api_token  : {_redact(sec.jobpilot_api_token)}")
    print(f"  slack_bot_token     : {_redact(sec.slack_bot_token)}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    from jobpilot.config import REPO_ROOT
    from jobpilot.tailor.build import BuildError, build_cv

    work_dir = args.dir or str(REPO_ROOT)
    try:
        result = build_cv(work_dir, entry=args.entry)
    except BuildError as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        return 1
    ok = "OK: 1 page" if result.pages == 1 else f"WARNING: {result.pages} pages (CV should be 1)"
    print(f"Built {result.pdf}  [{ok}]")
    return 0


def cmd_crawl(args: argparse.Namespace) -> int:
    from jobpilot.crawler.pipeline import default_query, run_crawl
    from jobpilot.crawler.registry import build_scrapers
    from jobpilot.store.db import session_scope

    cfg = get_config()
    scrapers = build_scrapers(cfg, respect_robots=not args.no_robots)
    if not scrapers:
        print("No enabled sources with a registered scraper. Check config.yaml.", file=sys.stderr)
        return 1

    query = args.query or default_query(cfg)
    print(
        f"Crawling {[s.source for s in scrapers]}  query={query!r}  limit={cfg.crawl.jobs_per_site}"
    )
    with session_scope() as db:
        report = run_crawl(scrapers, cfg, db, query=query)

    for site in report.sites:
        s = site.stats
        status = "ok " if site.ok else "FAIL"
        detail = (
            f"error={site.error}"
            if not site.ok
            else (
                f"fetched={s.fetched} new={s.inserted} upd={s.updated} "
                f"dup={s.duplicates} filtered={s.filtered} fresh={s.fresh}"
            )
        )
        print(f"  [{status}] {site.source:14s} {detail}")
    t = report.totals
    print(
        f"Total: new={t.inserted} updated={t.updated} duplicates={t.duplicates} fresh={t.fresh} (run #{report.run_id})"
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        print("uvicorn not installed — run: pip install -e '.[api]'", file=sys.stderr)
        return 1
    uvicorn.run(
        "jobpilot.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def _not_yet(phase: str):
    def _run(_: argparse.Namespace) -> int:
        print(f"Not implemented yet — arrives in {phase}. See PLAN.md §9.")
        return 0

    return _run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobpilot", description="JobPilot CLI")
    parser.add_argument("--version", action="version", version=f"jobpilot {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("config", help="validate & print resolved config").set_defaults(func=cmd_config)

    p_build = sub.add_parser("build", help="compile a CV to PDF via Docker (Phase 1)")
    p_build.add_argument("dir", nargs="?", default=None, help="work dir (default: repo root)")
    p_build.add_argument("--entry", default="cv.tex", help="LaTeX entry file")
    p_build.set_defaults(func=cmd_build)
    p_crawl = sub.add_parser("crawl", help="crawl enabled sources into the DB (Phase 3)")
    p_crawl.add_argument("--query", default=None, help="search query (default: from config stacks)")
    p_crawl.add_argument(
        "--no-robots", action="store_true", help="skip robots.txt checks (debug only)"
    )
    p_crawl.set_defaults(func=cmd_crawl)
    p_serve = sub.add_parser("serve", help="run FastAPI backend (Phase 2)")
    p_serve.add_argument("--host", default="127.0.0.1", help="bind host (localhost only)")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true", help="auto-reload on code change")
    p_serve.set_defaults(func=cmd_serve)
    sub.add_parser("run", help="crawl -> notify -> await (Phase 8)").set_defaults(
        func=_not_yet("Phase 8")
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
