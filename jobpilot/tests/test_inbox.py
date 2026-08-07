"""Reading employer replies out of the mailbox (Phase 19).

Two properties matter more than everything else here and each has its own group
below. **Mail that belongs to no application never reaches the classifier** —
that ordering is the privacy design, so there is a test that fails if a private
message is ever handed to an engine. And **nothing becomes an outcome without a
person** — the sync only ever writes suggestions.

The rest pin the matcher against the headers that actually occur: recruiters
writing from gmail, subdomains, company names made entirely of words every other
company also uses.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from jobpilot.apply.inbox import (
    ACCEPTED,
    DISMISSED,
    IGNORED,
    PENDING,
    UNUSABLE,
    Applied,
    FixtureClassifier,
    MAX_KEY,
    MailVerdict,
    accept_suggestion,
    check_verdict,
    company_tokens,
    dismiss_suggestion,
    domain_of,
    mail_key,
    match_message,
    pending_suggestions,
    registrable,
    sender_address,
    sync_inbox,
)
from jobpilot.apply.outcome import OutcomeRefused, list_outcome_events
from jobpilot.crawler.mailbox import MailMessage
from jobpilot.store.models import Application, InboxSuggestion, Job, JobStatus
from jobpilot.timeutil import VN_TZ

NOW = datetime(2026, 8, 5, 9, 0, tzinfo=VN_TZ)

ACME = Applied(
    application_id=1,
    job_id="itviec:1",
    company="ACME Technology Solutions JSC",
    title="Backend Engineer",
    message_id="<sent-acme@jobpilot.local>",
    applied_to="careers@acme.com",
)
BETA = Applied(
    application_id=2,
    job_id="itviec:2",
    company="BetaCo",
    title="Java Developer",
    # Applied through a portal, so there is no thread and no address to match.
)


def mail(**kw) -> MailMessage:
    base = dict(
        uid="1",
        subject="Re: your application",
        sender="Recruiter <hr@acme.com>",
        date=NOW,
        html="",
        text="Thanks for applying.",
    )
    base.update(kw)
    return MailMessage(**base)


class FakeMailbox:
    """Hands back canned messages and remembers how it was asked."""

    def __init__(self, messages):
        self.messages = messages
        self.calls = []

    def fetch(self, senders, since_days, limit):
        self.calls.append((senders, since_days, limit))
        return self.messages[:limit]


# --------------------------------------------------------------------------- #
# reading the headers
# --------------------------------------------------------------------------- #
def test_the_address_is_pulled_out_of_a_display_name():
    assert sender_address("ACME Careers <HR@Acme.com>") == "hr@acme.com"
    assert sender_address("plain@acme.com") == "plain@acme.com"
    assert sender_address("no address here") == ""


def test_a_subdomain_still_names_the_company():
    assert registrable("careers.acme.com") == "acme"
    assert registrable("acme.co.uk") == "acme"
    assert registrable("acme.com") == "acme"
    assert domain_of("hr@acme.com") == "acme.com"


def test_company_tokens_drop_the_words_everybody_uses():
    """Matching on "solutions" would tie a reply to whichever employer happened
    to be listed first."""
    assert company_tokens("ACME Technology Solutions JSC") == {"acme"}
    assert company_tokens("Công ty TNHH Beta Vietnam") == {"beta"}
    # A name made *entirely* of noise leaves nothing to match on, which is the
    # right answer — better than matching everything.
    assert company_tokens("Technology Solutions Group") == set()


# --------------------------------------------------------------------------- #
# matching
# --------------------------------------------------------------------------- #
def test_a_threaded_reply_is_certain():
    """They quoted the Message-ID we sent. Nothing else needs checking."""
    m = mail(sender="Someone Else <anna@gmail.com>", in_reply_to="<sent-acme@jobpilot.local>")
    found = match_message(m, [ACME, BETA])
    assert found and found.application_id == 1 and found.confidence == "thread"


def test_the_thread_id_is_found_inside_a_references_chain():
    m = mail(references="<a@x.com> <sent-acme@jobpilot.local> <b@y.com>")
    found = match_message(m, [ACME])
    assert found and found.confidence == "thread"


def test_the_exact_address_we_applied_to_beats_a_domain_guess():
    found = match_message(mail(sender="careers@acme.com"), [ACME])
    assert found and found.confidence == "address"


def test_a_colleague_at_the_same_domain_still_matches():
    """The recruiter replying from her own name is the normal case."""
    found = match_message(mail(sender="Anna <anna@acme.com>"), [ACME])
    assert found and found.confidence == "domain"


def test_a_portal_application_can_only_be_matched_by_company():
    """No mail was ever sent, so there is no thread and no address — the domain
    looking like the company is all that is left, and it is marked as such."""
    found = match_message(mail(sender="talent@betaco.com"), [BETA])
    assert found and found.confidence == "company"


def test_a_recruiter_writing_from_gmail_is_not_matched_by_domain():
    """Sharing a mail host with four billion people proves nothing. The message
    can still match by thread or by the address we wrote to."""
    assert match_message(mail(sender="anna@gmail.com"), [ACME, BETA]) is None


def test_mail_that_belongs_to_nobody_is_not_matched():
    assert match_message(mail(sender="statements@mybank.com"), [ACME, BETA]) is None


def test_a_sender_with_no_address_at_all_is_skipped():
    assert match_message(mail(sender="Mailer Daemon"), [ACME, BETA]) is None


def test_an_ambiguous_message_is_dropped_rather_than_guessed():
    """Two applications at the same company, one message. A suggestion pointing
    at a coin flip is worse than no suggestion."""
    second = Applied(
        application_id=9,
        job_id="itviec:9",
        company="ACME",
        title="Data Engineer",
        applied_to="careers@acme.com",
    )
    assert match_message(mail(sender="careers@acme.com"), [ACME, second]) is None


def test_the_strongest_signal_wins_when_they_disagree():
    """A thread beats a domain, even when the domain points somewhere else."""
    other = Applied(
        application_id=7,
        job_id="itviec:7",
        company="ACME",
        title="SRE",
        applied_to="jobs@acme.com",
    )
    m = mail(sender="anna@acme.com", in_reply_to="<sent-acme@jobpilot.local>")
    found = match_message(m, [other, ACME])
    assert found and found.application_id == 1 and found.confidence == "thread"


# --------------------------------------------------------------------------- #
# the quote has to be real
# --------------------------------------------------------------------------- #
def test_a_quote_must_appear_in_the_message():
    """The card shows the sentence so you can overrule the label by reading it.
    A paraphrase would make that check impossible while looking like evidence."""
    m = mail(text="We would like to invite you to a technical interview.")
    good = MailVerdict(verdict="interview", quote="we would like to invite you")
    assert check_verdict(good, m) == []

    invented = MailVerdict(verdict="interview", quote="We loved your CV and want to hire you")
    assert "does not appear" in " ".join(check_verdict(invented, m))


def test_the_quote_match_survives_reflowed_whitespace():
    m = mail(text="We would like to invite\n   you to a  technical interview.")
    assert (
        check_verdict(MailVerdict(verdict="interview", quote="invite you to a technical"), m) == []
    )


def test_evidence_is_required_only_for_what_gets_shown():
    """Found by running a real local model: it answered `auto_ack` correctly and
    left the quote empty, and the guard filed that correct answer as a failure.

    A quote exists so you can overrule a label by reading one line. `auto_ack`
    and `unrelated` are recorded and never offered, so there is no label to
    overrule and nothing for the evidence to do.
    """
    m = mail(text="Your parcel is out for delivery.")
    assert check_verdict(MailVerdict(verdict="unrelated"), m) == []
    assert check_verdict(MailVerdict(verdict="auto_ack"), m) == []
    for shown in ("replied", "interview", "offer", "rejected"):
        assert "no supporting quote" in " ".join(check_verdict(MailVerdict(verdict=shown), m))


# --------------------------------------------------------------------------- #
# the sync
# --------------------------------------------------------------------------- #
def _seed(db, *, result="success", job_id="itviec:1", company="ACME Corp", meta=None):
    if db.get(Job, job_id) is None:
        db.add(
            Job(
                id=job_id,
                source="itviec",
                url="u",
                title="Backend Engineer",
                company=company,
                status=JobStatus.SUBMITTED,
                payload={},
            )
        )
        db.flush()
    app = Application(
        job_id=job_id,
        channel="email",
        result=result,
        submitted_at=NOW - timedelta(days=10),
        next_followup_at=NOW - timedelta(days=1),
        followup_stage="first_nudge",
        meta=meta if meta is not None else {"email": {"intended_to": "careers@acme.com"}},
    )
    db.add(app)
    db.commit()
    return app


def test_unmatched_mail_is_never_handed_to_the_classifier(session_factory):
    """The whole privacy design in one assertion. Matching happens locally and
    only what already belongs to an application is ever looked at further."""
    with session_factory() as db:
        _seed(db)
        private = mail(uid="9", sender="statements@mybank.com", subject="Your statement")
        reply = mail(uid="1", sender="careers@acme.com", message_id="<r1@acme.com>")
        engine = FixtureClassifier(
            default=MailVerdict(verdict="replied", quote="Thanks for applying")
        )

        report = sync_inbox(db, mailbox=FakeMailbox([private, reply]), classifier=engine, limit=10)

        assert engine.seen == ["1"]  # the bank statement was never read
        assert report.scanned == 2 and report.matched == 1 and report.classified == 1


def test_the_mailbox_is_asked_for_every_sender(session_factory):
    """Employer addresses are exactly what we don't know in advance."""
    with session_factory() as db:
        _seed(db)
        box = FakeMailbox([])
        sync_inbox(db, mailbox=box, classifier=FixtureClassifier(), since_days=21, limit=7)
        assert box.calls == [((), 21, 7)]


