"""What happened after the application went out (Phase 18).

These pin the three decisions that make the numbers worth reading: only real
applications can carry an outcome, any outcome ends the follow-up cadence, and
a mis-click is retracted rather than deleted — with the history left behind to
explain why the stage moved back.

The last group is the one that matters most. ``outcome_stage`` alone cannot tell
"rejected after two interviews" apart from "rejected on day one", so the rates
are counted from the event log instead, and there is a test here that fails if
anyone ever simplifies that back.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from jobpilot.apply.followup import DONE, FIRST_NUDGE, SECOND_NUDGE, mark_followed_up
from jobpilot.apply.outcome import (
    GHOSTED,
    INTERVIEW,
    OFFER,
    REJECTED,
    REPLIED,
    WITHDRAWN,
    MAX_LABEL,
    OutcomeRefused,
    describe,
    list_outcome_events,
    outcome_counts,
    record_outcome,
    retract_outcome_event,
)
from jobpilot.store.models import Application, ApplicationEvent, Job, JobStatus
from jobpilot.timeutil import VN_TZ

NOW = datetime(2026, 8, 5, 9, 0, tzinfo=VN_TZ)


def _at(value):
    """Force +07 before comparing: SQLite drops the offset on read-back where
    Postgres keeps it, so a raw ``==`` passes on one backend and fails on the
    other (same trap as ``followup._aware``)."""
    return None if value is None else value.replace(tzinfo=VN_TZ)


def _seed(db, *, result="success", job_id="x:1", stage=FIRST_NUDGE) -> Application:
    if db.get(Job, job_id) is None:
        db.add(
            Job(
                id=job_id,
                source="x",
                url="u",
                title="Java Backend Engineer",
                company="ACME",
                status=JobStatus.SUBMITTED,
                match_score=1.0,
            )
        )
    app = Application(
        job_id=job_id,
        channel="email",
        result=result,
        submitted_at=NOW - timedelta(days=10),
        next_followup_at=NOW - timedelta(days=1),
        followup_stage=stage,
    )
    db.add(app)
    db.commit()
    return app


# --------------------------------------------------------------------------- #
# recording
# --------------------------------------------------------------------------- #
def test_a_reply_ends_the_chasing(session_factory):
    """The cadence exists to chase silence. Once anything is known there is
    nothing left to chase, and nudging a company that already answered is how a
    prompt loses its credibility."""
    with session_factory() as db:
        app = _seed(db)
        event, updated = record_outcome(db, app.id, REPLIED)

        assert event.event_type == REPLIED
        assert updated.outcome_stage == REPLIED
        assert updated.followup_stage == DONE
        assert updated.next_followup_at is None


def test_a_rejection_ends_it_too(session_factory):
    """Even bad news is news — there is nobody left to nudge."""
    with session_factory() as db:
        app = _seed(db)
        _, updated = record_outcome(db, app.id, REJECTED)
        assert updated.next_followup_at is None


def test_an_interview_round_keeps_its_label(session_factory):
    with session_factory() as db:
        app = _seed(db)
        event, updated = record_outcome(db, app.id, INTERVIEW, label="Round 1 — Technical")
        assert event.label == "Round 1 — Technical"
        assert updated.outcome_stage == INTERVIEW


def test_every_round_is_its_own_event(session_factory):
    """ "Reached interview" and "reached the third round" are different facts
    about the same application, and only the log can tell them apart."""
    with session_factory() as db:
        app = _seed(db)
        record_outcome(db, app.id, INTERVIEW, label="Round 1")
        record_outcome(db, app.id, INTERVIEW, label="Round 2")

        events = list_outcome_events(db, app.id)
        assert [e.label for e in events] == ["Round 1", "Round 2"]
        assert db.get(Application, app.id).outcome_stage == INTERVIEW


def test_a_dry_run_cannot_have_an_outcome(session_factory):
    """Nothing left the machine, so nobody could have answered. Allowing this
    would corrupt the exact denominator the dashboard divides by."""
    with session_factory() as db:
        app = _seed(db, result="dry_run")
        with pytest.raises(OutcomeRefused):
            record_outcome(db, app.id, REPLIED)


def test_a_failed_dispatch_cannot_either(session_factory):
    with session_factory() as db:
        app = _seed(db, result="failed")
        with pytest.raises(OutcomeRefused):
            record_outcome(db, app.id, REJECTED)


def test_an_unknown_application_is_not_an_error(session_factory):
    """The caller turns this into its own 404 — raising here would make a
    missing row indistinguishable from a refused one."""
    with session_factory() as db:
        assert record_outcome(db, 9999, REPLIED) == (None, None)


def test_an_unknown_outcome_is_refused(session_factory):
    """The API validates first, but a CLI calling in directly must not be able
    to write a value the stats route doesn't know how to count."""
    with session_factory() as db:
        app = _seed(db)
        with pytest.raises(ValueError):
            record_outcome(db, app.id, "maybe")


