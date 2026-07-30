"""TopCV parser contract, pinned against snapshot-shaped HTML.

Trimmed from a live ``/tim-viec-lam-it`` page and one job page, keeping the parts
that mislead a naive parser: promo badges sharing the title's heading, a city
label annotated "(mới)", a per-session tracking token in the href, "Thoả thuận"
where a salary should be, and three identically-marked-up tag groups of which
only one is about the work.
"""

from __future__ import annotations

from jobpilot.crawler.topcv import TopCVScraper
from jobpilot.crawler.types import SearchHit

SEARCH_HTML = """
<div class="job-list-search-result">
  <div class="job-item-search-result job-ta" data-job-id="2254799"
       data-job-position="1" data-u-sr-id="NHEEUU03fqDp_1785412252">
    <div class="body-content">
      <h3 class="title highlight">
        <div class="box-label-top">
          <label class="label tag-new-job-label">Tin mới</label>
          <label class="label tag-highlight-label">Nổi bật</label>
        </div>
        <a class="highlight" target="_blank"
           href="https://www.topcv.vn/viec-lam/business-analyst-domain-crm-contract/2254799.html?ta_source=JobSearchList_LinkDetail&amp;u_sr_id=NHEEUU03fqDp_1785412252">
          <span title="Business Analyst (Domain CRM/Contract)">Business Analyst (Domain CRM/Contract)</span>
        </a>
      </h3>
      <a class="company" href="https://www.topcv.vn/cong-ty/cong-ty-co-phan-misa/198409.html">
        <span class="company-name" title="Công ty Cổ phần MISA">Công ty Cổ phần MISA</span>
      </a>
      <div class="box-right"><label class="title-salary">15 - 25 triệu</label></div>
      <div class="info"><div class="label-content">
        <label class="salary"><span>15 - 25 triệu</span></label>
        <label class="address truncate" data-html="true"
               title="&lt;div&gt;&lt;p&gt;Địa điểm làm việc đã được cập nhật theo Danh mục Hành chính mới&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Hà Nội&lt;/li&gt;&lt;/ul&gt;&lt;/div&gt;">
          <span class="city-text">Hà Nội</span>
        </label>
        <label class="exp"><span>2 năm</span></label>
      </div></div>
    </div>
  </div>

  <div class="job-item-search-result" data-job-id="1833111">
    <h3 class="title"><a href="/viec-lam/it-lead-manager/1833111.html?ta_source=x">
      <span title="IT Lead/Manager">IT Lead/Manager</span></a></h3>
    <span class="company-name" title="Công ty TNHH ITECHWX">Công ty TNHH ITECHWX</span>
    <label class="title-salary">Thoả thuận</label>
    <label class="address"><span class="city-text">Hồ Chí Minh (mới)</span></label>
  </div>

  <div class="job-item-search-result" data-job-id="2254799">
    <h3 class="title"><a href="/viec-lam/dup/2254799.html"><span title="dup">dup</span></a></h3>
  </div>
  <div class="job-item-search-result"><div class="ad">no anchor at all</div></div>
</div>
"""

DETAIL_HTML = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"JobPosting",
 "title":"Business Analyst (Domain CRM/Contract)",
 "description":"<h2>M\\u00f4 t\\u1ea3 c\\u00f4ng vi\\u1ec7c</h2><p>Ph\\u00e2n t\\u00edch nghi\\u1ec7p v\\u1ee5.</p><h2>Y\\u00eau c\\u1ea7u \\u1ee9ng vi\\u00ean</h2><ul><li>2 n\\u0103m kinh nghi\\u1ec7m</li></ul>",
 "identifier":{"@type":"PropertyValue","name":"C\\u00f4ng ty C\\u1ed5 ph\\u1ea7n MISA","value":198409},
 "datePosted":"2026-07-29",
 "hiringOrganization":{"@type":"Organization","name":"C\\u00f4ng ty C\\u1ed5 ph\\u1ea7n MISA"},
 "jobLocation":{"@type":"Place","address":{"@type":"PostalAddress",
   "addressLocality":"Ph\\u01b0\\u1ee3ng Xu\\u00e2n \\u0110\\u1ec9nh","addressRegion":"H\\u00e0 N\\u1ed9i"}},
 "baseSalary":{"@type":"MonetaryAmount","currency":"VND",
   "value":{"@type":"QuantitativeValue","unitText":"MONTH","minValue":15000000,"maxValue":25000000}}}