def test_a_reply_becomes_a_suggestion_not_an_outcome(session_factory):
    """The one thing this phase must never do is decide for you."""
    with session_factory() as db:
        app = _seed(db)
        engine = FixtureClassifier(
            default=MailVerdict(
                verdict="interview", quote="Thanks for applying", round_label="Round 1"
            )
        )
        # From the exact address we applied to, so the match is not a guess.
        m = mail(sender="careers@acme.com", message_id="<r1@acme.com>")
        sync_inbox(db, mailbox=FakeMailbox([m]), classifier=engine)

        assert db.get(Application, app.id).outcome_stage is None
        assert list_outcome_events(db, app.id) == []
        rows = pending_suggestions(db)
        assert len(rows) == 1 and rows[0].verdict == "interview"
        assert rows[0].round_label == "Round 1"
        assert rows[0].match_confidence == "address"


def test_an_automated_receipt_is_not_a_reply(session_factory):
    """ "We have received your application" is a robot, not somebody answering.
    It is recorded so the sync won't pay to read it twice, and never offered."""
    with session_factory() as db:
        _seed(db)
        engine = FixtureClassifier(
            default=MailVerdict(verdict="auto_ack", quote="Thanks for applying")
        )
        report = sync_inbox(
            db, mailbox=FakeMailbox([mail(message_id="<r1@acme.com>")]), classifier=engine
        )

        assert report.suggested == 0 and report.ignored == 1
        assert pending_suggestions(db) == []
        assert db.query(InboxSuggestion).one().status == IGNORED


