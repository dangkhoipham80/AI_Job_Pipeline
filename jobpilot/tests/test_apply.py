"""Phase 6: the apply dispatcher — gates, channels, cover letter guardrails."""

from __future__ import annotations

from pathlib import Path

import pytest

from jobpilot.apply import dispatcher
from jobpilot.apply.email import EmailError, build_email, recipient_of
from jobpilot.apply.letter import CoverLetter, FixtureLetterEngine, check_letter
from jobpilot.apply.portal import contact_fields, match_field, prepare_handoff
from jobpilot.config import ApplyCfg, EmailCfg
from jobpilot.cv import store as cv_store
from jobpilot.cv.compile import scope_slug
from jobpilot.store.models import Application, Job, JobStatus, Run
from jobpilot.tailor.build import BuildError, BuildResult
from jobpilot.tailor.guard import GuardrailViolation
from jobpilot.tailor.schema import Requirement, TailorPlan

LETTER = CoverLetter(
    greeting="Dear Hiring Team at ACME Corp,",
    paragraphs=[
        "I am applying for the Backend Engineer role. I build RESTful APIs with Java and "
        "Spring Boot at Example Software.",
        "I wrote unit tests with JUnit and deployed through Jenkins pipelines.",
    ],
    closing="Best regards,",
)


@pytest.fixture
def db(session_factory, tmp_path, monkeypatch):
    # Keep every build artefact inside the test's tmp dir.
    monkeypatch.setattr(
        "jobpilot.apply.dispatcher.build_dir", lambda scope: tmp_path / scope_slug(scope)
    )

    # Stub the LaTeX build. Left real, every test that applies with a letter
    # engine would start a Docker container: slow, and green only on machines
    # that happen to have Docker. The letter PDF gets its own tests, which build
    # for real; here it just needs to exist.
    def fake_compile(_letter, _doc, _job, dest, today=None):
        dest.mkdir(parents=True, exist_ok=True)
        pdf = dest / "cover_letter.pdf"
        pdf.write_bytes(b"%PDF-1.5\n<</Type /Page>>\n%%EOF")
        return BuildResult(pdf=pdf, pages=1)

    monkeypatch.setattr("jobpilot.apply.dispatcher.compile_letter", fake_compile)
    with session_factory() as s:
        cv_store.ensure_master(s)
        yield s


def _job(db, **kw) -> Job:
    defaults = dict(
        id="itviec:1",
        source="itviec",
        title="Backend Engineer",
        company="ACME Corp",
        status=JobStatus.APPROVED,
        apply_channel="email",
        apply_target="hr@acme.com",
        payload={},
    )
    job = Job(**{**defaults, **kw})
    db.add(job)
    db.commit()
    return job


def _cv(tmp_path: Path, job_id: str) -> Path:
    pdf = tmp_path / scope_slug(job_id) / "cv.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4\n%fake\n")
    return pdf


def _cfg(**kw) -> ApplyCfg:
    return ApplyCfg(email=EmailCfg(**{"enabled": True, "from_addr": "me@example.com", **kw}))


# --------------------------------------------------------------------------- #
# Email gates — the part that can actually send mail
# --------------------------------------------------------------------------- #
def test_recipient_parsing():
    assert recipient_of("hr@acme.com") == "hr@acme.com"
    assert recipient_of("mailto:hr@acme.com") == "hr@acme.com"
    assert recipient_of("https://acme.com/careers") == ""
    assert recipient_of(None) == ""


def test_disabled_email_cannot_be_built():
    with pytest.raises(EmailError, match="disabled"):
        build_email(cfg=ApplyCfg(), to="hr@acme.com", subject="s", body="b")


def test_missing_from_addr_blocks_email():
    cfg = ApplyCfg(email=EmailCfg(enabled=True))
    with pytest.raises(EmailError, match="from_addr"):
        build_email(cfg=cfg, to="hr@acme.com", subject="s", body="b")


def test_non_email_target_blocks_email():
    with pytest.raises(EmailError, match="no usable email"):
        build_email(cfg=_cfg(), to="https://acme.com/apply", subject="s", body="b")


