"""Pydantic response schemas for the API (serialize ORM rows)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from jobpilot.apply import outcome as outcome_mod
from jobpilot.apply.followup import describe, is_due
from jobpilot.cv.schema import CvDocument
from jobpilot.store.models import Job, JobStatus
from jobpilot.tailor.diff import CvDiff

T = TypeVar("T")

#: Rows per request when the caller doesn't say.
DEFAULT_PAGE_SIZE = 25
#: Hard ceiling. A caller asking for more gets a 422, not a slow success — an
#: unbounded list endpoint is a denial-of-service against your own dashboard,
#: and `/applications` had no cap at all.
MAX_PAGE_SIZE = 200


class Page(BaseModel, Generic[T]):
    """One window onto a list, plus the size of the list it came from.

    ``total`` is the point. Every list endpoint used to return a bare array,
    which cannot answer "is there more?" — a page of 25 out of 25 and a page of
    25 out of 900 look identical on the wire, so the UI either lies about being
    complete or has to guess from `len(items) == limit` (wrong exactly when the
    total is an even multiple). It is counted with the same filters as the
    window, so it is the total of *this* query, not of the table.
    """

    items: list[T]
    total: int
    limit: int
    offset: int


class JobOut(BaseModel):
    """List-row projection (no heavy JD payload)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    source: str
    url: str
    title: str
    company: str
    location: str | None
    salary: str | None
    level: str | None
    posted_at: datetime | None
    status: JobStatus
    match_score: float
    apply_channel: str | None
    apply_target: str | None
    crawled_at: datetime | None
    # Which crawl discovered this job (null for hand-added ones).
    run_id: int | None = None
    # Why the score is what it is, and whether the posting looks worth
    # answering. Advisory only — nothing here filters a job out.
    quality: dict | None = None


class JobDetailOut(JobOut):
    """Detail view: adds JD payload fields pulled from ``Job.payload``."""

    skills: list[str] = []
    description_md: str = ""
    is_fresh: bool = False
    # True when the source announced the job but couldn't carry its text —
    # LinkedIn alerts, mainly. Paste one in before tailoring.
    needs_jd: bool = False

    @classmethod
    def from_job(cls, job: Job) -> "JobDetailOut":
        payload: dict[str, Any] = job.payload or {}
        return cls(
            **JobOut.model_validate(job).model_dump(),
            skills=payload.get("skills", []) or [],
            description_md=payload.get("description_md", "") or "",
            is_fresh=bool(payload.get("is_fresh", False)),
            needs_jd=bool(payload.get("needs_jd", False)),
        )


class StatsOut(BaseModel):
    total: int
    fresh: int
    by_status: dict[str, int]
    by_source: dict[str, int]
    by_level: dict[str, int]
    by_day: dict[str, int]  # crawled_at date (YYYY-MM-DD) -> count
    #: What happened after the applications went out (Phase 18). Always present:
    #: an empty pipeline is zeroes, not a missing key the UI has to guard.
    outcomes: "OutcomeStats"


# --------------------------------------------------------------------------- #
# CV Studio (Phase 4.5)
# --------------------------------------------------------------------------- #
class CvDocumentOut(BaseModel):
    """The structured CV plus which version it is."""

    scope: str
    version: int
    document: CvDocument
    #: True when the PDF is built from hand-edited LaTeX, so edits made here no
    #: longer reach it. The editor has to say so — silently ignoring what someone
    #: types is worse than refusing to accept it.
    tex_override: bool = False


class CvTexOut(BaseModel):
    """The LaTeX project behind a scope, for the raw editor.

    Carries both what the JSON renders to and what is actually built, so the
    editor can show a per-file "revert to generated" without a second request —
    and so a stale override is visible rather than merely in effect.
    """

    scope: str
    version: int
    overridden: bool
    #: Effective project: generated files with the override written over them.
    files: dict[str, str]
    generated: dict[str, str]


class CvTexIn(BaseModel):
    """Raw ``.tex`` files to build instead of the generated ones."""

    files: dict[str, str]


class CvVersionOut(BaseModel):
    """Version-history row (content omitted — fetch the detail endpoint for it)."""

    model_config = ConfigDict(from_attributes=True)

    version: int
    author: str
    created_at: datetime | None


class CvVersionDetailOut(CvVersionOut):
    document: CvDocument
    tex: str