def test_a_verdict_whose_quote_is_invented_is_never_offered(session_factory):
    with session_factory() as db:
        _seed(db)
        engine = FixtureClassifier(
            default=MailVerdict(verdict="offer", quote="We are delighted to offer you the role")
        )
        report = sync_inbox(
            db, mailbox=FakeMailbox([mail(message_id="<r1@acme.com>")]), classifier=engine
        )

        assert report.rejected_quotes == 1 and report.suggested == 0
        assert pending_suggestions(db) == []
        row = db.query(InboxSuggestion).one()
        assert row.status == UNUSABLE
        # The invented sentence is not kept — there is no version of it worth
        # showing, and storing it invites it being read as evidence later.
        assert row.quote == ""
        assert "does not appear" in row.match_reason


def test_an_unusable_verdict_is_not_paid_for_twice(session_factory):
    """Found by running the sync against a real mailbox twice: a rejected
    verdict used to leave no trace, so the message looked new on every later
    pass and was re-classified — and re-billed — forever, for an answer that
    was never going to be shown.
    """
    with session_factory() as db:
        _seed(db)
        messages = [mail(message_id="<r1@acme.com>")]
        engine = FixtureClassifier(default=MailVerdict(verdict="offer", quote="not in the message"))

        sync_inbox(db, mailbox=FakeMailbox(messages), classifier=engine)
        second = sync_inbox(db, mailbox=FakeMailbox(messages), classifier=engine)

        assert engine.seen == ["1"]  # asked once, ever
        assert second.classified == 0 and second.already_known == 1
        assert db.query(InboxSuggestion).count() == 1


