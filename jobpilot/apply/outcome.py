"""What happened after the application went out.

Phase 15 taught the board to ask "should I nudge this?". This module is where
the answer goes. Six things can happen to an application that actually left the
machine:

===========  ==============================================================
replied      A human answered. The silence is over, whatever comes next.
interview    You're talking to them. Recorded once per round, with a label,
             because "reached interview" and "reached the third round" are
             different facts about the same application.
offer        They said yes.
rejected     They said no.
withdrawn    You said no, or took something else.
ghosted      Nobody ever answered and you're calling it. **You** call it —
             the system never decides this on a timer. A silence you have
             not given up on is not the same as a rejection, and only you
             know which one you're living in.
===========  ==============================================================

Three decisions worth defending.

**Only real applications get outcomes.** A ``dry_run`` sent nothing, so there is
nobody who could reply; a ``failed`` dispatch never reached them either.
Recording "rejected" against either would corrupt the exact denominator Phase 20
is going to divide by, so both are refused rather than quietly allowed.

**Any outcome ends the follow-up cadence.** The cadence exists to chase silence.
Once anything at all is known — even a rejection — there is nothing left to
chase, and a reminder to nudge a company that already said no is the kind of
prompt that makes a person stop trusting the tool.

**Nothing is deleted.** A mis-click is retracted, not removed: ``outcome_stage``
rewinds to the previous live event, and the retracted row stays in the log. The
append-only history is what makes "rejected after two interviews" legible later,
and an edit that erases its own tracks would take that away.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

#: ``SENT_RESULTS`` is imported rather than restated: "which results mean
#: something really went out" is one rule, and two copies of it would drift the
#: first time a new result value appears.
from jobpilot.apply.followup import DONE, SENT_RESULTS
from jobpilot.timeutil import VN_TZ, vn_now

REPLIED = "replied"
INTERVIEW = "interview"
OFFER = "offer"
REJECTED = "rejected"
WITHDRAWN = "withdrawn"
GHOSTED = "ghosted"

#: Every outcome the API will accept. Kept in one place so the Pydantic literal,
#: the stats route and the UI copy can't drift apart.
ALL_OUTCOMES: tuple[str, ...] = (REPLIED, INTERVIEW, OFFER, REJECTED, WITHDRAWN, GHOSTED)

#: Outcomes after which nothing more is expected to happen on its own.
TERMINAL = frozenset({OFFER, REJECTED, WITHDRAWN, GHOSTED})

#: Outcomes that mean a human on their side actually responded. ``withdrawn``
#: and ``ghosted`` are absent on purpose: you decided those, they didn't.
ANSWERED_BY = frozenset({REPLIED, INTERVIEW, OFFER, REJECTED})

#: The column is VARCHAR(128) and Postgres enforces that while SQLite shrugs.
#: Phase 19 will feed labels straight from mail subject lines, so the clamp goes
#: here rather than being discovered on the first real inbox sync.
MAX_LABEL = 128


class OutcomeRefused(RuntimeError):
    """The application can't carry an outcome — a dry run, or a failed send."""


def describe(event_type: str | None) -> str:
    """What the board should say about this outcome, in the second person."""
    return {
        REPLIED: "They answered. No more follow-ups needed.",
        INTERVIEW: "You're talking to them.",
        OFFER: "They made an offer.",
        REJECTED: "They passed.",
        WITHDRAWN: "You withdrew this one.",
        GHOSTED: "No answer, and you've called it.",
    }.get(event_type or "", "")


def is_outcome(event_type: str | None) -> bool:
    return event_type in ALL_OUTCOMES


def _aware(value: datetime) -> datetime:
    """Assume a naive timestamp is already local, which is how they're stored.

    SQLite hands back naive datetimes where Postgres returns aware ones, so a
    raw comparison raises on one backend and works on the other — a difference
    that only surfaces wherever the tests aren't looking. Same guard as
    ``followup._aware``.
    """
    return value if value.tzinfo else value.replace(tzinfo=VN_TZ)


