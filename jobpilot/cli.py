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
    sub.add_parser("crawl", help="crawl jobs into DB (Phase 3)").set_defaults(
        func=_not_yet("Phase 3")
    )
    sub.add_parser("serve", help="run API backend (Phase 2)").set_defaults(
        func=_not_yet("Phase 2")
    )
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