class CvVersionDiffOut(BaseModel):
    """Structural diff between two versions of one scope.

    ``base``/``target`` echo the versions actually compared, so the UI labels the
    panel from the response rather than from what it believes it asked for.
    """

    scope: str
    base: int
    target: int
    base_author: str
    target_author: str
    diff: CvDiff


class CvCompileOut(BaseModel):
    scope: str
    version: int
    #: None when the build succeeded but the page count couldn't be read.
    pages: int | None
    pdf_url: str
    # What a parser gets back out of the PDF. `None` means "not checked" (pypdf
    # missing), which the UI must not render as a pass.
    ats: dict | None = None


# --------------------------------------------------------------------------- #
# Tailor + CV Review (Phase 5)
# --------------------------------------------------------------------------- #
class TailorIn(BaseModel):
    instruction: str


class JobIn(BaseModel):
    """Add a job by hand — the path for anything the crawlers can't reach.

    Mostly LinkedIn: its robots.txt forbids automated access to job pages, so you
    find the posting yourself and paste it here. Everything downstream (tailor,
    review, apply) then works exactly as it does for a crawled job.
    """

    url: str = ""
    title: str
    company: str
    location: str | None = None
    salary: str | None = None
    level: str | None = None
    description_md: str = ""
    skills: list[str] = []
    # Defaults to external — you submit it yourself, which is the honest default
    # for a job we couldn't crawl.
    apply_channel: str = "external"
    apply_target: str | None = None


class JobPatch(BaseModel):
    """Fill in or correct a job. Only the fields present are touched, so pasting
    a description can't wipe the title."""

    title: str | None = None
    company: str | None = None
    location: str | None = None
    salary: str | None = None
    level: str | None = None
    url: str | None = None
    description_md: str | None = None
    skills: list[str] | None = None
    apply_channel: str | None = None
    apply_target: str | None = None


class ApplyIn(BaseModel):
    # None = generate a cover letter when a Claude key is configured.
    cover_letter: bool | None = None


class FailureIn(BaseModel):
    reason: str = ""


class ApplicationOut(BaseModel):
    """One card on the Applications board."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: str
    job_title: str
    company: str
    job_status: JobStatus
    channel: str | None
    result: str | None
    error_msg: str | None
    submitted_at: datetime | None
    created_at: datetime | None
    cv_pdf_path: str | None
    # The letter as sent (text) and as filed (PDF). A non-null text with a null
    # PDF is a real state — the build failed — and `meta.letter.pdf_error` says
    # why, so the board can show the reason instead of an unexplained gap.
    cover_letter_path: str | None = None
    cover_letter_pdf_path: str | None = None
    apply_target: str | None
    meta: dict = {}
    # Where this application is in the follow-up cadence, and when it's due.
    followup_stage: str | None = None
    next_followup_at: datetime | None = None
    followup_due: bool = False
    followup_hint: str = ""
    # What happened after it went out. NULL is "nothing recorded yet", which the
    # board renders as a prompt rather than as an outcome (Phase 18).
    outcome_stage: str | None = None
    outcome_hint: str = ""

    @classmethod
    def from_row(cls, app: Any, job: Job) -> "ApplicationOut":
        return cls(
            id=app.id,
            job_id=app.job_id,
            job_title=job.title,
            company=job.company,
            job_status=job.status,
            channel=app.channel,
            result=app.result,
            error_msg=app.error_msg,
            submitted_at=app.submitted_at,
            created_at=app.created_at,
            cv_pdf_path=app.cv_pdf_path,
            cover_letter_path=app.cover_letter_path,
            cover_letter_pdf_path=app.cover_letter_pdf_path,
            apply_target=job.apply_target,
            meta=app.meta or {},
            followup_stage=app.followup_stage,
            next_followup_at=app.next_followup_at,
            followup_due=is_due(app.next_followup_at),
            followup_hint=describe(app.followup_stage),
            outcome_stage=app.outcome_stage,
            outcome_hint=outcome_mod.describe(app.outcome_stage),
        )


# --------------------------------------------------------------------------- #
# Outcome tracking (Phase 18)
# --------------------------------------------------------------------------- #
OutcomeType = Literal["replied", "interview", "offer", "rejected", "withdrawn", "ghosted"]


class OutcomeIn(BaseModel):
    """Recording one thing that happened after the application went out."""

    event_type: OutcomeType
    #: When it actually happened. Defaults to now, but a reply you're entering on
    #: Friday may have arrived on Tuesday, and time-to-reply should believe you.
    occurred_at: datetime | None = None
    label: str | None = Field(None, max_length=outcome_mod.MAX_LABEL)
    notes: str | None = None


class ApplicationEventOut(BaseModel):
    """One row of an application's history."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    event_type: str
    # Both NOT NULL in the table, so they are non-optional here too — declaring
    # them nullable would describe a contract the database can't produce.
    occurred_at: datetime
    recorded_at: datetime
    label: str | None = None
    notes: str | None = None
    is_retracted: bool = False