def test_running_it_twice_costs_nothing(session_factory):
    """A mailbox pass re-reads the same messages by design, so the second run
    must not re-classify them — that would be a second bill for the same answer."""
    with session_factory() as db:
        _seed(db)
        messages = [mail(message_id="<r1@acme.com>")]
        engine = FixtureClassifier(
            default=MailVerdict(verdict="replied", quote="Thanks for applying")
        )

        sync_inbox(db, mailbox=FakeMailbox(messages), classifier=engine)
        second = sync_inbox(db, mailbox=FakeMailbox(messages), classifier=engine)

        assert engine.seen == ["1"]  # not read again
        assert second.already_known == 1 and second.suggested == 0
        assert db.query(InboxSuggestion).count() == 1


def test_an_over_long_message_id_is_hashed_not_truncated():
    """The column is VARCHAR(512) and Postgres enforces it where SQLite shrugs,
    so an id from a stranger's mail server would fail only in production —
    mid-flush, taking the whole sync with it.

    Truncating would be the wrong repair here, unlike a label: two ids sharing a
    prefix would collapse into one message and the second would never be read.
    """
    long_id = "<" + "a" * 600 + "@example.com>"
    sibling = "<" + "a" * 600 + "@other.com>"  # identical for 512 characters
    key = mail_key(mail(message_id=long_id))

    assert len(key) <= MAX_KEY
    assert key != mail_key(mail(message_id=sibling))
    # An ordinary id is left exactly as it is, so the table stays readable.
    assert mail_key(mail(message_id="<abc@acme.com>")) == "<abc@acme.com>"


def test_a_message_is_keyed_by_its_own_id_not_the_uid():
    """IMAP uids are per-folder and get re-issued when UIDVALIDITY changes, so a
    uid key would look like a whole new mailbox after a server move."""
    assert mail_key(mail(uid="4", message_id="<abc@acme.com>")) == "<abc@acme.com>"
    assert mail_key(mail(uid="4", message_id="")) == "uid:4"


def test_a_dry_run_gets_no_suggestions(session_factory):
    """Nothing left the machine, so nobody is writing back."""
    with session_factory() as db:
        _seed(db, result="dry_run")
        engine = FixtureClassifier(default=MailVerdict(verdict="replied", quote="Thanks"))
        report = sync_inbox(
            db, mailbox=FakeMailbox([mail(message_id="<r1@acme.com>")]), classifier=engine
        )
        assert report.matched == 0 and engine.seen == []


def test_the_test_recipient_address_is_not_used_for_matching(session_factory):
    """`to` may be your own rehearsal address; matching on it would tie every
    reply you ever get to whichever application was tested last."""
    with session_factory() as db:
        _seed(db, meta={"email": {"to": "me@example.com", "intended_to": "careers@acme.com"}})
        engine = FixtureClassifier(
            default=MailVerdict(verdict="replied", quote="Thanks for applying")
        )
        sync_inbox(
            db,
            mailbox=FakeMailbox([mail(uid="2", sender="me@example.com", message_id="<x@e.com>")]),
            classifier=engine,
        )
        assert engine.seen == []


