"""Phase 3: ITviec parser contract, pinned against snapshot-shaped HTML.

Selectors are best-effort vs the live site; these tests lock the documented
parsing mechanism (the ``data-search--job-selection-job-url`` attribute and the
detail-page structure) so changes are deliberate.
"""

from __future__ import annotations

from jobpilot.crawler.itviec import ITViecScraper
from jobpilot.crawler.types import SearchHit

SEARCH_HTML = """
<div class="jobs">
  <div data-search--job-selection-job-url="/it-jobs/backend-java-acme-101">
    Backend Engineer (Java) - ACME
  </div>
  <div data-search--job-selection-job-url="/it-jobs/spring-dev-foo-102">
    Spring Developer - Foo
  </div>
  <div data-search--job-selection-job-url="/it-jobs/backend-java-acme-101">dup</div>
  <div class="ad">no job url here</div>
</div>
"""

DETAIL_HTML = """
<main>
  <h1>Backend Engineer (Java, Spring Boot)</h1>
  <div class="employer-name">ACME Corp</div>
  <div class="job-location">Ho Chi Minh City</div>
  <div class="salary-range">1000-2000 USD</div>
  <div class="tag-list"><a>Java</a><a>Spring Boot</a><a>Java</a></div>
  <div class="job-description"><p>Build APIs.</p><ul><li>3+ yrs Java</li></ul></div>
</main>
"""


def test_parse_search_extracts_job_urls_and_dedups():
    hits = ITViecScraper().parse_search(SEARCH_HTML)
    assert len(hits) == 2  # duplicate url collapsed, ad ignored
    assert hits[0].url == "https://itviec.com/it-jobs/backend-java-acme-101"
    assert hits[0].native_id == "backend-java-acme-101"


def test_parse_detail_pulls_core_fields():
    hit = SearchHit(native_id="backend-java-acme-101", url="https://itviec.com/it-jobs/x")
    raw = ITViecScraper().parse_detail(DETAIL_HTML, hit)
    assert raw.id == "itviec:backend-java-acme-101"
    assert raw.title == "Backend Engineer (Java, Spring Boot)"
    assert raw.company == "ACME Corp"
    assert raw.location == "Ho Chi Minh City"
    assert raw.salary == "1000-2000 USD"
    assert raw.skills == ["Java", "Spring Boot"]  # order preserved, deduped
    assert "Build APIs." in raw.description_html
    assert raw.apply_channel == "portal"
    assert raw.apply_target == hit.url
