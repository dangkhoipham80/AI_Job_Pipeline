"""JobPilot CLI. Zero extra deps (argparse). Subcommands grow per phase.

python -m jobpilot.cli config    # validate + print resolved config (Phase 0)
python -m jobpilot.cli crawl     # Phase 3
python -m jobpilot.cli serve     # Phase 2+ (API)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
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


def cmd_cv(args: argparse.Namespace) -> int:
    """CV Studio from the terminal: seed / render / build / list versions."""
    from jobpilot.cv import store
    from jobpilot.cv.compile import build_dir, compile_document
    from jobpilot.cv.render import write_document
    from jobpilot.store.db import session_scope
    from jobpilot.tailor.build import BuildError

    with session_scope() as db:
        if args.cv_command == "seed":
            row = store.ensure_master(db)
            print(f"Master CV at version {row.version} (author={row.author})")
            return 0

        if args.cv_command == "import":
            # The only way personal data enters the app. After this it lives in
            # the database and is read through the API.
            try:
                doc = store.read_document(Path(args.file))
            except (OSError, ValueError) as exc:
                print(f"ERROR: could not read {args.file}: {exc}", file=sys.stderr)
                return 1
            row = store.save_version(db, args.scope, doc, author="user")
            name = f"{doc.header.first_name} {doc.header.last_name}".strip() or "(no name)"
            print(f"Imported into {args.scope} as v{row.version}: {name}")
            return 0

        if args.cv_command == "export":
            try:
                doc = store.get_document(db, args.scope)
            except store.ScopeNotFound as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 1
            payload = doc.model_dump(mode="json")
            payload = {
                "_comment": "Exported from the JobPilot database. Contains personal data — "
                "keep it out of git (*.local.json is gitignored).",
                **payload,
            }
            Path(args.file).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(f"Exported {args.scope} to {args.file}")
            return 0

        if args.cv_command == "versions":
            rows = store.list_versions(db, args.scope)
            if not rows:
                print(f"No versions for scope {args.scope!r}.")
                return 1
            for r in rows:
                print(f"  v{r.version:<4d} {r.author:<6s} {r.created_at}")
            return 0

        try:
            doc = store.get_document(db, args.scope)
        except store.ScopeNotFound as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    if args.cv_command == "render":
        dest = write_document(doc, build_dir(args.scope))
        print(f"Rendered .tex into {dest}")
        return 0

    try:
        result = compile_document(doc, args.scope)
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
    limit = args.limit or cfg.crawl.jobs_per_site
    print(f"Crawling {[s.source for s in scrapers]}  query={query!r}  limit={limit}")
    with session_scope() as db:
        report = run_crawl(scrapers, cfg, db, query=query, limit=args.limit)

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


def cmd_tailor(args: argparse.Namespace) -> int:
    """Tailor the Master CV to one job and report the plan (Phase 5)."""
    from jobpilot.store.db import session_scope
    from jobpilot.tailor import service
    from jobpilot.tailor.build import BuildError
    from jobpilot.tailor.engine import TailorError, default_engine
    from jobpilot.tailor.guard import GuardrailViolation

    with session_scope() as db:
        try:
            outcome = service.tailor_job(
                db,
                args.job_id,
                default_engine(),
                instruction=args.instruction,
                compile_pdf=not args.no_build,
            )
        except service.TailorRefused as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 1
        except GuardrailViolation as exc:
            print(f"GUARDRAIL: {exc}", file=sys.stderr)
            return 1
        except (TailorError, BuildError) as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 1

        plan = outcome.plan
        pages = "n/a" if outcome.pages is None else f"{outcome.pages} page(s)"
        print(f"{args.job_id}: v{outcome.version}  match={plan.match_score:.0%}  {pages}")
        for change in plan.changes:
            print(f"  ~ [{change.section}] {change.what}  ({change.reason})")
        for gap in plan.gaps():
            print(f"  ! gap ({gap.kind}): {gap.text}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    """Dispatch an approved job to its channel (Phase 6)."""
    from jobpilot.apply import dispatcher
    from jobpilot.apply.letter import default_letter_engine
    from jobpilot.apply.portal import prefill_with_browser
    from jobpilot.store.db import session_scope

    cfg = get_config()
    engine = None
    if not args.no_letter and get_secrets().anthropic_api_key:
        engine = default_letter_engine()

    with session_scope() as db:
        try:
            outcome = dispatcher.apply_job(db, args.job_id, engine)
        except dispatcher.ApplyRefused as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 1

    print(f"{args.job_id}: channel={outcome.channel} result={outcome.result}")
    print(f"  {outcome.detail}")
    if outcome.result == "dry_run":
        gates = cfg.apply.email
        print(
            f"  gates: enabled={gates.enabled} dry_run={gates.dry_run} "
            f"test_recipient={gates.test_recipient or '(none)'}"
        )
    if outcome.handoff:
        print(f"  open: {outcome.handoff.url}")
        print(f"  CV  : {outcome.handoff.cv_path}")
        for key, value in outcome.handoff.fields.items():
            print(f"    {key:<12} {value}")
        if args.open_portal:
            prefill_with_browser(outcome.handoff)
        print("  when you've submitted it, run: jobpilot confirm-submit " + args.job_id)
    return 0 if outcome.result != "failed" else 1


def cmd_confirm_submit(args: argparse.Namespace) -> int:
    from jobpilot.apply import dispatcher
    from jobpilot.store.db import session_scope

    with session_scope() as db:
        try:
            job = dispatcher.confirm_submit(db, args.job_id)
        except dispatcher.ApplyRefused as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 1
        print(f"{args.job_id}: {job.status.value}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Crawl, report, and stop — optionally on a loop (PLAN.md §9 'cron nhẹ').

    A plain loop rather than a scheduler dependency: it is one less thing to
    install, and `--every` is easy to reason about when it wakes at 3am.
    """
    import time

    from jobpilot.orchestrator import crawl_body

    def once() -> int:
        try:
            result = crawl_body(query=args.query, respect_robots=not args.no_robots)(print)
        except Exception as exc:
            print(f"CRAWL FAILED: {exc}", file=sys.stderr)
            return 1
        for site in result["sites"]:
            status = "ok " if site["ok"] else "FAIL"
            detail = (
                f"error={site['error']}"
                if not site["ok"]
                else (
                    f"fetched={site['fetched']} new={site['inserted']} "
                    f"upd={site['updated']} dup={site['duplicates']} fresh={site['fresh']}"
                )
            )
            print(f"  [{status}] {site['source']:14s} {detail}")
        t = result["totals"]
        print(f"Total: new={t['inserted']} updated={t['updated']} fresh={t['fresh']}")
        # Individual site failures are normal and don't fail the batch, but a run
        # where nothing worked should be visible to whatever scheduled it.
        sites = result["sites"]
        return 1 if sites and not any(s["ok"] for s in sites) else 0

    if not args.every:
        return once()

    print(f"Looping every {args.every} minutes — Ctrl-C to stop.")
    try:
        while True:
            once()
            print(f"-- sleeping {args.every}m --")
            time.sleep(args.every * 60)
    except KeyboardInterrupt:
        print("\nstopped")
        return 0