def _clamp(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    return text[:limit]


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def record_outcome(
    db,
    application_id: int,
    event_type: str,
    *,
    occurred_at: datetime | None = None,
    label: str | None = None,
    notes: str | None = None,
):
    """Append one event, update the denormalized stage, end the follow-ups.

    Returns ``(event, application)``, or ``(None, None)`` when there is no such
    application so the caller can raise its own 404. Raises
    :class:`OutcomeRefused` when the application never actually went out, and
    ``ValueError`` on an unknown ``event_type`` — the API validates first, but a
    CLI or a later phase calling in directly should not be able to write a value
    the stats route doesn't know how to count.
    """
    from jobpilot.store.models import Application, ApplicationEvent

    if not is_outcome(event_type):
        raise ValueError(f"unknown outcome: {event_type!r}")

    app = db.get(Application, application_id)
    if app is None:
        return None, None
    if app.result not in SENT_RESULTS:
        raise OutcomeRefused(
            f"this application has result={app.result!r} — nothing left the machine, "
            "so there is nobody who could have answered"
        )

    event = ApplicationEvent(
        application_id=app.id,
        event_type=event_type,
        occurred_at=_aware(occurred_at or vn_now()),
        label=_clamp(label, MAX_LABEL),
        notes=_clamp(notes, 100_000),
        # Remember what this event is about to overwrite, so retracting it can
        # hand the cadence back exactly rather than guessing at it.
        prev_followup_stage=app.followup_stage,
        prev_followup_at=app.next_followup_at,
    )
    db.add(event)
    app.outcome_stage = event_type
    # Not a call into followup.stop_followups: that one commits, and this whole
    # write has to land or not land together.
    app.followup_stage = DONE
    app.next_followup_at = None
    db.commit()
    db.refresh(event)
    return event, app


def retract_outcome_event(db, application_id: int, event_id: int):
    """Undo a mis-click: mark the event retracted, rewind ``outcome_stage``.

    Returns the application, or ``None`` when the event doesn't exist or belongs
    to a different application — the caller turns that into a 404. Retracting an
    already-retracted event is a no-op that still recomputes, so a double click
    can't leave the stage pointing at a dead row.
    """
    from jobpilot.store.models import Application, ApplicationEvent

    event = db.get(ApplicationEvent, event_id)
    if event is None or event.application_id != application_id:
        return None
    app = db.get(Application, application_id)
    if app is None:
        return None

    event.is_retracted = True
    db.flush()
    app.outcome_stage = _latest_live_stage(db, application_id)

    if app.outcome_stage is None:
        # Every outcome has been taken back, so the reason the cadence stopped
        # is gone too — hand it back where it was.
        stopper = _last_stopping_event(db, application_id)
        if stopper is not None:
            app.followup_stage = stopper.prev_followup_stage
            app.next_followup_at = stopper.prev_followup_at
    db.commit()
    return app


def _last_stopping_event(db, application_id: int):
    """The most recent event that actually silenced the follow-up cadence.

    Most events don't: recording a second interview round on an application
    whose cadence is already ``done`` changes nothing, and its ``prev_`` fields
    say ``done`` to prove it. Restoring from one of those would hand back
    "already finished".

    Nor is it simply the first event ever recorded. You can retract a mis-click,
    get the reminder back, actually send the nudge — advancing to
    ``second_nudge`` — and only then record a real outcome. Anchoring on the
    first event would rewind past the nudge you really sent and tell you to
    chase a company you already chased. The event that matters is the newest one
    that found the cadence alive.
    """
    from jobpilot.store.models import ApplicationEvent

    stmt = (
        select(ApplicationEvent)
        .where(ApplicationEvent.application_id == application_id)
        .where(ApplicationEvent.prev_followup_stage.is_distinct_from(DONE))
        .order_by(ApplicationEvent.id.desc())
        .limit(1)
    )
    return db.scalar(stmt)


def _latest_live_stage(db, application_id: int) -> str | None:
    """The event that should be showing on the card, or None if none are left.

    Ordered by ``id``, not ``occurred_at``: back-dating a correction should not
    make it win over what you recorded afterwards, and two events on the same
    day would otherwise tie.
    """
    from jobpilot.store.models import ApplicationEvent

    stmt = (
        select(ApplicationEvent.event_type)
        .where(ApplicationEvent.application_id == application_id)
        .where(ApplicationEvent.is_retracted.is_(False))
        .order_by(ApplicationEvent.id.desc())
        .limit(1)
    )
    return db.scalar(stmt)


def list_outcome_events(db, application_id: int) -> list:
    """The whole history, oldest first, retracted entries included.

    Retracted rows are returned rather than filtered: the card shows them struck
    through, and hiding them would make "why did the stage change back?"
    unanswerable from the UI.
    """
    from jobpilot.store.models import ApplicationEvent

    stmt = (
        select(ApplicationEvent)
        .where(ApplicationEvent.application_id == application_id)
        .order_by(ApplicationEvent.id.asc())
    )
    return list(db.scalars(stmt))


# --------------------------------------------------------------------------- #
# Aggregates
# --------------------------------------------------------------------------- #
def outcome_counts(db) -> dict:
    """The numbers behind the dashboard, counted two different ways.

    ``current`` is what the board is showing: one bucket per application, keyed
    on its latest live event. ``reached`` is how many applications ever touched
    each stage, counted from the event log.

    They have to be separate. An application that interviewed twice and was then
    rejected shows up in ``current`` only as ``rejected`` — count interviews that
    way and the interview rate silently reports the applications that are *stuck*
    in interviews rather than the ones that *got* one. ``reached`` is the honest
    numerator; ``current`` is only for rendering.

    Rates are ``None``, never ``0.0``, when the denominator is zero. A reply rate
    of "0%" from zero applications is a claim about the world; "—" is the truth.
    """
    from sqlalchemy import distinct, func

    from jobpilot.store.models import Application, ApplicationEvent

    real = Application.result.in_(tuple(SENT_RESULTS))

    total_real = db.scalar(select(func.count()).select_from(Application).where(real)) or 0

    current = {name: 0 for name in ALL_OUTCOMES}
    no_outcome = 0
    for stage, n in db.execute(
        select(Application.outcome_stage, func.count())
        .where(real)
        .group_by(Application.outcome_stage)
    ).all():
        if stage in current:
            current[stage] = n
        elif stage is None:
            no_outcome = n

    reached = {name: 0 for name in ALL_OUTCOMES}
    rows = db.execute(
        select(ApplicationEvent.event_type, func.count(distinct(ApplicationEvent.application_id)))
        .join(Application, Application.id == ApplicationEvent.application_id)
        .where(real)
        .where(ApplicationEvent.is_retracted.is_(False))
        .group_by(ApplicationEvent.event_type)
    ).all()
    for event_type, n in rows:
        if event_type in reached:
            reached[event_type] = n

    # An interview *is* a reply, even when the reply itself was never recorded —
    # nobody types "they replied" and then "they invited me" for the same email.
    # Without this, inviting someone to interview would lower the reply rate.
    #
    # It has to be its own COUNT DISTINCT, not a max() over the buckets above.
    # Those buckets are per-event-type, so one application that emailed back and
    # another that phoned straight to an interview give ``{replied: 1,
    # interview: 1}`` — and ``max`` reads that as one answered application when
    # it is two. The bug hid behind single-application tests, where max happens
    # to be right.
    answered = (
        db.scalar(
            select(func.count(distinct(ApplicationEvent.application_id)))
            .join(Application, Application.id == ApplicationEvent.application_id)
            .where(real)
            .where(ApplicationEvent.is_retracted.is_(False))
            .where(ApplicationEvent.event_type.in_(ANSWERED_BY))
        )
        or 0
    )

    return {
        "total_real": total_real,
        "no_outcome": no_outcome,
        "current": current,
        "reached": reached,
        "answered": answered,
        "reply_rate": _rate(answered, total_real),
        "interview_rate": _rate(reached[INTERVIEW], total_real),
        "offer_rate": _rate(reached[OFFER], reached[INTERVIEW]),
    }


def _rate(numerator: int, denominator: int) -> float | None:
    """None when there is nothing to divide by — see ``outcome_counts``."""
    if not denominator:
        return None
    return round(numerator / denominator, 4)