def test_test_recipient_redirects_delivery():
    email = build_email(
        cfg=_cfg(test_recipient="me@example.com"), to="hr@acme.com", subject="s", body="b"
    )
    assert email.to == "me@example.com"
    assert email.intended_to == "hr@acme.com"
    assert email.redirected is True
    assert "would have gone to hr@acme.com" in email.as_message().get_content()


def test_without_test_recipient_mail_goes_to_the_employer():
    email = build_email(cfg=_cfg(), to="hr@acme.com", subject="s", body="b")
    assert email.to == "hr@acme.com" and email.redirected is False


def test_message_carries_the_cv_attachment(tmp_path):
    pdf = _cv(tmp_path, "itviec:1")
    email = build_email(
        cfg=_cfg(dry_run=False), to="hr@acme.com", subject="Hi", body="Body", attachments=[pdf]
    )
    parts = list(email.as_message().iter_attachments())
    assert len(parts) == 1
    assert parts[0].get_filename() == "cv.pdf"
    assert parts[0].get_content_type() == "application/pdf"


def test_send_refuses_on_a_dry_run():
    from jobpilot.apply.email import send_email
    from jobpilot.config import Secrets

    email = build_email(cfg=_cfg(), to="hr@acme.com", subject="s", body="b")
    assert email.dry_run is True
    with pytest.raises(EmailError, match="dry_run"):
        send_email(email, Secrets(smtp_host="localhost"))


# --------------------------------------------------------------------------- #
# Cover letter guardrails
# --------------------------------------------------------------------------- #
def test_letter_claiming_an_absent_skill_is_rejected(db):
    master = cv_store.get_document(db, "master")
    job = _job(db)
    bad = LETTER.model_copy(
        update={"paragraphs": ["I have production experience with Kubernetes and Terraform."]}
    )
    report = check_letter(bad, master, job)
    assert not report.ok and "Terraform" in report.violations[0]


def test_letter_may_name_the_employer_and_city(db):
    master = cv_store.get_document(db, "master")
    job = _job(db, company="Zalopay", location="Da Nang")
    letter = LETTER.model_copy(
        update={"paragraphs": ["I would like to join Zalopay in Da Nang as a backend engineer."]}
    )
    assert check_letter(letter, master, job).ok


def test_learning_note_may_name_a_gap_but_paragraphs_may_not(db):
    """The whole point of splitting the field: honest gap talk stays possible."""
    master = cv_store.get_document(db, "master")
    job = _job(db)
    plan = TailorPlan(
        match_score=0.6,
        requirements=[Requirement(text="Terraform", kind="nice_to_have", status="MISSING")],
    )

    ok = LETTER.model_copy(
        update={"learning_note": "I have not used Terraform yet, and I am keen to pick it up."}
    )
    assert check_letter(ok, master, job, plan).ok

    smuggled = LETTER.model_copy(
        update={"paragraphs": [*LETTER.paragraphs, "I also use Terraform daily."]}
    )
    assert not check_letter(smuggled, master, job, plan).ok


def test_learning_note_cannot_invent_a_gap_that_is_not_one(db):
    master = cv_store.get_document(db, "master")
    job = _job(db)
    plan = TailorPlan(match_score=0.6, requirements=[])
    letter = LETTER.model_copy(update={"learning_note": "I am eager to learn Rust."})
    assert not check_letter(letter, master, job, plan).ok


def test_overlong_letter_is_rejected(db):
    master = cv_store.get_document(db, "master")
    job = _job(db)
    long_letter = LETTER.model_copy(update={"paragraphs": ["word " * 400]})
    assert any("words" in v for v in check_letter(long_letter, master, job).violations)


def test_letter_body_layout():
    body = LETTER.body()
    assert body.startswith("Dear Hiring Team")
    assert body.endswith("Best regards,")
    assert "\n\n" in body


# --------------------------------------------------------------------------- #
# Channel resolution + portal handoff
# --------------------------------------------------------------------------- #
def test_channel_resolution(db):
    assert dispatcher.resolve_channel(Job(id="a", apply_target="hr@x.com")) == "email"
    assert dispatcher.resolve_channel(Job(id="b", apply_target="https://x.com/apply")) == "portal"
    assert dispatcher.resolve_channel(Job(id="c", apply_target=None)) == "external"
    # A declared channel always wins over the guess.
    assert (
        dispatcher.resolve_channel(Job(id="d", apply_channel="external", apply_target="hr@x.com"))
        == "external"
    )