def test_a_naive_timestamp_is_not_quietly_shifted(session_factory):
    """A naive input is local time and must stay on the wall clock it arrived on.

    Note what this asserts *around*. SQLite drops the offset when the row is read
    back, so ``occurred_at`` returns naive here and aware on Postgres — the same
    split ``followup._aware`` exists for, and the reason nothing downstream
    compares these raw. What has to hold on both backends is that 09:00 typed in
    is still 09:00 read out, rather than 09:00 UTC landing as 16:00 local.
    """
    with session_factory() as db:
        app = _seed(db)
        event, _ = record_outcome(db, app.id, REPLIED, occurred_at=datetime(2026, 8, 1, 9, 0))
        stored = event.occurred_at
        assert (stored.day, stored.hour) == (1, 9)
        assert stored.replace(tzinfo=VN_TZ) == datetime(2026, 8, 1, 9, 0, tzinfo=VN_TZ)


def test_a_long_label_is_clamped_not_rejected(session_factory):
    """Postgres enforces VARCHAR(128) and SQLite shrugs, so a label pasted from
    a mail subject in Phase 19 would only blow up in production."""
    with session_factory() as db:
        app = _seed(db)
        event, _ = record_outcome(db, app.id, INTERVIEW, label="R" * 400)
        assert len(event.label) == MAX_LABEL


def test_occurred_at_can_be_backdated(session_factory):
    """A reply you type in on Friday may have arrived on Tuesday, and
    time-to-reply should believe you rather than the clock."""
    with session_factory() as db:
        app = _seed(db)
        event, _ = record_outcome(db, app.id, REPLIED, occurred_at=NOW - timedelta(days=4))
        # Forced onto +07 on both sides first: on SQLite these come back naive,
        # on Postgres aware, and comparing them raw raises on exactly one of them.
        occurred = event.occurred_at.replace(tzinfo=VN_TZ)
        recorded = event.recorded_at.replace(tzinfo=VN_TZ)
        assert occurred < recorded


def test_each_outcome_says_what_it_means():
    for name in (REPLIED, INTERVIEW, OFFER, REJECTED, GHOSTED):
        assert len(describe(name)) > 10
    assert describe(None) == ""


# --------------------------------------------------------------------------- #
# retracting
# --------------------------------------------------------------------------- #
def test_retracting_the_only_event_clears_the_stage(session_factory):
    with session_factory() as db:
        app = _seed(db)
        event, _ = record_outcome(db, app.id, REPLIED)

        updated = retract_outcome_event(db, app.id, event.id)
        assert updated.outcome_stage is None
        assert list_outcome_events(db, app.id)[0].is_retracted is True


def test_retracting_rewinds_to_the_previous_one(session_factory):
    with session_factory() as db:
        app = _seed(db)
        record_outcome(db, app.id, REPLIED)
        second, _ = record_outcome(db, app.id, INTERVIEW)

        updated = retract_outcome_event(db, app.id, second.id)
        assert updated.outcome_stage == REPLIED


def test_the_history_keeps_retracted_rows(session_factory):
    """Hiding them would make "why did the stage change back?" unanswerable
    from the card that shows the change."""
    with session_factory() as db:
        app = _seed(db)
        first, _ = record_outcome(db, app.id, REPLIED)
        record_outcome(db, app.id, INTERVIEW)
        retract_outcome_event(db, app.id, first.id)

        events = list_outcome_events(db, app.id)
        assert len(events) == 2
        assert [e.is_retracted for e in events] == [True, False]
        # The live event still wins even though an older one was retracted.
        assert db.get(Application, app.id).outcome_stage == INTERVIEW


def test_retracting_someone_elses_event_does_nothing(session_factory):
    with session_factory() as db:
        mine = _seed(db)
        theirs = _seed(db, job_id="x:2")
        event, _ = record_outcome(db, theirs.id, OFFER)

        assert retract_outcome_event(db, mine.id, event.id) is None
        assert db.get(ApplicationEvent, event.id).is_retracted is False


