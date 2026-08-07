"""Apply dispatcher — routes an approved job to its channel (PLAN.md §5.4).

    APPROVED ─apply─▶ SUBMITTING ─┬─ email sent ─────────▶ SUBMITTED
                                  ├─ portal/external ────▶ (waits for the user)
                                  └─ error ──────────────▶ FAILED

Three channels, three different amounts of autonomy — deliberately:

* ``email``    full-auto, but only once every gate in ``apply.email`` is open.
               A dry run leaves the job APPROVED, because nothing was sent and
               saying SUBMITTED would be a lie.
* ``portal``   prepares a handoff package and stops. The user submits and then
               confirms, which is what moves the job to SUBMITTED.
* ``external`` same as portal, minus any pretence of automation (LinkedIn and
               friends — CLAUDE.md rule 2 forbids automating these at all).

Every path writes an ``Application`` row, so a failure is as visible on the
board as a success.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from jobpilot.apply.followup import first_step
from jobpilot.apply.email import EmailError, OutgoingEmail, build_email, recipient_of, send_email
from jobpilot.apply.letter import LetterEngine
from jobpilot.apply.letter_pdf import compile_letter
from jobpilot.apply.portal import Handoff, prepare_handoff
from jobpilot.config import get_config, get_secrets
from jobpilot.cv import store as cv_store
from jobpilot.cv.compile import build_dir
from jobpilot.store.models import Application, Job, JobStatus, Run
from jobpilot.tailor.engine import TailorError
from jobpilot.tailor.guard import GuardrailViolation
from jobpilot.tailor.service import latest_plan
from jobpilot.timeutil import vn_now

EMAIL = "email"
PORTAL = "portal"
EXTERNAL = "external"

# Applying starts from APPROVED; FAILED and SUBMITTING are included so a retry
# after a bounce or a half-finished portal run isn't a dead end.
APPLIABLE = {JobStatus.APPROVED, JobStatus.FAILED, JobStatus.SUBMITTING}


class ApplyRefused(RuntimeError):
    """The job is not in a state where applying makes sense."""


@dataclass
class LetterArtifacts:
    """What the cover letter step produced, if it ran at all.

    ``text`` is the letter; ``pdf`` is a rendering of it. They are tracked apart
    because they fail apart: the text can exist with no PDF (Docker down), and
    that is a degraded application, not a failed one. ``pdf_error`` carries the
    reason onto the Application row so "no PDF" never has to be guessed at.
    """

    text: str = ""
    txt: Path | None = None
    pdf: Path | None = None
    pdf_error: str | None = None

    def summary(self) -> dict:
        return {
            "txt": self.txt.name if self.txt else None,
            "pdf": self.pdf.name if self.pdf else None,
            "pdf_error": self.pdf_error,
        }


@dataclass
class ApplyOutcome:
    job_id: str
    channel: str
    result: str  # success | dry_run | awaiting_user | failed
    detail: str
    application_id: int | None = None
    email: OutgoingEmail | None = None
    handoff: Handoff | None = None


def resolve_channel(job: Job) -> str:
    """The channel to use: whatever the crawler recorded, else inferred."""
    declared = (job.apply_channel or "").strip().lower()
    if declared in {EMAIL, PORTAL, EXTERNAL}:
        return declared
    if recipient_of(job.apply_target):
        return EMAIL
    return PORTAL if (job.apply_target or "").startswith("http") else EXTERNAL


def cv_pdf_for(job_id: str) -> Path | None:
    pdf = build_dir(job_id) / "cv.pdf"
    return pdf if pdf.is_file() else None


def _write_letter(job_id: str, text: str) -> Path:
    path = build_dir(job_id) / "cover_letter.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def check_appliable(db: Session, job_id: str) -> tuple[Job, Path]:
    """Everything that can be refused before any slow work starts.

    The API calls this in the request so "no CV built yet" is still an immediate
    409 rather than a task that fails a minute later; ``apply_job`` calls it too,
    because the job can move between queueing and running.
    """
    job = db.get(Job, job_id)
    if job is None:
        raise ApplyRefused(f"job {job_id!r} not found")
    if job.status not in APPLIABLE:
        raise ApplyRefused(
            f"job {job_id!r} is {job.status.value}; applying starts from "
            + "/".join(sorted(s.value for s in APPLIABLE))
        )

    cv_pdf = cv_pdf_for(job_id)
    if cv_pdf is None:
        raise ApplyRefused("no tailored CV has been built for this job yet")
    return job, cv_pdf


def apply_job(
    db: Session,
    job_id: str,
    letter_engine: LetterEngine | None = None,
    progress: Callable[[str], None] | None = None,
) -> ApplyOutcome:
    """Dispatch one application. Raises ``ApplyRefused`` for bad state.

    ``progress`` names the stage, because the two slow steps have very different
    stakes: writing a cover letter is a Claude call, sending is the step that
    actually puts mail in front of an employer.
    """
    say = progress or (lambda _message: None)
    job, cv_pdf = check_appliable(db, job_id)

    cfg = get_config()
    channel = resolve_channel(job)
    run = Run(kind="apply", started_at=vn_now())
    db.add(run)
    job.status = JobStatus.SUBMITTING
    db.commit()

    letter = LetterArtifacts()
    if letter_engine is not None:
        try:
            say("writing the cover letter")
            master = cv_store.get_document(db, cv_store.MASTER_SCOPE)
            result = letter_engine.write(master, job, latest_plan(db, job_id))
            letter.text = result.letter.body()
            letter.txt = _write_letter(job_id, letter.text)
        except (TailorError, GuardrailViolation) as exc:
            return _fail(db, run, job, channel, cv_pdf, f"cover letter: {exc}")

        # The PDF is a rendering; the text is the letter. Docker being down or a
        # LaTeX error must not withhold an application whose CV already built, so
        # this failure is recorded on the row and the dispatch goes ahead.
        #
        # Deliberately broad. `BuildError` alone covers LaTeX and Docker, but the
        # same call also copies assets (OSError on a full disk or a read-only
        # dir) and renders a template (RenderError). Those escaping would leave
        # the job stuck in SUBMITTING with no error_msg — the one outcome this
        # whole branch exists to prevent. Nothing is swallowed: the type and
        # message land on the row.
        try:
            say("building the cover letter PDF")
            letter.pdf = compile_letter(result.letter, master, job, build_dir(job_id)).pdf
        except Exception as exc:
            letter.pdf_error = f"{type(exc).__name__}: {exc}"[-500:]

    say(f"dispatching via {channel}")
    if channel == EMAIL:
        return _apply_email(db, run, job, cfg, cv_pdf, letter)
    return _apply_handoff(db, run, job, channel, cv_pdf, letter)


# --------------------------------------------------------------------------- #
# Channels
# --------------------------------------------------------------------------- #
def _apply_email(db, run, job, cfg, cv_pdf, letter: LetterArtifacts) -> ApplyOutcome:
    master = cv_store.get_document(db, cv_store.MASTER_SCOPE)
    name = " ".join(p for p in (master.header.first_name, master.header.last_name) if p).title()
    subject = cfg.apply.email.subject_template.format(
        title=job.title, name=name, company=job.company
    )

    # The letter goes out twice on purpose: as the body, because that is what
    # gets read in the preview pane, and as a PDF, because that is what gets
    # filed. Attached only when it built — never a broken or stale one.
    attachments = [cv_pdf] + ([letter.pdf] if letter.pdf else [])

    try:
        email = build_email(
            cfg=cfg.apply,
            to=job.apply_target or "",
            subject=subject,
            body=letter.text
            or f"Dear Hiring Team at {job.company},\n\nPlease find my CV attached.",
            attachments=attachments,
        )
    except EmailError as exc:
        return _fail(db, run, job, EMAIL, cv_pdf, str(exc), letter)

    if email.dry_run:
        # Nothing left the machine, so the job has not been submitted.
        app = _record(
            db, job, EMAIL, cv_pdf, letter, result="dry_run", meta={"email": email.summary()}
        )
        job.status = JobStatus.APPROVED
        _finish(db, run, {"job_id": job.id, "channel": EMAIL, "result": "dry_run"})
        db.commit()
        return ApplyOutcome(
            job_id=job.id,
            channel=EMAIL,
            result="dry_run",
            detail=f"prepared for {email.intended_to} — not sent (apply.email.dry_run is on)",
            application_id=app.id,
            email=email,
        )

    try:
        detail = send_email(email, get_secrets())
    except EmailError as exc:
        return _fail(
            db, run, job, EMAIL, cv_pdf, str(exc), letter, meta={"email": email.summary()}
        )

    app = _record(
        db,
        job,
        EMAIL,
        cv_pdf,
        letter,
        result="success",
        submitted=True,
        meta={"email": email.summary()},
    )
    job.status = JobStatus.SUBMITTED
    _finish(db, run, {"job_id": job.id, "channel": EMAIL, "result": "success"})
    db.commit()
    return ApplyOutcome(
        job_id=job.id,
        channel=EMAIL,
        result="success",
        detail=detail,
        application_id=app.id,
        email=email,
    )


def _apply_handoff(db, run, job, channel, cv_pdf, letter: LetterArtifacts) -> ApplyOutcome:
    master = cv_store.get_document(db, cv_store.MASTER_SCOPE)
    handoff = prepare_handoff(
        url=job.apply_target or job.url,
        master=master,
        cv_path=cv_pdf,
        cover_letter=letter.text,
    )
    app = _record(
        db,
        job,
        channel,
        cv_pdf,
        letter,
        result="awaiting_user",
        meta={"handoff": handoff.summary()},
    )
    # Stays SUBMITTING until the user confirms they actually submitted.
    _finish(db, run, {"job_id": job.id, "channel": channel, "result": "awaiting_user"})
    db.commit()
    return ApplyOutcome(
        job_id=job.id,
        channel=channel,
        result="awaiting_user",
        detail="prepared — open the link, submit it yourself, then confirm here",
        application_id=app.id,
        handoff=handoff,
    )


# --------------------------------------------------------------------------- #
# Confirmations
# --------------------------------------------------------------------------- #
def confirm_submit(db: Session, job_id: str) -> Job:
    """The user says they submitted a portal/external application themselves."""
    job = db.get(Job, job_id)
    if job is None:
        raise ApplyRefused(f"job {job_id!r} not found")
    if job.status is not JobStatus.SUBMITTING:
        raise ApplyRefused(f"job {job_id!r} is {job.status.value}; expected SUBMITTING")

    app = _latest_application(db, job_id)
    if app is not None:
        app.result = "success"
        app.submitted_at = vn_now()
    job.status = JobStatus.SUBMITTED
    db.commit()
    return job


def mark_failed(db: Session, job_id: str, reason: str) -> Job:
    """The user reports the submission didn't go through."""
    job = db.get(Job, job_id)
    if job is None:
        raise ApplyRefused(f"job {job_id!r} not found")
    app = _latest_application(db, job_id)
    if app is not None:
        app.result = "failed"
        app.error_msg = reason
    job.status = JobStatus.FAILED
    db.commit()
    return job


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _latest_application(db: Session, job_id: str) -> Application | None:
    return (
        db.query(Application)
        .filter(Application.job_id == job_id)
        .order_by(Application.id.desc())
        .first()
    )