def test_contact_fields_come_from_the_cv_header(db):
    fields = contact_fields(cv_store.get_document(db, "master"))
    assert fields["email"] == "alex@example.com"
    assert fields["github"].endswith("/alex-example")
    assert fields["full_name"] == "Alex Example"


def test_names_are_cased_for_a_web_form_not_for_latex(db):
    """The CV header holds ALEX/EXAMPLE in caps for the LaTeX header styling;
    a web form wants Alex Example."""
    fields = contact_fields(cv_store.get_document(db, "master"))
    assert fields["first_name"] == "Alex" and fields["last_name"] == "Example"


def test_form_label_matching():
    assert match_field("First Name") == "first_name"
    assert match_field("your-email") == "email"
    assert match_field("Số điện thoại") == "phone"
    assert match_field("Why do you want this job?") is None


def test_prepare_handoff_never_submits(db, tmp_path):
    handoff = prepare_handoff(
        url="https://acme.com/apply",
        master=cv_store.get_document(db, "master"),
        cv_path=_cv(tmp_path, "itviec:1"),
    )
    assert handoff.prefilled is False
    assert "Nothing was submitted" in handoff.note


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #
def test_apply_requires_a_built_cv(db):
    _job(db)
    with pytest.raises(dispatcher.ApplyRefused, match="no tailored CV"):
        dispatcher.apply_job(db, "itviec:1")


def test_apply_requires_the_right_status(db, tmp_path):
    _job(db, status=JobStatus.REVIEW)
    _cv(tmp_path, "itviec:1")
    with pytest.raises(dispatcher.ApplyRefused, match="REVIEW"):
        dispatcher.apply_job(db, "itviec:1")


def test_dry_run_leaves_the_job_approved(db, tmp_path, monkeypatch):
    """Nothing was sent, so calling it SUBMITTED would be a lie."""
    monkeypatch.setattr(
        "jobpilot.apply.dispatcher.get_config",
        lambda: type("C", (), {"apply": _cfg()})(),
    )
    _job(db)
    _cv(tmp_path, "itviec:1")

    outcome = dispatcher.apply_job(db, "itviec:1")
    assert outcome.result == "dry_run"
    assert db.get(Job, "itviec:1").status == JobStatus.APPROVED
    app = db.query(Application).one()
    assert app.result == "dry_run" and app.submitted_at is None
    assert app.meta["email"]["to"] == "hr@acme.com"


def test_disabled_email_fails_the_job_with_the_reason(db, tmp_path):
    _job(db)
    _cv(tmp_path, "itviec:1")
    outcome = dispatcher.apply_job(db, "itviec:1")
    assert outcome.result == "failed" and "disabled" in outcome.detail
    assert db.get(Job, "itviec:1").status == JobStatus.FAILED
    assert db.query(Application).one().error_msg.startswith("email apply is disabled")


def test_successful_send_marks_submitted(db, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "jobpilot.apply.dispatcher.get_config",
        lambda: type("C", (), {"apply": _cfg(dry_run=False)})(),
    )
    monkeypatch.setattr("jobpilot.apply.dispatcher.send_email", lambda email, secrets: "sent ok")
    _job(db)
    _cv(tmp_path, "itviec:1")

    outcome = dispatcher.apply_job(db, "itviec:1")
    assert outcome.result == "success"
    assert db.get(Job, "itviec:1").status == JobStatus.SUBMITTED
    app = db.query(Application).one()
    assert app.result == "success" and app.submitted_at is not None


def test_send_failure_marks_failed_with_the_error(db, tmp_path, monkeypatch):
    def boom(email, secrets):
        raise EmailError("SMTP error: mailbox unavailable")

    monkeypatch.setattr(
        "jobpilot.apply.dispatcher.get_config",
        lambda: type("C", (), {"apply": _cfg(dry_run=False)})(),
    )
    monkeypatch.setattr("jobpilot.apply.dispatcher.send_email", boom)
    _job(db)
    _cv(tmp_path, "itviec:1")

    outcome = dispatcher.apply_job(db, "itviec:1")
    assert outcome.result == "failed"
    assert "mailbox unavailable" in db.query(Application).one().error_msg
    assert db.get(Job, "itviec:1").status == JobStatus.FAILED