# --------------------------------------------------------------------------- #
# acting on one
# --------------------------------------------------------------------------- #
def _suggest(db, app, **kw) -> InboxSuggestion:
    row = InboxSuggestion(
        application_id=app.id,
        mail_key="<r1@acme.com>",
        mail_from="careers@acme.com",
        mail_subject="Re: your application",
        mail_date=NOW - timedelta(days=3),
        match_confidence="address",
        match_reason="from careers@acme.com",
        verdict=kw.get("verdict", "interview"),
        quote="We would like to invite you",
        round_label=kw.get("round_label"),
        status=PENDING,
    )
    db.add(row)
    db.commit()
    return row


def test_accepting_one_writes_the_outcome_and_dates_it_from_the_mail(session_factory):
    """The employer replied when they replied. Dating the event from the click
    would make time-to-reply a measure of your inbox habits."""
    with session_factory() as db:
        app = _seed(db)
        row = _suggest(db, app, round_label="Round 1")

        found, updated = accept_suggestion(db, row.id)

        assert found.status == ACCEPTED
        assert updated.outcome_stage == "interview"
        events = list_outcome_events(db, app.id)
        assert len(events) == 1
        assert events[0].label == "Round 1"
        assert events[0].occurred_at.day == (NOW - timedelta(days=3)).day
        # And the follow-up stops, because the silence is over.
        assert updated.next_followup_at is None


def test_the_outcome_remembers_which_message_it_came_from(session_factory):
    with session_factory() as db:
        app = _seed(db)
        row = _suggest(db, app)
        accept_suggestion(db, row.id)
        notes = list_outcome_events(db, app.id)[0].notes
        assert "careers@acme.com" in notes and "invite you" in notes


def test_the_suggestion_and_the_outcome_land_in_one_transaction(session_factory):
    """Marking accepted used to happen *after* ``record_outcome`` committed, so
    a crash in the gap left the event written and the suggestion still pending —
    and the next click wrote the event again. Both changes now ride the same
    commit, which is observable as the status already being set by the time the
    event exists.
    """
    with session_factory() as db:
        app = _seed(db)
        row = _suggest(db, app)

        found, _ = accept_suggestion(db, row.id)

    # A fresh session, so nothing is being read out of the identity map.
    with session_factory() as db:
        assert db.get(InboxSuggestion, found.id).status == ACCEPTED
        assert len(list_outcome_events(db, app.id)) == 1


def test_a_refused_outcome_leaves_the_suggestion_alone(session_factory):
    """The other half of marking accepted *before* writing the outcome.

    ``record_outcome`` raises on an application that can't carry one, and by
    then the session is already holding the ACCEPTED mark. Nothing commits on
    that path — the route answers 409 and closes the session, which rolls the
    change back — so the suggestion has to still be pending in a fresh one.
    """
    with session_factory() as db:
        app = _seed(db, result="dry_run")
        row = _suggest(db, app)
        rid = row.id

        with pytest.raises(OutcomeRefused):
            accept_suggestion(db, rid)

    with session_factory() as db:
        assert db.get(InboxSuggestion, rid).status == PENDING


def test_accepting_twice_does_not_write_two_events(session_factory):
    with session_factory() as db:
        app = _seed(db)
        row = _suggest(db, app)
        accept_suggestion(db, row.id)
        accept_suggestion(db, row.id)
        assert len(list_outcome_events(db, app.id)) == 1


def test_dismissing_leaves_it_on_file_so_it_is_not_offered_again(session_factory):
    with session_factory() as db:
        app = _seed(db)
        row = _suggest(db, app)

        dismiss_suggestion(db, row.id)

        assert pending_suggestions(db) == []
        assert db.get(InboxSuggestion, row.id).status == DISMISSED
        assert list_outcome_events(db, app.id) == []


def test_acting_on_a_suggestion_that_is_not_there(session_factory):
    with session_factory() as db:
        assert accept_suggestion(db, 999) == (None, None)
        assert dismiss_suggestion(db, 999) is None