def test_taking_back_every_outcome_gives_the_reminder_back(session_factory):
    """Otherwise a mis-click costs you the follow-up permanently.

    Recording an outcome stops the cadence, which is right — but if you then
    retract the whole thing, the application is back to "no idea what happened"
    with its reminder switched off and no way to ask for it back. The board
    would go quiet about an application that has never actually been answered.
    """
    with session_factory() as db:
        app = _seed(db)  # seeded mid-cadence: first_nudge, due yesterday
        due_before, stage_before = app.next_followup_at, app.followup_stage

        event, updated = record_outcome(db, app.id, REJECTED)
        assert updated.followup_stage == DONE and updated.next_followup_at is None

        restored = retract_outcome_event(db, app.id, event.id)
        assert restored.outcome_stage is None
        assert restored.followup_stage == stage_before
        assert _at(restored.next_followup_at) == _at(due_before)


def test_the_cadence_stays_stopped_while_any_outcome_stands(session_factory):
    """Retracting one of several is a correction, not a reopening — there is
    still an outcome on the record, so there is still nothing to chase."""
    with session_factory() as db:
        app = _seed(db)
        record_outcome(db, app.id, REPLIED)
        second, _ = record_outcome(db, app.id, INTERVIEW)

        updated = retract_outcome_event(db, app.id, second.id)
        assert updated.outcome_stage == REPLIED
        assert updated.followup_stage == DONE
        assert updated.next_followup_at is None


def test_the_restore_ignores_events_that_stopped_nothing(session_factory):
    """A second outcome found the cadence already stopped — its ``prev_`` fields
    say ``done``, and restoring from it would hand back "already finished"
    instead of "still owed a nudge"."""
    with session_factory() as db:
        app = _seed(db)
        due_before = app.next_followup_at
        first, _ = record_outcome(db, app.id, REPLIED)
        second, _ = record_outcome(db, app.id, INTERVIEW)
        assert second.prev_followup_stage == DONE  # the trap this test guards

        retract_outcome_event(db, app.id, second.id)
        restored = retract_outcome_event(db, app.id, first.id)
        assert restored.followup_stage == FIRST_NUDGE
        assert _at(restored.next_followup_at) == _at(due_before)


def test_a_nudge_you_really_sent_survives_a_later_mistake(session_factory):
    """The reason the anchor isn't just "the first event ever recorded".

    Retract a mis-click, get the reminder back, actually send the nudge — you
    are now at ``second_nudge``. Record a real outcome, then take that back too.
    Rewinding to the first event would put you back at ``first_nudge`` and tell
    you to chase a company you already chased; the cadence would also gain a
    third nudge it was designed never to have.
    """
    with session_factory() as db:
        app = _seed(db)
        mistake, _ = record_outcome(db, app.id, REPLIED)
        retract_outcome_event(db, app.id, mistake.id)
        mark_followed_up(db, app.id, now=NOW)
        assert db.get(Application, app.id).followup_stage == SECOND_NUDGE

        real, _ = record_outcome(db, app.id, INTERVIEW)
        assert real.prev_followup_stage == SECOND_NUDGE

        restored = retract_outcome_event(db, app.id, real.id)
        assert restored.followup_stage == SECOND_NUDGE


def test_retracting_out_of_order_still_restores(session_factory):
    """Nothing forces you to take them back newest-first."""
    with session_factory() as db:
        app = _seed(db)
        due_before = app.next_followup_at
        first, _ = record_outcome(db, app.id, REPLIED)
        second, _ = record_outcome(db, app.id, INTERVIEW)

        retract_outcome_event(db, app.id, first.id)  # oldest first
        mid = db.get(Application, app.id)
        assert mid.outcome_stage == INTERVIEW and mid.followup_stage == DONE

        restored = retract_outcome_event(db, app.id, second.id)
        assert restored.outcome_stage is None
        assert restored.followup_stage == FIRST_NUDGE
        assert _at(restored.next_followup_at) == _at(due_before)


def test_a_dry_run_has_no_cadence_to_restore(session_factory):
    """It was never owed a follow-up, so taking an outcome back must not invent
    one. (It can't get an outcome in the first place — this pins the pairing.)"""
    with session_factory() as db:
        app = _seed(db, result="dry_run", stage=None)
        app.next_followup_at = None
        db.commit()
        with pytest.raises(OutcomeRefused):
            record_outcome(db, app.id, REPLIED)
        assert db.get(Application, app.id).next_followup_at is None


def test_retracting_twice_is_harmless(session_factory):
    with session_factory() as db:
        app = _seed(db)
        event, _ = record_outcome(db, app.id, REPLIED)
        retract_outcome_event(db, app.id, event.id)
        again = retract_outcome_event(db, app.id, event.id)
        assert again.outcome_stage is None