def test_portal_prepares_and_waits_for_the_user(db, tmp_path):
    _job(db, apply_channel="portal", apply_target="https://acme.com/apply")
    _cv(tmp_path, "itviec:1")

    outcome = dispatcher.apply_job(db, "itviec:1")
    assert outcome.result == "awaiting_user"
    # Still SUBMITTING — nothing has been submitted on the user's behalf.
    assert db.get(Job, "itviec:1").status == JobStatus.SUBMITTING
    assert outcome.handoff.fields["email"]
    assert db.query(Application).one().meta["handoff"]["url"] == "https://acme.com/apply"


def test_external_channel_is_never_automated(db, tmp_path):
    _job(db, apply_channel="external", apply_target="https://linkedin.com/jobs/1")
    _cv(tmp_path, "itviec:1")
    outcome = dispatcher.apply_job(db, "itviec:1")
    assert outcome.result == "awaiting_user" and outcome.channel == "external"


def test_confirm_submit_completes_a_portal_application(db, tmp_path):
    _job(db, apply_channel="portal", apply_target="https://acme.com/apply")
    _cv(tmp_path, "itviec:1")
    dispatcher.apply_job(db, "itviec:1")

    job = dispatcher.confirm_submit(db, "itviec:1")
    assert job.status == JobStatus.SUBMITTED
    app = db.query(Application).one()
    assert app.result == "success" and app.submitted_at is not None


def test_confirm_submit_requires_submitting(db, tmp_path):
    _job(db)
    with pytest.raises(dispatcher.ApplyRefused):
        dispatcher.confirm_submit(db, "itviec:1")


def test_report_failure_records_the_reason(db, tmp_path):
    _job(db, apply_channel="portal", apply_target="https://acme.com/apply")
    _cv(tmp_path, "itviec:1")
    dispatcher.apply_job(db, "itviec:1")

    job = dispatcher.mark_failed(db, "itviec:1", "form rejected the CV size")
    assert job.status == JobStatus.FAILED
    assert db.query(Application).one().error_msg == "form rejected the CV size"


def test_cover_letter_is_written_next_to_the_cv(db, tmp_path):
    _job(db, apply_channel="portal", apply_target="https://acme.com/apply")
    _cv(tmp_path, "itviec:1")

    dispatcher.apply_job(db, "itviec:1", FixtureLetterEngine(letter=LETTER))
    app = db.query(Application).one()
    assert Path(app.cover_letter_path).read_text(encoding="utf-8").startswith("Dear Hiring Team")


def test_the_letter_pdf_is_built_and_recorded(db, tmp_path):
    _job(db, apply_channel="portal", apply_target="https://acme.com/apply")
    _cv(tmp_path, "itviec:1")

    dispatcher.apply_job(db, "itviec:1", FixtureLetterEngine(letter=LETTER))
    app = db.query(Application).one()
    assert Path(app.cover_letter_pdf_path).name == "cover_letter.pdf"
    assert Path(app.cover_letter_pdf_path).is_file()
    assert app.meta["letter"]["pdf_error"] is None


def test_a_letter_pdf_that_will_not_build_still_applies(db, tmp_path, monkeypatch):
    """Docker being down is not a reason to sit on an application whose CV
    already built. The letter still goes out as text; the row says why there is
    no PDF instead of leaving a NULL nobody can explain."""

    def boom(*_a, **_k):
        raise BuildError("! Undefined control sequence")

    monkeypatch.setattr("jobpilot.apply.dispatcher.compile_letter", boom)
    _job(db, apply_channel="portal", apply_target="https://acme.com/apply")
    _cv(tmp_path, "itviec:1")

    outcome = dispatcher.apply_job(db, "itviec:1", FixtureLetterEngine(letter=LETTER))
    assert outcome.result == "awaiting_user"
    app = db.query(Application).one()
    assert app.cover_letter_pdf_path is None
    assert app.cover_letter_path is not None  # the letter itself survived
    assert "Undefined control sequence" in app.meta["letter"]["pdf_error"]


