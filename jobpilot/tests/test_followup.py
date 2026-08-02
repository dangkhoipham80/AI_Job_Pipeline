"""The follow-up cadence.

Applications don't usually get rejected; they get forgotten. These pin the two
decisions that make the reminder trustworthy: nothing is ever sent
automatically, and a dry run is owed nothing at all.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from jobpilot.apply.followup import (
    DONE,
    FIRST_NUDGE,
    SECOND_NUDGE,
    add_business_days,
    advance,
    describe,
    due_applications,
    first_step,
    is_due,
    mark_followed_up,
    stop_followups,
)
from jobpilot.store.models import Application, Job, JobStatus
from jobpilot.timeutil import VN_TZ

# A Wednesday, so weekend arithmetic actually gets exercised.
NOW = datetime(2026, 8, 5, 9, 0, tzinfo=VN_TZ)


# --------------------------------------------------------------------------- #
# the schedule
# --------------------------------------------------------------------------- #
def test_business_days_skip_the_weekend():
    """A nudge that lands on Sunday is read on Monday, in a worse mood."""
    thursday = datetime(2026, 8, 6, 9, 0, tzinfo=VN_TZ)
    assert thursday.weekday() == 3
    landed = add_business_days(thursday, 5)
    assert landed.weekday() < 5
    assert landed == datetime(2026, 8, 13, 9, 0, tzinfo=VN_TZ)  # the next Thursday


def test_a_sent_application_starts_the_clock():
    step = first_step("success", sent_at=NOW)
    assert step.stage == FIRST_NUDGE
    assert step.due_at is not None and step.due_at > NOW


def test_awaiting_user_also_starts_the_clock():
    """Portal and external applications are still applications — you submitted
    them yourself, and they go just as quiet."""
    assert first_step("awaiting_user", sent_at=NOW).stage == FIRST_NUDGE


def test_a_dry_run_is_owed_nothing():
    """Nothing left the machine, so there is nobody to chase. NULL says that
    more honestly than a date already in the past."""
    step = first_step("dry_run", sent_at=NOW)
    assert step.stage == DONE
    assert step.due_at is None
    assert step.finished is True


def test_a_failed_application_is_owed_nothing_either():
    assert first_step("failed", sent_at=NOW).due_at is None


def test_the_cadence_is_finite():
    """Two unanswered notes is an answer."""
    second = advance(FIRST_NUDGE, now=NOW)
    assert second.stage == SECOND_NUDGE and second.due_at is not None

    end = advance(SECOND_NUDGE, now=NOW)
    assert end.stage == DONE and end.due_at is None
    # And it stays ended, however many times you ask.
    assert advance(DONE, now=NOW).stage == DONE
    assert advance(None, now=NOW).stage == DONE


def test_due_compares_a_naive_timestamp_without_blowing_up():
    """SQLite hands back naive datetimes where Postgres returns aware ones, so
    comparing them raw raises on one backend and passes on the other."""
    naive_past = datetime(2020, 1, 1, 0, 0)
    assert is_due(naive_past, now=NOW) is True
    assert is_due(None, now=NOW) is False
    assert is_due(NOW + timedelta(days=1), now=NOW) is False


def test_every_stage_says_what_to_actually_do():
    for stage in (FIRST_NUDGE, SECOND_NUDGE, DONE):
        assert len(describe(stage)) > 20
    assert describe(None) == ""


# --------------------------------------------------------------------------- #
# through the database
# --------------------------------------------------------------------------- #
def _seed(db, *, due_at, stage=FIRST_NUDGE) -> Application:
    db.add(
        Job(
            id="x:1",
            source="x",
            url="u",
            title="Java Backend Engineer",
            company="ACME",
            status=JobStatus.SUBMITTED,
            match_score=1.0,
        )
    )
    app = Application(
        job_id="x:1",
        channel="email",
        result="success",
        next_followup_at=due_at,
        followup_stage=stage,
    )
    db.add(app)
    db.commit()
    return app


def test_only_applications_that_have_come_due_are_listed(session_factory):
    with session_factory() as db:
        _seed(db, due_at=NOW - timedelta(days=1))
        assert len(due_applications(db, now=NOW)) == 1

    with session_factory() as db:
        for app in db.query(Application):
            app.next_followup_at = NOW + timedelta(days=3)
        db.commit()
        assert due_applications(db, now=NOW) == []


def test_marking_one_done_advances_then_ends_the_cadence(session_factory):
    with session_factory() as db:
        app = _seed(db, due_at=NOW - timedelta(days=1))

        second = mark_followed_up(db, app.id, now=NOW)
        assert second.followup_stage == SECOND_NUDGE
        assert second.next_followup_at is not None

        ended = mark_followed_up(db, app.id, now=NOW)
        assert ended.followup_stage == DONE
        assert ended.next_followup_at is None
        assert due_applications(db, now=NOW) == []


def test_you_can_let_one_go_at_any_point(session_factory):
    with session_factory() as db:
        app = _seed(db, due_at=NOW - timedelta(days=1))
        stopped = stop_followups(db, app.id)
        assert stopped.followup_stage == DONE
        assert stopped.next_followup_at is None


def test_unknown_application_ids_are_not_an_error(session_factory):
    with session_factory() as db:
        assert mark_followed_up(db, 4242) is None
        assert stop_followups(db, 4242) is None
