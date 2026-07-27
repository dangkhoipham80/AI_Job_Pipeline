"""Phase 9: LinkedIn jobs via Job Alert emails, and manual job entry.

The parsing methods are pure functions over an email's HTML, so they are tested
against a saved message the same way the HTML scrapers are tested against saved
pages — no IMAP, no network, and above all no requests to LinkedIn.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from jobpilot.api.deps import get_db
from jobpilot.api.main import app
from jobpilot.config import get_secrets
from jobpilot.crawler.linkedin import JOB_LINK_RE, LinkedInAlertsScraper, job_url
from jobpilot.crawler.mailbox import MailMessage
from jobpilot.store.models import Job, JobStatus

AUTH = {"X-API-Token": get_secrets().jobpilot_api_token}


def _card(job_id: str, title: str, company: str, location: str, extra: str = "") -> str:
    """One job card, copied from the shape real alert emails use.

    Two details cost real bugs before this was checked against actual mail:
    company and location arrive on ONE line separated by a middle dot, and a
    social-proof line ("34 company alumni") follows, which reads exactly like a
    location if you assume the second line is one.
    """
    tracked = (
        f"https://www.linkedin.com/comm/jobs/view/{job_id}/"
        f"?trackingId=abc%3D%3D&refId=xyz&midToken=AQ"
    )
    return f"""
    <table><tr><td>
      <table><tr>
        <td><a href="{tracked}"><img src="https://media.licdn.com/logo.png"/></a></td>
        <td>
          <table>
            <tr><td><a href="{tracked}"><strong>{title}</strong></a></td></tr>
            <tr><td>{company} &middot; {location}</td></tr>
            {extra}
          </table>
        </td>
      </tr></table>
    </td></tr></table>
    """


ALERT_EMAIL = f"""
<html><body>
  <table><tr><td>
    <h2>Your job alert for backend engineer</h2>
    {_card("4012345678", "Backend Engineer (Java, Spring Boot)", "ACME Corp",
           "Ho Chi Minh City, Vietnam (Hybrid)", "<tr><td>34 company alumni</td></tr>")}
    {_card("4012345679", "Junior Java Developer", "Beta Technologies",
           "Ha Noi, Vietnam (On-site)", "<tr><td>4 connections</td></tr>")}
    {_card("4012345680", "Software Engineer, Backend", "Gamma Labs", "Vietnam (Remote)",
           "<tr><td>Promoted</td></tr>")}
    <a href="https://www.linkedin.com/jobs/search/?keywords=backend">See all jobs</a>
    <a href="https://www.linkedin.com/comm/psettings/email-unsubscribe">Unsubscribe</a>
  </td></tr></table>
