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

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from jobpilot.apply.followup import first_step
from jobpilot.apply.email import EmailError, OutgoingEmail, build_email, recipient_of, send_email
from jobpilot.apply.letter import LetterEngine
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


def apply_job(
    db: Session,
    job_id: str,
    letter_engine: LetterEngine | None = None,
) -> ApplyOutcome:
    """Dispatch one application. Raises ``ApplyRefused`` for bad state."""
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

    cfg = get_config()
    channel = resolve_channel(job)
    run = Run(kind="apply", started_at=vn_now())
    db.add(run)
    job.status = JobStatus.SUBMITTING
    db.commit()

    letter_path: Path | None = None
    letter_text = ""
    if letter_engine is not None:
        try:
            master = cv_store.get_document(db, cv_store.MASTER_SCOPE)
            result = letter_engine.write(master, job, latest_plan(db, job_id))
            letter_text = result.letter.body()
            letter_path = _write_letter(job_id, letter_text)
        except (TailorError, GuardrailViolation) as exc:
            return _fail(db, run, job, channel, cv_pdf, f"cover letter: {exc}")

    if channel == EMAIL:
        return _apply_email(db, run, job, cfg, cv_pdf, letter_path, letter_text)
    return _apply_handoff(db, run, job, channel, cv_pdf, letter_path, letter_text)


# --------------------------------------------------------------------------- #
# Channels
# --------------------------------------------------------------------------- #
def _apply_email(db, run, job, cfg, cv_pdf, letter_path, letter_text) -> ApplyOutcome:
    master = cv_store.get_document(db, cv_store.MASTER_SCOPE)
    name = " ".join(p for p in (master.header.first_name, master.header.last_name) if p).title()
    subject = cfg.apply.email.subject_template.format(
        title=job.title, name=name, company=job.company
    )

    try:
        email = build_email(
            cfg=cfg.apply,
            to=job.apply_target or "",
            subject=subject,
            body=letter_text
            or f"Dear Hiring Team at {job.company},\n\nPlease find my CV attached.",
            attachments=[cv_pdf],
        )
    except EmailError as exc:
        return _fail(db, run, job, EMAIL, cv_pdf, str(exc), letter_path)

    if email.dry_run:
        # Nothing left the machine, so the job has not been submitted.
        app = _record(
            db, job, EMAIL, cv_pdf, letter_path, result="dry_run", meta={"email": email.summary()}
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
            db, run, job, EMAIL, cv_pdf, str(exc), letter_path, meta={"email": email.summary()}
        )

    app = _record(
        db,
        job,
        EMAIL,
        cv_pdf,
        letter_path,
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


def _apply_handoff(db, run, job, channel, cv_pdf, letter_path, letter_text) -> ApplyOutcome:
    master = cv_store.get_document(db, cv_store.MASTER_SCOPE)
    handoff = prepare_handoff(
        url=job.apply_target or job.url,
        master=master,
        cv_path=cv_pdf,
        cover_letter=letter_text,
    )
    app = _record(
        db,
        job,
        channel,
        cv_pdf,
        letter_path,
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
    letter_path: Path | None,
    *,
    result: str,
    submitted: bool = False,
    meta: dict | None = None,
    error: str | None = None,
) -> Application:
    # An application that really went out starts its follow-up clock here. A dry
    # run does not: there is nobody to chase about a message that never left.
    step = first_step(result)
    app = Application(
        job_id=job.id,
        cv_pdf_path=str(cv_pdf),
        cover_letter_path=str(letter_path) if letter_path else None,
        channel=channel,
        result=result,
        error_msg=error,
        submitted_at=vn_now() if submitted else None,
        meta=meta or {},
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
    db, run, job, channel, cv_pdf, reason, letter_path=None, meta: dict | None = None
) -> ApplyOutcome:
    app = _record(db, job, channel, cv_pdf, letter_path, result="failed", error=reason, meta=meta)
    job.status = JobStatus.FAILED
    _finish(db, run, {"job_id": job.id, "channel": channel, "result": "failed", "error": reason})
    db.commit()
    return ApplyOutcome(
        job_id=job.id, channel=channel, result="failed", detail=reason, application_id=app.id
    )
