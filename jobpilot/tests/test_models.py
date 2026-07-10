"""Phase 2: ORM model + schema smoke tests (SQLite, no Postgres needed)."""

from __future__ import annotations

from jobpilot.store.models import Application, Job, JobStatus


def test_job_defaults_and_json_payload(session_factory):
    with session_factory() as s:
        s.add(Job(id="itviec:1", source="itviec", title="Backend Engineer", company="ACME"))
        s.commit()

    with session_factory() as s:
        job = s.get(Job, "itviec:1")
        assert job is not None
        assert job.status is JobStatus.DISCOVERED  # client-side default applied
        assert job.match_score == 0.0
        assert job.payload == {}
        assert job.crawled_at is not None  # server_default now()


def test_job_payload_roundtrips_jsonb(session_factory):
    with session_factory() as s:
        s.add(
            Job(
                id="topcv:42",
                source="topcv",
                title="Java Dev",
                company="Foo",
                payload={"skills": ["Java", "Spring"], "nested": {"k": 1}},
            )
        )
        s.commit()

    with session_factory() as s:
        job = s.get(Job, "topcv:42")
        assert job.payload["skills"] == ["Java", "Spring"]
        assert job.payload["nested"]["k"] == 1


def test_application_fk_and_cascade(session_factory):
    with session_factory() as s:
        job = Job(id="vietnamworks:7", source="vietnamworks", title="BE", company="Bar")
        job.applications.append(Application(channel="email", result="success"))
        s.add(job)
        s.commit()

    with session_factory() as s:
        job = s.get(Job, "vietnamworks:7")
        assert len(job.applications) == 1
        assert job.applications[0].channel == "email"