def test_a_letter_pdf_failing_in_any_way_still_applies(db, tmp_path, monkeypatch):
    """Not just BuildError. The same call copies assets (OSError on a full disk)
    and renders a template (RenderError); if either escapes, the job sits in
    SUBMITTING forever with no error_msg — the exact outcome the fallback is
    there to prevent."""
    _job(db, apply_channel="portal", apply_target="https://acme.com/apply")
    _cv(tmp_path, "itviec:1")

    def boom(*_a, **_k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("jobpilot.apply.dispatcher.compile_letter", boom)
    outcome = dispatcher.apply_job(db, "itviec:1", FixtureLetterEngine(letter=LETTER))

    assert outcome.result == "awaiting_user"
    assert db.get(Job, "itviec:1").status == JobStatus.SUBMITTING
    app = db.query(Application).one()
    assert app.cover_letter_pdf_path is None
    # The row names the failure rather than leaving an unexplained NULL.
    assert "OSError" in app.meta["letter"]["pdf_error"]
    assert "No space left" in app.meta["letter"]["pdf_error"]


def test_the_letter_pdf_is_attached_to_the_email(db, tmp_path, monkeypatch):
    sent = {}
    monkeypatch.setattr(
        "jobpilot.apply.dispatcher.get_config",
        lambda: type("C", (), {"apply": _cfg(dry_run=False)})(),
    )
    monkeypatch.setattr(
        "jobpilot.apply.dispatcher.send_email",
        lambda email, secrets: sent.update(names=[p.name for p in email.attachments]) or "sent",
    )
    _job(db)
    _cv(tmp_path, "itviec:1")

    dispatcher.apply_job(db, "itviec:1", FixtureLetterEngine(letter=LETTER))
    assert sent["names"] == ["cv.pdf", "cover_letter.pdf"]


def test_no_letter_pdf_means_no_broken_attachment(db, tmp_path, monkeypatch):
    """A CV must never go out with a missing or stale file stapled to it."""

    def boom(*_a, **_k):
        raise BuildError("docker not found on PATH")

    sent = {}
    monkeypatch.setattr("jobpilot.apply.dispatcher.compile_letter", boom)
    monkeypatch.setattr(
        "jobpilot.apply.dispatcher.get_config",
        lambda: type("C", (), {"apply": _cfg(dry_run=False)})(),
    )
    monkeypatch.setattr(
        "jobpilot.apply.dispatcher.send_email",
        lambda email, secrets: sent.update(names=[p.name for p in email.attachments]) or "sent",
    )
    _job(db)
    _cv(tmp_path, "itviec:1")

    dispatcher.apply_job(db, "itviec:1", FixtureLetterEngine(letter=LETTER))
    assert sent["names"] == ["cv.pdf"]


def test_applying_without_a_letter_engine_records_no_letter_at_all(db, tmp_path):
    """No letter and a letter whose PDF failed are different states."""
    _job(db, apply_channel="portal", apply_target="https://acme.com/apply")
    _cv(tmp_path, "itviec:1")

    dispatcher.apply_job(db, "itviec:1")
    app = db.query(Application).one()
    assert app.cover_letter_path is None and app.cover_letter_pdf_path is None
    assert "letter" not in app.meta


def test_a_dishonest_cover_letter_stops_the_application(db, tmp_path):
    """The letter guardrail must fail the apply, not get skipped past."""
    _job(db, apply_channel="portal", apply_target="https://acme.com/apply")
    _cv(tmp_path, "itviec:1")
    liar = LETTER.model_copy(update={"paragraphs": ["I run Kubernetes and Terraform at scale."]})

    class Rogue:
        def write(self, master, job, plan=None):
            raise GuardrailViolation("cover letter claims Terraform")

    outcome = dispatcher.apply_job(db, "itviec:1", Rogue())
    assert outcome.result == "failed" and "Terraform" in outcome.detail
    assert db.get(Job, "itviec:1").status == JobStatus.FAILED
    # FixtureLetterEngine enforces the same check before it ever returns.
    with pytest.raises(GuardrailViolation):
        FixtureLetterEngine(letter=liar).write(
            cv_store.get_document(db, "master"), db.get(Job, "itviec:1")
        )


def test_apply_records_a_run(db, tmp_path):
    _job(db, apply_channel="portal", apply_target="https://acme.com/apply")
    _cv(tmp_path, "itviec:1")
    dispatcher.apply_job(db, "itviec:1")
    run = db.query(Run).filter(Run.kind == "apply").one()
    assert run.finished_at is not None and run.stats["result"] == "awaiting_user"
