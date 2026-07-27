"""Config loading for JobPilot.

Two layers:
  * config.yaml  -> non-secret settings (crawl rules, sources, apply, cv)  -> `Config`
  * .env         -> secrets (DB url, API keys, tokens)                     -> `Secrets`

Usage:
    from jobpilot.config import get_config, get_secrets
    cfg = get_config()
    sec = get_secrets()
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent
CONFIG_PATH = PACKAGE_DIR / "config.yaml"
# Overlay written by the Settings page. config.yaml is heavily commented and
# those comments are load-bearing documentation (the email safety gates most of
# all), and YAML round-tripping would strip them — so edits land in a separate,
# gitignored file that is merged on top instead.
LOCAL_CONFIG_PATH = PACKAGE_DIR / "config.local.yaml"


# --------------------------------------------------------------------------- #
# Non-secret config (config.yaml)
# --------------------------------------------------------------------------- #
class AppCfg(BaseModel):
    timezone: str = "Asia/Ho_Chi_Minh"
    edit_max_rounds: int = 3


class CrawlCfg(BaseModel):
    jobs_per_site: int = 10
    fresh_hours: int = 48
    rate_limit_seconds: tuple[float, float] = (2.0, 5.0)
    match_score_min: float = 0.30
    stacks: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)


class SourceCfg(BaseModel):
    key: str
    tier: int = 1
    enabled: bool = False


class EmailCfg(BaseModel):
    """Email is the one channel allowed to send without a second confirmation
    (CLAUDE.md rule 2), so it is gated three ways: off by default, dry-run by
    default, and able to redirect every message to your own inbox until you
    trust it."""

    enabled: bool = False
    method: Literal["gmail", "smtp"] = "gmail"
    from_addr: str = ""
    from_name: str = ""
    # Build and record the message, but never hand it to a mail server.
    dry_run: bool = True
    # Deliver to this address instead of the employer — "test email mình trước"
    # (PLAN.md §9 Phase 6). Empty means mail really goes to the job's contact.
    test_recipient: str = ""
    subject_template: str = "Application for {title} — {name}"


class ApplyCfg(BaseModel):
    email: EmailCfg = Field(default_factory=EmailCfg)
    portal_prefill: bool = True

    def email_blocker(self) -> str:
        """Why the email channel may not run, or '' if it may."""
        if not self.email.enabled:
            return "email apply is disabled (apply.email.enabled)"
        if not self.email.from_addr:
            return "apply.email.from_addr is not set"
        return ""


class CvCfg(BaseModel):
    master_dir: str = "resume"
    out_dir: str = "out"
    docker_image: str = "csmith/awesome-cv-builder"
    theme: str = "awesome-red"


class Config(BaseModel):
    app: AppCfg = Field(default_factory=AppCfg)
    crawl: CrawlCfg = Field(default_factory=CrawlCfg)
    sources: list[SourceCfg] = Field(default_factory=list)
    apply: ApplyCfg = Field(default_factory=ApplyCfg)
    cv: CvCfg = Field(default_factory=CvCfg)

    def enabled_sources(self) -> list[SourceCfg]:
        return [s for s in self.sources if s.enabled]


# --------------------------------------------------------------------------- #
# Secrets (.env)
# --------------------------------------------------------------------------- #
class Secrets(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://jobpilot:jobpilot@localhost:5432/jobpilot"
    anthropic_api_key: str = ""
    jobpilot_api_token: str = "changeme"

    slack_bot_token: str = ""
    slack_app_token: str = ""
    slack_channel_id: str = ""

    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""


def deep_merge(base: dict, overlay: dict) -> dict:
    """Overlay wins, but only for the keys it actually sets."""
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@lru_cache
def get_config(path: Path | None = None) -> Config:
    p = path or CONFIG_PATH
    data = deep_merge(_read_yaml(p), _read_yaml(LOCAL_CONFIG_PATH))
    return Config.model_validate(data)


def save_local_config(patch: dict) -> Config:
    """Merge ``patch`` into the overlay, validate the result, then persist it.

    Validating before writing means a bad Settings save is rejected rather than
    leaving the app unable to load its own config on next start.
    """
    merged_overlay = deep_merge(_read_yaml(LOCAL_CONFIG_PATH), patch)
    Config.model_validate(deep_merge(_read_yaml(CONFIG_PATH), merged_overlay))

    header = (
        "# Written by the JobPilot Settings page — merged on top of config.yaml.\n"
        "# Safe to delete: that just restores the defaults in config.yaml.\n"
    )
    LOCAL_CONFIG_PATH.write_text(
        header + yaml.safe_dump(merged_overlay, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    get_config.cache_clear()
    return get_config()


@lru_cache
def get_secrets() -> Secrets:
    return Secrets()