</body></html>
"""


@pytest.fixture
def scraper() -> LinkedInAlertsScraper:
    return LinkedInAlertsScraper()


# --------------------------------------------------------------------------- #
# Parsing an alert email
# --------------------------------------------------------------------------- #
def test_finds_every_job_card(scraper):
    hits = scraper.parse_search(ALERT_EMAIL)
    assert [h.native_id for h in hits] == ["4012345678", "4012345679", "4012345680"]


def test_reads_title_company_and_location(scraper):
    first = scraper.parse_search(ALERT_EMAIL)[0]
    assert first.title == "Backend Engineer (Java, Spring Boot)"
    assert first.company == "ACME Corp"
    assert first.location == "Ho Chi Minh City, Vietnam (Hybrid)"


def test_company_and_location_are_split_on_the_middle_dot(scraper):
    """Real cards put both on one line: "ACME Corp · Ho Chi Minh City". Keeping
    them merged made every company name carry a location tail."""
    for hit in scraper.parse_search(ALERT_EMAIL):
        assert "·" not in hit.company
        assert hit.company in ("ACME Corp", "Beta Technologies", "Gamma Labs")


def test_social_proof_is_never_read_as_a_location(scraper):
    """ "34 company alumni" / "4 connections" sit where a location would be."""
    locations = [h.location for h in scraper.parse_search(ALERT_EMAIL)]
    assert all("alumni" not in (loc or "") for loc in locations)
    assert all("connection" not in (loc or "") for loc in locations)


def test_tracking_parameters_are_stripped_from_the_url(scraper):
    """The alert URL carries trackingId/midToken; the stored one must not."""
    first = scraper.parse_search(ALERT_EMAIL)[0]
    assert first.url == "https://www.linkedin.com/jobs/view/4012345678/"
    assert "trackingId" not in first.url and "midToken" not in first.url


def test_logo_and_title_links_collapse_to_one_hit(scraper):
    """Each card links twice — once from the logo image, once from the title."""
    assert len(scraper.parse_search(ALERT_EMAIL)) == 3


def test_footer_links_are_not_jobs(scraper):
    hits = scraper.parse_search(ALERT_EMAIL)
    assert all("unsubscribe" not in h.title.lower() for h in hits)
    assert all("see all jobs" not in h.title.lower() for h in hits)


def test_badges_are_not_mistaken_for_a_company(scraper):
    """ "Promoted" / social-proof lines sit right next to the real fields."""
    by_id = {h.native_id: h for h in scraper.parse_search(ALERT_EMAIL)}
    assert by_id["4012345678"].company == "ACME Corp"
    assert by_id["4012345679"].company == "Beta Technologies"


def test_an_email_with_no_jobs_yields_nothing(scraper):
    assert scraper.parse_search("<html><body><p>No new jobs.</p></body></html>") == []
    assert scraper.parse_search("") == []


def test_malformed_html_does_not_raise(scraper):
    assert scraper.parse_search("<html><a href='/jobs/view/'>broken") == []


def test_link_regex_matches_both_url_shapes():
    assert JOB_LINK_RE.search("https://www.linkedin.com/jobs/view/123/").group(1) == "123"
    assert JOB_LINK_RE.search("https://www.linkedin.com/comm/jobs/view/456/?x=1").group(1) == "456"
    assert JOB_LINK_RE.search("https://www.linkedin.com/in/someone") is None


# --------------------------------------------------------------------------- #
# Turning a card into a job
# --------------------------------------------------------------------------- #
def test_jobs_are_external_and_never_auto_applied(scraper):
    """CLAUDE.md rule 2: LinkedIn is never applied to automatically."""
    hit = scraper.parse_search(ALERT_EMAIL)[0]
    raw = scraper.parse_detail("", hit)
    assert raw.apply_channel == "external"
    assert raw.apply_target == job_url("4012345678")


def test_missing_description_is_empty_and_flagged(scraper):
    """Alert emails carry no JD. The description stays genuinely empty so
    "has no JD" is one check everywhere; needs_jd records why."""
    raw = scraper.parse_detail("", scraper.parse_search(ALERT_EMAIL)[0])
    assert raw.description_md == ""
    assert raw.extra["needs_jd"] is True


def test_needs_jd_survives_normalisation_into_the_payload(scraper):
    """The flag was silently dropped once: normalize() rebuilt the payload from
    named fields and ignored `extra`."""
    from jobpilot.config import Config
    from jobpilot.crawler.normalize import normalize

    raw = scraper.parse_detail("", scraper.parse_search(ALERT_EMAIL)[0])
    payload = normalize(raw, Config()).payload
    assert payload["needs_jd"] is True
    # ...and extras must never shadow a canonical §3.1 field.
    assert payload["source"] == "linkedin"


def test_job_id_is_the_linkedin_posting_id(scraper):
    raw = scraper.parse_detail("", scraper.parse_search(ALERT_EMAIL)[0])
    assert raw.id == "linkedin:4012345678"


# --------------------------------------------------------------------------- #
# The crawl loop, against a fake mailbox
# --------------------------------------------------------------------------- #
class FakeMailbox:
    def __init__(self, messages):
        self.messages = messages
        self.calls = []

    def fetch(self, senders, since_days, limit):
        self.calls.append((senders, since_days, limit))
        return self.messages


def _mail(uid: str, html: str, days_ago: int = 0) -> MailMessage:
    return MailMessage(
        uid=uid,
        subject="Your job alert for backend engineer",
        sender="LinkedIn <jobalerts-noreply@linkedin.com>",
        date=datetime(2026, 7, 20) - timedelta(days=days_ago),
        html=html,
    )


def test_crawl_reads_the_mailbox_and_never_the_network():
    mailbox = FakeMailbox([_mail("1", ALERT_EMAIL)])
    scraper = LinkedInAlertsScraper(mailbox=mailbox)
    jobs = scraper.crawl()

    assert len(jobs) == 3
    assert {j.source for j in jobs} == {"linkedin"}
    # The base class's HTTP fetcher was never even resolved.
    assert scraper._owned_fetcher is None


def test_the_same_job_across_daily_alerts_is_deduped():
    """Alerts repeat: a job seen Monday shows up again Tuesday."""
    mailbox = FakeMailbox([_mail("2", ALERT_EMAIL, 0), _mail("1", ALERT_EMAIL, 1)])
    assert len(LinkedInAlertsScraper(mailbox=mailbox).crawl()) == 3


def test_posted_at_falls_back_to_the_email_date():
    """Cards carry no post date, so the alert's own date is the best estimate."""
    mailbox = FakeMailbox([_mail("1", ALERT_EMAIL)])
    job = LinkedInAlertsScraper(mailbox=mailbox).crawl()[0]
    assert job.posted_raw.startswith("2026-07-20")