class OutcomeStats(BaseModel):
    """Two ways of counting, because one of them lies.

    ``current`` buckets each application by its latest live event — what the
    board is showing. ``reached`` counts how many applications ever touched each
    stage. Rates use ``reached``: an application that interviewed and was then
    rejected is in ``current["rejected"]`` only, and dividing by that would
    report the applications *stuck* in interviews instead of the ones that got
    one.

    Rates are ``None``, not ``0.0``, when the denominator is zero — see
    ``apply.outcome.outcome_counts``.
    """

    total_real: int
    no_outcome: int
    current: dict[str, int]
    reached: dict[str, int]
    #: Applications that got any human answer at all (an interview invite is a
    #: reply even when nobody typed "replied" first).
    answered: int
    reply_rate: float | None = None
    interview_rate: float | None = None
    offer_rate: float | None = None


class BackendStatsOut(BaseModel):
    """What one (task, provider, model) combination has cost and delivered.

    ``first_try_rate`` is the quality number: the share of tasks the guardrails
    accepted without a corrective round. It and ``success_rate`` are ``None``
    below ``llm.stats.MIN_SAMPLE`` — three calls with two failures is not "33%",
    it is three calls, and a percentage invites a comparison the sample cannot
    support.

    ``cost_usd`` is ``None`` when no round on record carried a price;
    ``unpriced_rounds`` says how many were missing, so a total built from half
    the rows is not read as if it covered all of them.
    """

    task: str
    provider: str
    model: str
    attempts: int
    rounds: int
    cost_usd: float | None = None
    unpriced_rounds: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    p50_latency_ms: int = 0
    p95_latency_ms: int = 0
    first_try_rate: float | None = None
    success_rate: float | None = None


class ModelOptionOut(BaseModel):
    """One model the picker can offer, with what it costs to run.

    Sourced from the price table, so the list is exactly "models we can tell you
    the price of". Anything else is still settable — the field accepts free text —
    but it will report an unknown cost, and saying so up front beats a dropdown
    that silently omits the model somebody wants.
    """

    provider: str
    model: str
    input_per_mtok: float
    output_per_mtok: float
    #: False when the provider's live model list does not include this id — the
    #: price table outlives the models it prices.
    available: bool = True


class ProviderSpendOut(BaseModel):
    """What one provider has cost, against what you said you put on it.

    ``remaining`` is **not** a balance read from the provider: every vendor's
    spend endpoint needs an *Admin* key, not the ordinary one JobPilot holds
    (checked — all three answer 401). It is ``budget_usd`` minus what JobPilot
    itself recorded, so it knows nothing about usage from anywhere else. A
    budget tracker, not an account balance, and the page says so.
    """

    provider: str
    has_key: bool
    spent_usd: float
    #: Rounds with no price in the table — the spend figure excludes them.
    unpriced_rounds: int
    budget_usd: float | None = None
    remaining_usd: float | None = None
    #: Live model ids the key can see. Empty when the provider could not be
    #: reached, which is not the same as "this provider has no models".
    models: list[str] = Field(default_factory=list)


