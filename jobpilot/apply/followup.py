"""When to chase an application, and when to let it go.

The pipeline used to end at "submitted". That is where most applications
actually die: not rejected, just never followed up, because following up
depends on remembering — and remembering is the thing a tool like this exists
to replace.

The cadence is deliberately short and finite:

===============  ======================================================
first_nudge      ~5 business days after it went out. Long enough not to
                 look anxious, short enough that the req is still open.
second_nudge     ~7 days after the first. One more, then stop.
done             No further prompts. Two unanswered notes is an answer.
===============  ======================================================

Two decisions worth defending. **Nothing is sent automatically** — the due date
produces a prompt on the board and that is all; an email that leaves the machine
without you seeing it is exactly what principle 2 forbids, and a follow-up is a
message to a person who is deciding about you. And **a dry run is owed
nothing**: if no application left the machine there is nobody to chase, so the
date stays NULL rather than becoming a reminder about a thing that never
happened.

Business days, not calendar days: five days from Thursday is the following
Thursday, and a nudge that lands on Sunday is a nudge that gets read on Monday
in a worse mood.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from jobpilot.timeutil import VN_TZ, vn_now

#: Results that mean something really went out. `dry_run` deliberately absent.
SENT_RESULTS = frozenset({"success", "awaiting_user"})

FIRST_NUDGE = "first_nudge"
SECOND_NUDGE = "second_nudge"
DONE = "done"

#: Business days from sending to the first nudge, then to the second.
DAYS_TO_FIRST = 5
DAYS_TO_SECOND = 7


@dataclass(frozen=True)
class Step:
    """The next thing to do about an application, and when."""

    stage: str
    due_at: datetime | None

    @property
    def finished(self) -> bool:
        return self.stage == DONE


def add_business_days(start: datetime, days: int) -> datetime:
    """``start`` plus ``days``, skipping weekends.

    Calendar arithmetic would drop reminders on a Saturday, where they are
    either ignored or answered by nobody.
    """
    out = start
    remaining = days
    while remaining > 0:
        out += timedelta(days=1)
        if out.weekday() < 5:  # Mon-Fri
            remaining -= 1
    return out


def first_step(result: str | None, *, sent_at: datetime | None = None) -> Step:
    """The cadence position for an application that has just been dispatched."""
    if result not in SENT_RESULTS:
        # Nothing left the machine, so there is nobody to follow up with.
        return Step(stage=DONE, due_at=None)
    return Step(FIRST_NUDGE, add_business_days(sent_at or vn_now(), DAYS_TO_FIRST))


def advance(stage: str | None, *, now: datetime | None = None) -> Step:
    """Where the cadence goes after you've done the step it was asking for."""
    now = now or vn_now()
    if stage == FIRST_NUDGE:
        return Step(SECOND_NUDGE, add_business_days(now, DAYS_TO_SECOND))
    # Anything else — the second nudge, an unknown stage, or none at all —
    # ends the cadence. Two unanswered notes is an answer.
    return Step(DONE, None)


def is_due(next_followup_at: datetime | None, *, now: datetime | None = None) -> bool:
    """Whether the next step has come due.

    Both sides are forced onto the project's fixed +07 offset first. SQLite
    hands back naive datetimes where Postgres returns aware ones, so comparing
    them raw raises on one backend and works on the other — a difference that
    would only surface wherever the tests aren't looking.
    """
    if next_followup_at is None:
        return False
    return _aware(next_followup_at) <= _aware(now or vn_now())


def _aware(value: datetime) -> datetime:
    """Assume a naive timestamp is already local, which is how they're stored."""
    return value if value.tzinfo else value.replace(tzinfo=VN_TZ)


def describe(stage: str | None) -> str:
    """What the prompt should actually say, in the second person."""
    return {
        FIRST_NUDGE: "Send a short note asking where the application stands.",
        SECOND_NUDGE: "One last follow-up, then let this one go.",
        DONE: "No further follow-ups — this one has run its course.",
    }.get(stage or "", "")


# --------------------------------------------------------------------------- #
# Persistence — the thin layer over the two columns
# --------------------------------------------------------------------------- #
def _due_stmt(now: datetime):
    from sqlalchemy import select

    from jobpilot.store.models import Application

    return (
        select(Application)
        .where(Application.next_followup_at.is_not(None))
        .where(Application.next_followup_at <= now)
        # `id` last so the order is total: several applications scheduled by the
        # same dispatch share a `next_followup_at` to the microsecond, and ties
        # in an unstable order make LIMIT/OFFSET repeat one row and skip another.
        .order_by(Application.next_followup_at.asc(), Application.id.asc())
    )


def due_applications(
    db, *, now: datetime | None = None, limit: int | None = 50, offset: int = 0
) -> list:
    """Applications whose next follow-up has come due, oldest first.

    Only a query. Deliberately nothing is sent from here: a follow-up is a
    message to a person deciding about you, and mail that leaves the machine
    without you seeing it is what principle 2 forbids.

    ``limit=None`` means every due application — the caller that needs a count
    rather than a page.
    """
    stmt = _due_stmt(now or vn_now()).offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.scalars(stmt))


def due_count(db, *, now: datetime | None = None) -> int:
    """How many applications are due, ignoring any page window."""
    from sqlalchemy import func, select

    stmt = _due_stmt(now or vn_now()).order_by(None)
    return db.scalar(select(func.count()).select_from(stmt.subquery())) or 0


def mark_followed_up(db, application_id: int, *, now: datetime | None = None):
    """Record that you sent the nudge, and schedule (or end) the next one."""
    from jobpilot.store.models import Application

    app = db.get(Application, application_id)
    if app is None:
        return None
    step = advance(app.followup_stage, now=now)
    app.followup_stage = step.stage
    app.next_followup_at = step.due_at
    db.commit()
    return app


def stop_followups(db, application_id: int):
    """Let one go — after a reply, a rejection, or a change of heart."""
    from jobpilot.store.models import Application

    app = db.get(Application, application_id)
    if app is None:
        return None
    app.followup_stage = DONE
    app.next_followup_at = None
    db.commit()
    return app