def test_a_broken_email_does_not_sink_the_batch(monkeypatch):
    good = _mail("2", ALERT_EMAIL)
    bad = _mail("1", ALERT_EMAIL)
    scraper = LinkedInAlertsScraper(mailbox=FakeMailbox([bad, good]))
    original = scraper.parse_search

    def explode(html):
        if scraper.parse_search.calls == 0:
            scraper.parse_search.calls += 1
            raise ValueError("unparsable")
        return original(html)

    explode.calls = 0
    monkeypatch.setattr(scraper, "parse_search", explode)
    assert len(scraper.crawl()) == 3  # the good email still came through


def test_limit_is_respected():
    mailbox = FakeMailbox([_mail("1", ALERT_EMAIL)])
    assert len(LinkedInAlertsScraper(mailbox=mailbox).crawl(limit=2)) == 2


def test_lookback_window_is_passed_to_the_mailbox():
    mailbox = FakeMailbox([])
    LinkedInAlertsScraper(mailbox=mailbox, since_days=30).crawl()
    assert mailbox.calls[0][1] == 30


# --------------------------------------------------------------------------- #
# Manual job entry — the other way LinkedIn jobs get in
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def test_create_a_job_by_hand(client):
    r = client.post(
        "/jobs",
        headers=AUTH,
        json={
            "url": "https://www.linkedin.com/jobs/view/4012345678/",
            "title": "Backend Engineer",
            "company": "ACME Corp",
            "location": "Ho Chi Minh City",
            "description_md": "Java, Spring Boot, Kafka",
            "skills": ["Java", "Spring Boot"],
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["source"] == "manual"
    assert body["description_md"] == "Java, Spring Boot, Kafka"
    # External by default: you submit LinkedIn applications yourself.
    assert body["apply_channel"] == "external"


def test_the_linkedin_posting_id_makes_the_job_id_stable(client):
    """Pasting the same posting twice must update it, not duplicate it."""
    payload = {
        "url": "https://www.linkedin.com/jobs/view/4012345678/?trackingId=x",
        "title": "Backend Engineer",
        "company": "ACME Corp",
    }
    first = client.post("/jobs", headers=AUTH, json=payload).json()
    second = client.post(
        "/jobs", headers=AUTH, json={**payload, "title": "Backend Engineer II"}
    ).json()

    assert first["id"] == second["id"] == "manual:linkedin-4012345678"
    assert second["title"] == "Backend Engineer II"
    assert len(client.get("/jobs", headers=AUTH).json()) == 1


def test_a_job_without_a_url_still_gets_a_stable_id(client):
    body = client.post(
        "/jobs", headers=AUTH, json={"title": "Backend Engineer", "company": "ACME Corp"}
    ).json()
    assert body["id"].startswith("manual:acme-corp-backend-engineer")


def test_title_and_company_are_required(client):
    assert (
        client.post("/jobs", headers=AUTH, json={"title": " ", "company": "X"}).status_code == 422
    )


def test_create_requires_a_token(client):
    assert client.post("/jobs", json={"title": "a", "company": "b"}).status_code == 401


def test_pasting_a_description_clears_the_needs_jd_flag(client, session_factory):
    """The alert-sourced flow: job arrives without a JD, you paste one in."""
    with session_factory() as s:
        s.add(
            Job(
                id="linkedin:4012345678",
                source="linkedin",
                title="Backend Engineer",
                company="ACME Corp",
                status=JobStatus.DISCOVERED,
                apply_channel="external",
                payload={"needs_jd": True, "description_md": "", "skills": []},
            )
        )
        s.commit()

    r = client.patch(
        "/jobs/linkedin:4012345678",
        headers=AUTH,
        json={"description_md": "Java, Spring Boot, PostgreSQL, Kafka"},
    )
    assert r.status_code == 200
    assert r.json()["description_md"].startswith("Java, Spring Boot")

    with session_factory() as s:
        assert "needs_jd" not in (s.get(Job, "linkedin:4012345678").payload or {})


def test_patch_only_touches_what_it_sets(client):
    created = client.post(
        "/jobs", headers=AUTH, json={"title": "Backend Engineer", "company": "ACME Corp"}
    ).json()
    patched = client.patch(
        f"/jobs/{created['id']}", headers=AUTH, json={"salary": "1500 USD"}
    ).json()
    assert patched["salary"] == "1500 USD"
    assert patched["title"] == "Backend Engineer"  # untouched


def test_patch_404_and_empty(client):
    assert client.patch("/jobs/nope:1", headers=AUTH, json={"title": "x"}).status_code == 404
    created = client.post("/jobs", headers=AUTH, json={"title": "T", "company": "C"}).json()
    assert client.patch(f"/jobs/{created['id']}", headers=AUTH, json={}).status_code == 422
