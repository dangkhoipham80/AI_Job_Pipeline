"""Phase 3: ITviec parser contract, pinned against snapshot-shaped HTML.

The snapshot below is trimmed from a real ITviec result page, keeping the parts
that broke the first implementation: utility-only class names, a company linked
twice (logo + name), a promo banner that looks like a salary, and a login wall
where the salary should be. Selectors are best-effort against a site that does
rename things, so these tests lock the *mechanism* — when ITviec changes, a test
fails instead of the crawl quietly returning nothing.
"""

from __future__ import annotations

from jobpilot.crawler.itviec import ITViecScraper
from jobpilot.crawler.types import SearchHit

# Shaped like the live page: the job identity lives in a Stimulus value, and
# every human-readable field sits in a div whose classes say nothing about it.
SEARCH_HTML = """
<div class="card-jobs-list">
  <div class="job-card ipt-2 d-flex" data-job-key="cb3bea00-uuid-rotates"
       data-search--job-selection-job-slug-value="backend-java-acme-101">
    <span class="text-it-white opacity-50 tiny-text">Hiring</span>
    <div class="text-rich-grey">Posted 8 hours ago</div>
    <h3>Backend Engineer (Java)</h3>
    <a href="/companies/acme?lab_feature=preview"><img src="/logo.png"></a>
    <a href="/companies/acme?lab_feature=preview">ACME Corp</a>
    <a class="sign-in-view-salary" href="/sign_in?job=x">Sign in to view salary</a>
    <div class="text-rich-grey text-truncate">Ho Chi Minh</div>
    <div class="text-rich-grey flex-shrink-0">At office</div>
  </div>

  <div class="job-card" data-search--job-selection-job-slug-value="spring-dev-foo-102">
    <h3>Spring Developer</h3>
    <a href="/companies/foo">Foo Ltd</a>
    <div class="text-rich-grey">Ha Noi</div>
    <div class="text-rich-grey">Posted 2 days ago</div>
  </div>

  <div class="job-card" data-search--job-selection-job-slug-value="backend-java-acme-101">
    <h3>same job, repeated slot</h3>
  </div>
  <div class="ad">no slug here</div>
</div>
"""

DETAIL_HTML = """
<main>
  <h1>Backend Engineer (Java, Spring Boot)</h1>
  <div class="employer-name">ACME Corp</div>
  <a class="salary-report-link ifs-14">IT Salary Report 2024-2025</a>
  <div class="tag-list"><a>Java</a><a>Spring Boot</a><a>Java</a></div>
  <div class="job-description"><p>Build APIs.</p><ul><li>3+ yrs Java</li></ul></div>
</main>
"""


def test_parse_search_reads_cards_and_dedups_by_slug():
    hits = ITViecScraper().parse_search(SEARCH_HTML)
    assert len(hits) == 2  # repeated slug collapsed, ad ignored
    assert hits[0].native_id == "backend-java-acme-101"
    assert hits[0].url == "https://itviec.com/it-jobs/backend-java-acme-101"
    assert hits[0].title == "Backend Engineer (Java)"


def test_search_card_carries_company_location_and_posted():
    """The card is the trusted source; the detail page only fills gaps."""
    first, second = ITViecScraper().parse_search(SEARCH_HTML)
    # The company is linked twice — the logo anchor has no text and must lose.
    assert first.company == "ACME Corp"
    assert first.location == "Ho Chi Minh"
    assert first.posted_raw == "Posted 8 hours ago"
    assert second.company == "Foo Ltd"
    assert second.location == "Ha Noi"


def test_location_is_not_fooled_by_opacity_class():
    """`[class*=city]` matches `opacity-50` — that bug gave every ITviec job the
    location "Hiring". Location is matched on its value, not on class names."""
    hits = ITViecScraper().parse_search(SEARCH_HTML)
    assert hits[0].location != "Hiring"


def test_parse_detail_pulls_core_fields():
    hit = SearchHit(
        native_id="backend-java-acme-101",
        url="https://itviec.com/it-jobs/x",
        company="ACME Corp",
        location="Ho Chi Minh",
    )
    raw = ITViecScraper().parse_detail(DETAIL_HTML, hit)
    assert raw.id == "itviec:backend-java-acme-101"
    assert raw.title == "Backend Engineer (Java, Spring Boot)"
    assert raw.company == "ACME Corp"
    assert raw.location == "Ho Chi Minh"
    assert raw.skills == ["Java", "Spring Boot"]  # order preserved, deduped
    assert "Build APIs." in raw.description_html
    assert raw.apply_channel == "portal"
    assert raw.apply_target == hit.url


def test_salary_stays_empty_when_itviec_hides_it():
    """ITviec shows "Sign in to view salary" while logged out, and a promo link
    named "IT Salary Report" sits nearby. Neither is a salary."""
    hits = ITViecScraper().parse_search(SEARCH_HTML)
    assert hits[0].salary is None

    raw = ITViecScraper().parse_detail(DETAIL_HTML, hits[0])
    assert raw.salary is None