class LlmStatsOut(BaseModel):
    """The backend comparison, plus what is currently configured to run each task."""

    #: Below this many attempts, rates are withheld — see ``BackendStatsOut``.
    min_sample: int
    backends: list[BackendStatsOut] = Field(default_factory=list)
    #: What the model picker can offer, grouped by provider.
    catalogue: list[ModelOptionOut] = Field(default_factory=list)
    #: Per-provider spend, budget and live model list.
    spend: list[ProviderSpendOut] = Field(default_factory=list)
    #: Total recorded spend across every provider.
    total_spent_usd: float = 0.0
    #: provider -> whether its API key is present, so the picker can grey out a
    #: backend you cannot actually reach.
    providers: dict[str, bool] = Field(default_factory=dict)
    #: Secrets whose .env value is being overridden by a different environment
    #: variable. Empty normally; when not, it explains a "wrong key" that looks
    #: unexplainable — see ``llm/redact.shadowed_secrets``.
    shadowed_env: list[str] = Field(default_factory=list)
    #: task -> provider, so the page can say which row is the one in force.
    configured: dict[str, str] = Field(default_factory=dict)
    #: task -> sentences about what that provider may do with the input.
    #: Empty for every provider that does not train on API data.
    warnings: dict[str, list[str]] = Field(default_factory=dict)
    #: task -> why it cannot run right now (missing key), '' when it can.
    blockers: dict[str, str] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Inbox suggestions (Phase 19)
# --------------------------------------------------------------------------- #
class SuggestionOut(BaseModel):
    """One employer reply and what it looks like it means.

    Carries ``quote`` and ``match_reason`` because the point is that you can
    overrule it by reading a line, rather than trusting a label.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    job_id: str = ""
    job_title: str = ""
    company: str = ""
    mail_from: str = ""
    mail_subject: str = ""
    mail_date: datetime | None = None
    match_confidence: str = ""
    match_reason: str = ""
    verdict: str
    quote: str = ""
    round_label: str | None = None
    status: str

    @classmethod
    def from_row(cls, row: Any, job: Job | None = None) -> "SuggestionOut":
        return cls(
            id=row.id,
            application_id=row.application_id,
            job_id=job.id if job else "",
            job_title=job.title if job else "",
            company=job.company if job else "",
            mail_from=row.mail_from or "",
            mail_subject=row.mail_subject or "",
            mail_date=row.mail_date,
            match_confidence=row.match_confidence or "",
            match_reason=row.match_reason or "",
            verdict=row.verdict,
            quote=row.quote or "",
            round_label=row.round_label,
            status=row.status,
        )


class InboxSettingsOut(BaseModel):
    """Whether the sync can run at all, and over what."""

    enabled: bool
    folder: str
    since_days: int
    blocker: str


# --------------------------------------------------------------------------- #
# Orchestration (Phase 8)
# --------------------------------------------------------------------------- #
class TaskOut(BaseModel):
    """A queued/running/finished background task."""

    id: str
    kind: str
    label: str
    job_id: str | None = None
    status: str  # queued | running | done | failed
    progress: str = ""
    result: dict = {}
    error: str | None = None
    #: Exception class name — lets the UI treat a guardrail violation (the agent
    #: tried to claim something untrue) differently from a build or network fault.
    error_kind: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class RunOut(BaseModel):
    """One persisted run from the ``runs`` table."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    started_at: datetime | None
    finished_at: datetime | None
    stats: dict = {}
    # How many jobs this crawl actually put in the database, counted from the
    # jobs themselves rather than trusted from the run's own stats blob.
    job_count: int = 0


class SettingsIn(BaseModel):
    """Partial settings patch. Only the sections present are touched, so the
    Settings page can save one card without clobbering the rest."""

    app: dict | None = None
    crawl: dict | None = None
    apply: dict | None = None
    cv: dict | None = None
    sources: list[dict] | None = None
    #: Which model runs which task. Patchable so the backend can be switched from
    #: the dashboard: choosing a model is a decision you make while looking at
    #: what it costs, and that is a different room from a text editor.
    llm: dict | None = None


class ReviewOut(BaseModel):
    """What the CV Review page reads. All tailor fields are null before the first
    round, so the page can render an untailored job without special-casing."""

    job_id: str
    version: int
    author: str | None
    created_at: datetime | None
    match_score: float | None = None
    pages: int | None = None
    round: int = 0
    instruction: str | None = None
    plan: dict | None = None
    diff: dict | None = None
    gaps: list[dict] = []


class CrawlRequest(BaseModel):
    """One crawl's scope. Every field is optional and applies to this run only —
    nothing here is written back to config, so narrowing a single crawl can't
    quietly become the new default."""

    query: str | None = None
    # Subset of the sources enabled in Settings. None = all of them.
    sources: list[str] | None = None
    limit: int | None = Field(None, ge=1, le=200, description="jobs per site")
    no_robots: bool = False