def _record(
    db: Session,
    job: Job,
    channel: str,
    cv_pdf: Path,
    letter: LetterArtifacts | None,
    *,
    result: str,
    submitted: bool = False,
    meta: dict | None = None,
    error: str | None = None,
) -> Application:
    # An application that really went out starts its follow-up clock here. A dry
    # run does not: there is nobody to chase about a message that never left.
    step = first_step(result)
    letter = letter or LetterArtifacts()
    app = Application(
        job_id=job.id,
        cv_pdf_path=str(cv_pdf),
        cover_letter_path=str(letter.txt) if letter.txt else None,
        cover_letter_pdf_path=str(letter.pdf) if letter.pdf else None,
        channel=channel,
        result=result,
        error_msg=error,
        submitted_at=vn_now() if submitted else None,
        meta={**(meta or {}), "letter": letter.summary()} if letter.txt else (meta or {}),
        followup_stage=step.stage,
        next_followup_at=step.due_at,
    )
    db.add(app)
    db.flush()
    return app


def _finish(db: Session, run: Run, stats: dict) -> None:
    run.finished_at = vn_now()
    run.stats = stats
    db.add(run)


def _fail(
    db, run, job, channel, cv_pdf, reason,
    letter: LetterArtifacts | None = None,
    meta: dict | None = None,
) -> ApplyOutcome:
    app = _record(db, job, channel, cv_pdf, letter, result="failed", error=reason, meta=meta)
    job.status = JobStatus.FAILED
    _finish(db, run, {"job_id": job.id, "channel": channel, "result": "failed", "error": reason})
    db.commit()
    return ApplyOutcome(
        job_id=job.id, channel=channel, result="failed", detail=reason, application_id=app.id
    )