</script></head>
<body>
  <h1>Business Analyst (Domain CRM /Contract)</h1>
  <a class="name">Công ty Cổ phần MISA</a>
  <div class="job-tags__group">
    <div class="job-tags__group-name">Yêu cầu:</div>
    <div class="job-tags__group-list-tag"><span>2 năm kinh nghiệm chuyên môn</span>
      <span>Đại Học trở lên</span></div>
  </div>
  <div class="job-tags__group">
    <div class="job-tags__group-name">Quyền lợi:</div>
    <div class="job-tags__group-list-tag"><span>Bảo hiểm xã hội</span>
      <span>Team building</span><span>Du lịch hàng năm</span></div>
  </div>
  <div class="job-tags__group">
    <div class="job-tags__group-name">Chuyên môn:</div>
    <div class="job-tags__group-list-tag"><a>Business Analyst (Phân tích nghiệp vụ)</a>
      <a>IT - Phần mềm</a></div>
  </div>
  <div class="box-job-information-detail">DOM fallback body</div>
</body></html>
"""


def _hits():
    return TopCVScraper().parse_search(SEARCH_HTML)


def test_parse_search_reads_cards_dedups_and_skips_junk():
    hits = _hits()
    assert len(hits) == 2  # repeated job id collapsed, anchor-less card ignored
    assert hits[0].native_id == "2254799"
    assert hits[1].native_id == "1833111"


def test_title_excludes_the_promo_badges_in_its_heading():
    """`h3.title` also contains "Tin mới"/"Nổi bật"; reading the heading's text
    would title the job "Tin mới Nổi bật Business Analyst (…)"."""
    assert _hits()[0].title == "Business Analyst (Domain CRM/Contract)"


def test_url_drops_the_per_session_tracking_token():
    """`u_sr_id` is minted per search session — keeping it would churn the stored
    URL on every crawl and leak a session id into the DB and the apply hand-off."""
    url = _hits()[0].url
    assert url == "https://www.topcv.vn/viec-lam/business-analyst-domain-crm-contract/2254799.html"
    assert "u_sr_id" not in url and "ta_source" not in url


def test_relative_hrefs_become_absolute():
    assert _hits()[1].url == "https://www.topcv.vn/viec-lam/it-lead-manager/1833111.html"


def test_negotiable_salary_is_not_a_salary():
    """ "Thoả thuận" means TopCV is not disclosing — recording it as the salary
    would make the job look like it published one."""
    first, second = _hits()
    assert first.salary == "15 - 25 triệu"
    assert second.salary is None


def test_city_drops_the_administrative_rename_annotation():
    """TopCV appends "(mới)" after cities renamed by the 2025 merge."""
    assert _hits()[1].location == "Hồ Chí Minh"


def test_location_ignores_the_html_blob_in_the_title_attribute():
    """`label.address[title]` holds an escaped notice plus a <ul> of wards."""
    location = _hits()[0].location
    assert location == "Hà Nội"
    assert "Danh mục" not in location


def test_company_and_experience_come_off_the_card():
    first = _hits()[0]
    assert first.company == "Công ty Cổ phần MISA"
    assert first.extra == {"experience": "2 năm"}
    # A card without an experience label carries no empty key.
    assert _hits()[1].extra == {}


def test_card_extras_reach_the_raw_job():
    """`normalize` spreads ``RawJob.extra`` into the payload and reads nothing
    off the SearchHit, so a parse_detail that forgets to carry it forward drops
    the experience label from every TopCV job while the card-level test stays
    green."""
    raw = TopCVScraper().parse_detail(DETAIL_HTML, _hits()[0])
    assert raw.extra == {"experience": "2 năm"}


def test_parse_detail_uses_json_ld_for_the_facts():
    raw = TopCVScraper().parse_detail(DETAIL_HTML, _hits()[0])
    assert raw.id == "topcv:2254799"
    assert raw.title == "Business Analyst (Domain CRM/Contract)"
    assert raw.company == "Công ty Cổ phần MISA"
    assert raw.posted_raw == "2026-07-29"  # absolute date, not "3 ngày trước"
    assert raw.apply_channel == "portal"  # applying needs a TopCV login
    assert raw.apply_target == raw.url
    assert "Yêu cầu ứng viên" in raw.description_html  # the whole JD, not a blurb


def test_job_id_never_comes_from_the_json_ld_identifier():
    """`identifier.value` is 198409 — the *employer* id. Keyed on that, every
    MISA job would share one row."""
    raw = TopCVScraper().parse_detail(DETAIL_HTML, _hits()[0])
    assert raw.native_id == "2254799"
    assert "198409" not in raw.id


def test_benefits_are_not_skills():
    """Three tag groups share identical markup. Selecting tags without reading
    the group label makes "Team building" a skill, which then feeds match_score
    and shows up in the tailor gap report."""
    hit = SearchHit(native_id="2254799", url="https://www.topcv.vn/x")
    # Strip the JSON-LD so the DOM path is what runs.
    dom_only = DETAIL_HTML.split("</head>")[1]
    raw = TopCVScraper().parse_detail(dom_only, hit)
    assert raw.skills == ["Business Analyst (Phân tích nghiệp vụ)", "IT - Phần mềm"]
    for perk in ("Team building", "Bảo hiểm xã hội", "Du lịch hàng năm", "Đại Học trở lên"):
        assert perk not in raw.skills


def test_detail_falls_back_to_the_dom_without_json_ld():
    hit = SearchHit(native_id="2254799", url="https://www.topcv.vn/x", company="ACME")
    raw = TopCVScraper().parse_detail(DETAIL_HTML.split("</head>")[1], hit)
    assert raw.title == "Business Analyst (Domain CRM /Contract)"  # the <h1>
    assert "DOM fallback body" in raw.description_html


def test_search_url_puts_the_keyword_in_the_path():
    """`/tim-viec-lam-it?keyword=java` answers 200 with 50 cards and ignores the
    keyword entirely — it serves the generic IT category, so every result then
    scores 0 against the configured stacks and gets filtered away. The real
    search slugifies the keyword into the path."""
    scraper = TopCVScraper()
    assert scraper.search_url("Java Spring Boot") == (
        "https://www.topcv.vn/tim-viec-lam-java-spring-boot"
    )
    assert "keyword=" not in scraper.search_url("java")
    # Vietnamese diacritics fold to ASCII, matching TopCV's own slugs.
    assert scraper.search_url("Lập trình viên") == (
        "https://www.topcv.vn/tim-viec-lam-lap-trinh-vien"
    )
    # Punctuation collapses instead of breaking the path; empty falls back.
    assert scraper.search_url("C#/.NET  dev!") == "https://www.topcv.vn/tim-viec-lam-c-net-dev"
    assert scraper.search_url("") == "https://www.topcv.vn/tim-viec-lam-java"


def test_title_anchor_prefers_the_titled_heading_over_an_earlier_one():
    """`select_one("h3.title a, h3 a")` resolves by document order, so a promo
    widget rendered ahead of the real heading would supply both the title and the
    URL — storing the row under the wrong id."""
    html = """
    <div class="job-item-search-result" data-job-id="2254799">
      <div class="promo"><h3><a href="/viec-lam/promo/999.html">Sponsored promo</a></h3></div>
      <h3 class="title"><a href="/viec-lam/real-job/2254799.html">
        <span title="Real Java Developer">Real Java Developer</span></a></h3>
    </div>
    """
    (hit,) = TopCVScraper().parse_search(html)
    assert hit.title == "Real Java Developer"
    assert hit.url == "https://www.topcv.vn/viec-lam/real-job/2254799.html"