# --------------------------------------------------------------------------- #
# counting — the part that is easy to get subtly wrong
# --------------------------------------------------------------------------- #
def test_an_interview_still_counts_after_the_rejection(session_factory):
    """The whole reason there are two sets of numbers.

    An application that interviewed twice and was then rejected sits in
    ``current["rejected"]`` only. Count interviews that way and the interview
    rate silently reports the applications *stuck* in interviews instead of the
    ones that got one — a number that goes down as the search goes well.
    """
    with session_factory() as db:
        app = _seed(db)
        record_outcome(db, app.id, INTERVIEW, label="Round 1")
        record_outcome(db, app.id, REJECTED)

        counts = outcome_counts(db)
        assert counts["current"][REJECTED] == 1
        assert counts["current"][INTERVIEW] == 0
        assert counts["reached"][INTERVIEW] == 1
        assert counts["interview_rate"] == 1.0


def test_rounds_of_the_same_kind_count_the_application_once(session_factory):
    with session_factory() as db:
        app = _seed(db)
        record_outcome(db, app.id, INTERVIEW, label="Round 1")
        record_outcome(db, app.id, INTERVIEW, label="Round 2")
        assert outcome_counts(db)["reached"][INTERVIEW] == 1


def test_an_interview_invite_is_a_reply(session_factory):
    """Nobody types "they replied" and then "they invited me" for the same
    email, so without this, going to interview would lower the reply rate."""
    with session_factory() as db:
        app = _seed(db)
        record_outcome(db, app.id, INTERVIEW)
        counts = outcome_counts(db)
        assert counts["answered"] == 1
        assert counts["reply_rate"] == 1.0


def test_answered_counts_applications_not_the_biggest_bucket(session_factory):
    """Two applications answered in two different ways is still two.

    This is the shape the first implementation got wrong: it took ``max()`` over
    the per-event-type buckets. One company emails back, another phones straight
    through to an interview, and the buckets read ``{replied: 1, interview: 1}``
    — whose max is 1. The dashboard then reported a 50% reply rate for a search
    where *everyone* had replied, and it stayed hidden because every other test
    here uses a single application, where max is accidentally right.
    """
    with session_factory() as db:
        emailed_back = _seed(db)
        phoned = _seed(db, job_id="x:2")
        record_outcome(db, emailed_back.id, REPLIED)
        record_outcome(db, phoned.id, INTERVIEW)

        counts = outcome_counts(db)
        assert counts["reached"][REPLIED] == 1
        assert counts["reached"][INTERVIEW] == 1
        assert counts["answered"] == 2
        assert counts["reply_rate"] == 1.0


def test_withdrawing_is_not_an_answer(session_factory):
    """You decided that one, they didn't — counting it as a reply would flatter
    the number with your own clicks."""
    with session_factory() as db:
        app = _seed(db)
        record_outcome(db, app.id, WITHDRAWN)
        counts = outcome_counts(db)
        assert counts["answered"] == 0
        assert counts["reply_rate"] == 0.0


def test_dry_runs_are_not_in_the_denominator(session_factory):
    """They were never sent, so counting them would dilute every rate with
    applications nobody ever saw."""
    with session_factory() as db:
        real = _seed(db)
        _seed(db, result="dry_run", job_id="x:2")
        record_outcome(db, real.id, REPLIED)

        counts = outcome_counts(db)
        assert counts["total_real"] == 1
        assert counts["reply_rate"] == 1.0


def test_retracted_events_stop_counting(session_factory):
    with session_factory() as db:
        app = _seed(db)
        event, _ = record_outcome(db, app.id, INTERVIEW)
        retract_outcome_event(db, app.id, event.id)

        counts = outcome_counts(db)
        assert counts["reached"][INTERVIEW] == 0
        assert counts["no_outcome"] == 1


def test_rates_are_unknown_rather_than_zero(session_factory):
    """A reply rate of "0%" from zero applications is a claim about the world.
    None is the truth, and the dashboard renders it as a dash."""
    with session_factory() as db:
        counts = outcome_counts(db)
        assert counts["total_real"] == 0
        assert counts["reply_rate"] is None
        assert counts["offer_rate"] is None


def test_offer_rate_is_measured_against_interviews(session_factory):
    with session_factory() as db:
        got_offer = _seed(db)
        no_offer = _seed(db, job_id="x:2")
        record_outcome(db, got_offer.id, INTERVIEW)
        record_outcome(db, got_offer.id, OFFER)
        record_outcome(db, no_offer.id, INTERVIEW)
        record_outcome(db, no_offer.id, REJECTED)

        counts = outcome_counts(db)
        assert counts["reached"][INTERVIEW] == 2
        assert counts["offer_rate"] == 0.5
