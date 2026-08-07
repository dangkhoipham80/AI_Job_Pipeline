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
    # Listing pages to walk per site before giving up on reaching jobs_per_site.
    # A ceiling, not a target: a board with 50 cards a page never leaves page 1.
    max_pages: int = 5
    fresh_hours: int = 48
    # A posting older than this is flagged (never hidden) as possibly filled.
    stale_days: int = 45
    rate_limit_seconds: tuple[float, float] = (2.0, 5.0)
    match_score_min: float = 0.30
    stacks: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)


class SourceCfg(BaseModel):
    key: str
    tier: int = 1
    enabled: bool = False


class AtsCfg(BaseModel):
    """Company boards to read per ATS platform (PLAN §5.1.1 tier 3).

    A token is the company's slug in its careers-page URL — the ``gitlab`` in
    ``job-boards.greenhouse.io/gitlab``. Adding a company is one word here;
    there is no per-company code.
    """

    greenhouse: list[str] = Field(default_factory=list)
    lever: list[str] = Field(default_factory=list)

    def boards_for(self, key: str) -> list[str]:
        return list(getattr(self, key, []) or [])


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


class InboxCfg(BaseModel):
    """Reading employer replies out of your own mailbox (Phase 19).

    Off by default. Reading somebody's mail is not a thing to switch on for
    them, even when the reading is local and read-only.

    ``folder`` is the escape hatch for anyone who would rather not point this at
    a whole inbox: file replies into a label with a mail rule and name it here,
    and nothing outside it is ever opened. The default is still INBOX, because a
    reply you forgot to file is a reply JobPilot would never see.
    """

    enabled: bool = False
    folder: str = "INBOX"
    since_days: int = 30
    # Messages read per pass, newest first. Matching is local, so this bounds
    # mail *read*, not mail sent anywhere.
    limit: int = 100


class ApplyCfg(BaseModel):
    email: EmailCfg = Field(default_factory=EmailCfg)
    portal_prefill: bool = True
    inbox: InboxCfg = Field(default_factory=InboxCfg)

    def email_blocker(self) -> str:
        """Why the email channel may not run, or '' if it may."""
        if not self.email.enabled:
            return "email apply is disabled (apply.email.enabled)"
        if not self.email.from_addr:
            return "apply.email.from_addr is not set"
        return ""

    def inbox_blocker(self, secrets: "Secrets | None" = None) -> str:
        """Why the inbox sync may not run, or '' if it may."""
        if not self.inbox.enabled:
            return "inbox sync is off (apply.inbox.enabled)"
        s = secrets or get_secrets()
        if not s.imap_user or not s.imap_password:
            return (
                "IMAP_USER / IMAP_PASSWORD are not set in .env — for Gmail this must be "
                "an App Password, not your account password"
            )
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
    ats: AtsCfg = Field(default_factory=AtsCfg)
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

    # Reading *your own* mailbox for LinkedIn Job Alerts (Phase 9). Gmail needs
    # an App Password, not your account password — see CLAUDE.md.
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""


def deep_merge(base: dict, overlay: dict) -> dict:
    """Overlay wins, but only for the keys it actually sets."""
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def merge_sources(base: list, overlay: list) -> list:
    """Merge the source list *by key* instead of replacing it wholesale.

    ``deep_merge`` overwrites lists, which is right for ``stacks`` but wrong
    here: the overlay written by the Settings page holds one entry per source
    that existed *when it was saved*, so a plain overwrite makes every source
    added to ``config.yaml`` since then vanish. Not merely default-off —
    absent, and therefore impossible to switch on in the Settings page that
    caused it. Adding the tier-2 feeds hit exactly that.

    So ``config.yaml`` owns the catalogue and its order; the overlay only
    carries your preferences for the sources it names. A key the overlay
    invents is still kept, so a hand-added source is not silently dropped.
    """
    merged = {s["key"]: dict(s) for s in base if isinstance(s, dict) and s.get("key")}
    order = list(merged)
    for src in overlay or []:
        if not isinstance(src, dict) or not src.get("key"):
            continue
        key = src["key"]
        if key in merged:
            merged[key].update(src)
        else:
            merged[key] = dict(src)
            order.append(key)
    return [merged[k] for k in order]


def resolve_config(base: dict, overlay: dict) -> dict:
    """``config.yaml`` + ``config.local.yaml`` → the settings the app runs on."""
    data = deep_merge(base, overlay)
    if isinstance(base.get("sources"), list):
        data["sources"] = merge_sources(base["sources"], overlay.get("sources") or [])
    return data


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@lru_cache
def get_config(path: Path | None = None) -> Config:
    p = path or CONFIG_PATH
    return Config.model_validate(resolve_config(_read_yaml(p), _read_yaml(LOCAL_CONFIG_PATH)))


def save_local_config(patch: dict) -> Config:
    """Merge ``patch`` into the overlay, validate the result, then persist it.

    Validating before writing means a bad Settings save is rejected rather than
    leaving the app unable to load its own config on next start.
    """
    merged_overlay = deep_merge(_read_yaml(LOCAL_CONFIG_PATH), patch)
    # Validate exactly what get_config() will build, or a save can pass here and
    # then fail on the next start.
    Config.model_validate(resolve_config(_read_yaml(CONFIG_PATH), merged_overlay))

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