def cmd_slack(args: argparse.Namespace) -> int:
    """Run the Slack companion app (Phase 7). Needs the API already running."""
    from jobpilot.slack.app import SlackNotConfigured, run

    try:
        run(api_base=args.api, web_base=args.web)
    except SlackNotConfigured as exc:
        print(f"Slack not started: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nstopped")
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobpilot", description="JobPilot CLI")
    parser.add_argument("--version", action="version", version=f"jobpilot {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("config", help="validate & print resolved config").set_defaults(func=cmd_config)

    p_build = sub.add_parser("build", help="compile a CV to PDF via Docker (Phase 1)")
    p_build.add_argument("dir", nargs="?", default=None, help="work dir (default: repo root)")
    p_build.add_argument("--entry", default="cv.tex", help="LaTeX entry file")
    p_build.set_defaults(func=cmd_build)
    p_cv = sub.add_parser("cv", help="CV Studio: seed/import/export/render/build (Phase 4.5)")
    cv_sub = p_cv.add_subparsers(dest="cv_command", required=True)
    cv_sub.add_parser("seed", help="create an empty Master CV if there isn't one (idempotent)")

    p_import = cv_sub.add_parser("import", help="load a CV JSON file into the database")
    p_import.add_argument("file", help="path to a CV document JSON")
    p_import.add_argument("--scope", default="master", help="'master' or a job id")

    p_export = cv_sub.add_parser("export", help="write a CV from the database to JSON (backup)")
    p_export.add_argument("file", help="destination path — use *.local.json to stay gitignored")
    p_export.add_argument("--scope", default="master", help="'master' or a job id")
    for name, helptext in (
        ("render", "write the structured CV out as .tex"),
        ("build", "render + compile to PDF via Docker"),
        ("versions", "list the version history"),
    ):
        sp = cv_sub.add_parser(name, help=helptext)
        sp.add_argument("scope", nargs="?", default="master", help="'master' or a job id")
    p_cv.set_defaults(func=cmd_cv)

    p_crawl = sub.add_parser("crawl", help="crawl enabled sources into the DB (Phase 3)")
    p_crawl.add_argument("--query", default=None, help="search query (default: from config stacks)")
    p_crawl.add_argument(
        "--no-robots", action="store_true", help="skip robots.txt checks (debug only)"
    )
    p_crawl.add_argument(
        "--limit",
        type=int,
        default=None,
        help="jobs per site for this run (default: config crawl.jobs_per_site)",
    )
    p_crawl.set_defaults(func=cmd_crawl)
    p_tailor = sub.add_parser("tailor", help="tailor the Master CV to a job (Phase 5)")
    p_tailor.add_argument("job_id", help="job id, e.g. itviec:2156537")
    p_tailor.add_argument(
        "--instruction", default=None, help="revision instruction for an edit round"
    )
    p_tailor.add_argument(
        "--no-build", action="store_true", help="produce the plan without building the PDF"
    )
    p_tailor.set_defaults(func=cmd_tailor)

    p_apply = sub.add_parser("apply", help="dispatch an approved job to its channel (Phase 6)")
    p_apply.add_argument("job_id")
    p_apply.add_argument("--no-letter", action="store_true", help="skip the cover letter")
    p_apply.add_argument(
        "--open-portal",
        action="store_true",
        help="for portal jobs, open a visible browser and pre-fill what it can (never submits)",
    )
    p_apply.set_defaults(func=cmd_apply)

    p_confirm = sub.add_parser("confirm-submit", help="mark a portal/external job as submitted")
    p_confirm.add_argument("job_id")
    p_confirm.set_defaults(func=cmd_confirm_submit)

    p_serve = sub.add_parser("serve", help="run FastAPI backend (Phase 2)")
    p_serve.add_argument("--host", default="127.0.0.1", help="bind host (localhost only)")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true", help="auto-reload on code change")
    p_serve.set_defaults(func=cmd_serve)
    p_slack = sub.add_parser("slack", help="run the Slack companion app (Phase 7)")
    p_slack.add_argument("--api", default="http://127.0.0.1:8000", help="JobPilot API base URL")
    p_slack.add_argument("--web", default="http://localhost:5173", help="dashboard base URL")
    p_slack.set_defaults(func=cmd_slack)

    p_run = sub.add_parser("run", help="crawl once, or on a loop (Phase 8)")
    p_run.add_argument("--query", default=None, help="search query (default: from config stacks)")
    p_run.add_argument("--no-robots", action="store_true", help="skip robots.txt (debug only)")
    p_run.add_argument("--every", type=int, default=0, help="repeat every N minutes")
    p_run.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
