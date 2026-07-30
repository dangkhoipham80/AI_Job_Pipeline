"""VietnamWorks parser contract, pinned against snapshot-shaped HTML.

Trimmed from a live rendered ``/viec-lam`` page and one job page. Two things
shape these tests:

* Every styling class on the real page is a build hash (``sc-1671001a-5 cjuZti``),
  so the fixtures keep only the semantic wrappers the parser is allowed to use.
  A test that leaned on a hash would pass today and rot on the next deploy.
* The cards mix real fields with social proof ("Rất đông ứng viên") and "+3" more
  indicators in the same text run — the shape that put "34 company alumni" into a
  LinkedIn job's ``location`` (CLAUDE.md).
"""

from __future__ import annotations

from jobpilot.crawler.types import SearchHit
from jobpilot.crawler.vietnamworks import VietnamWorksScraper

SEARCH_HTML = """
<div class="search-result-listJob">
  <div class="search_list view_job_item item-0 new-job-card">
    <div class="sc-fnLEGM lkWGQe">
      <a class="img_job_card" href="/ad-application-deveroper-2085932-jv?source=searchResults&amp;placement=2085932"
         title="AD Application Deveroper"><img alt="logo"/></a>
      <h2><a data-new-job="Mới" target="_blank"
             href="/ad-application-deveroper-2085932-jv?source=searchResults&amp;searchType=2&amp;placement=2085932&amp;sortBy=date">
        <span>Mới</span>AD Application Deveroper ( Chuyên Viên Phát Triển Ứng Dụng)</a></h2>
      <a href="/nha-tuyen-dung/fubon-life-insurance-vietnam-c123">Fubon Life Insurance (Vietnam) Co., Ltd</a>
      <span class="sc-x1">Thương lượng</span>
      <span class="sc-x2">Hà Nội</span>
      <span class="sc-x3">Cập nhật hôm nay</span>
      <span class="sc-x4">Java</span><span class="sc-x5">Python</span><span class="sc-x6">+3</span>
    </div>
  </div>

  <div class="search_list view_job_item item-1 new-job-card">
    <h2><a data-new-job="Mới" href="/solution-architect-finance-2077038-jv?source=searchResults">
      <span>Mới</span>Solution Architect (Finance)</a></h2>
    <a href="/nha-tuyen-dung/one-mount-c321984">One Mount</a>
    <span>$ 1,500-2,500 /tháng</span>
    <span>Hà Nội</span>
    <span>|</span>
    <span>Hãy là 1 trong 20 ứng viên đầu tiên</span>
    <span>Cập nhật hôm nay</span>
  </div>

  <div class="search_list view_job_item item-2 new-job-card">
    <h2><a href="/senior-software-engineer-2088154-jv">Senior Software Engineer</a></h2>
    <a href="/nha-tuyen-dung/vinsmart-c9">Công Ty Cổ Phần Vinsmart Future</a>
    <span>Hà Nội, Hồ Chí Minh</span>
    <span>Rất đông ứng viên</span>
  </div>

  <div class="new-job-card">
    <h2><a href="/ad-application-deveroper-2085932-jv?x=1">duplicate slot</a></h2>
  </div>
  <div class="new-job-card job-item-placeholder"><div>skeleton, no link</div></div>
</div>
"""

# The JSON-LD `description` holds only the responsibilities — VietnamWorks keeps
# "Yêu cầu công việc" out of it, so the DOM sections must win.
DETAIL_HTML = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"JobPosting",
 "title":"AD Application Deveroper ( Chuy\\u00ean Vi\\u00ean Ph\\u00e1t Tri\\u1ec3n \\u1ee8ng D\\u1ee5ng)",
 "description":"<p>Tham gia ph\\u00e1t tri\\u1ec3n l\\u1eadp tr\\u00ecnh ph\\u1ea7n m\\u1ec1m.</p>",
 "datePosted":"2026-07-23T10:28:43.000Z",
 "hiringOrganization":{"@type":"Organization","name":"Fubon Life Insurance (Vietnam) Co., Ltd"},
 "jobLocation":{"@type":"Place","address":{"@type":"PostalAddress",
   "addressLocality":"H\\u00e0 N\\u1ed9i","addressRegion":"H\\u00e0 N\\u1ed9i"}},
 "baseSalary":{"@type":"MonetaryAmount","currency":"USD",
   "value":{"@type":"QuantitativeValue","value":"Th\\u01b0\\u01a1ng l\\u01b0\\u1ee3ng","unitText":"HOUR"}},
 "skills":"Java, Python, MariaDB, Oracle, Java, MySQL",
 "identifier":{"@type":"PropertyValue","name":"Fubon Life","value":93664}}
</script></head>
<body>
  <h1>AD Application Deveroper ( Chuyên Viên Phát Triển Ứng Dụng)</h1>
  <div class="sc-1671001a-4 gDSEwb">
    <h2 class="sc-1671001a-5 cjuZti">Mô tả công việc</h2>
    <p>Tham gia phát triển lập trình phần mềm.</p>
  </div>
  <div class="sc-1671001a-4 gDSEwb">
    <h2 class="sc-1671001a-5 cjuZti">Yêu cầu công việc</h2>
    <ul><li>Tốt nghiệp Đại học CNTT</li><li>Thành thạo Java, Spring Boot</li></ul>
  </div>
</body></html>
"""


def _hits():
    return VietnamWorksScraper().parse_search(SEARCH_HTML)


def test_parse_search_reads_cards_dedups_and_skips_skeletons():
    hits = _hits()
    assert len(hits) == 3  # duplicate id collapsed, lazy-load skeleton ignored
    assert [h.native_id for h in hits] == ["2085932", "2077038", "2088154"]


def test_native_id_comes_from_the_jv_suffix():
    assert _hits()[0].url == "https://www.vietnamworks.com/ad-application-deveroper-2085932-jv"
    assert "source=searchResults" not in _hits()[0].url


def test_title_excludes_the_new_badge_inside_the_anchor():
    """The markup is `<a data-new-job="Mới"><span>Mới</span>Solution Architect</a>`,
    so the anchor's own text would read "Mới Solution Architect"."""
    assert _hits()[0].title == "AD Application Deveroper ( Chuyên Viên Phát Triển Ứng Dụng)"
    assert _hits()[1].title == "Solution Architect (Finance)"


def test_company_comes_from_the_employer_profile_link():
    assert _hits()[0].company == "Fubon Life Insurance (Vietnam) Co., Ltd"
    assert _hits()[1].company == "One Mount"


def test_negotiable_salary_is_none_but_a_real_one_survives():
    assert _hits()[0].salary is None  # "Thương lượng"
    assert _hits()[1].salary == "$ 1,500-2,500 /tháng"


def test_social_proof_never_becomes_a_field():
    """ "Hãy là 1 trong 20 ứng viên đầu tiên" and "Rất đông ứng viên" sit in the
    same text run as location and salary — the LinkedIn "34 company alumni" bug."""
    second, third = _hits()[1], _hits()[2]
    assert second.location == "Hà Nội"
    assert third.location == "Hà Nội, Hồ Chí Minh"  # multi-city kept
    for hit in _hits():
        for field in (hit.location, hit.salary, hit.company):
            assert field is None or "ứng viên" not in field


def test_more_indicator_is_not_mistaken_for_a_field():
    """A bare "+3" (more skills) must not land in location/salary/posted."""
    first = _hits()[0]
    assert first.posted_raw == "Cập nhật hôm nay"
    assert "+3" not in (first.location or "") and "+3" not in (first.salary or "")


def test_parse_detail_prefers_the_dom_jd_over_the_partial_json_ld():
    """JSON-LD `description` is responsibilities only; requirements live in the
    DOM. Tailoring against responsibilities alone misses what the CV must answer."""
    raw = VietnamWorksScraper().parse_detail(DETAIL_HTML, _hits()[0])
    assert "Yêu cầu công việc" in raw.description_html
    assert "Thành thạo Java, Spring Boot" in raw.description_html
    assert "Mô tả công việc" in raw.description_html


def test_jd_sections_are_found_without_touching_a_hashed_class():
    """The section wrapper's class is a build hash, so the heading text is the
    anchor. Renaming the hash must not empty the JD."""
    rehashed = DETAIL_HTML.replace("sc-1671001a-4 gDSEwb", "sc-99999999-7 zzZZzz").replace(
        "sc-1671001a-5 cjuZti", "sc-99999999-8 yyYYyy"
    )
    raw = VietnamWorksScraper().parse_detail(rehashed, _hits()[0])
    assert "Thành thạo Java, Spring Boot" in raw.description_html


def test_parse_detail_core_fields():
    raw = VietnamWorksScraper().parse_detail(DETAIL_HTML, _hits()[0])
    assert raw.id == "vietnamworks:2085932"
    assert raw.company == "Fubon Life Insurance (Vietnam) Co., Ltd"
    assert raw.location == "Hà Nội"
    assert raw.salary is None
    assert raw.posted_raw == "2026-07-23T10:28:43.000Z"
    assert raw.skills == ["Java", "Python", "MariaDB", "Oracle", "MySQL"]  # deduped
    # robots.txt disallows every apply route → the user submits (principle 2).
    assert raw.apply_channel == "portal"
    assert raw.apply_target == raw.url


def test_job_id_never_comes_from_the_json_ld_identifier():
    raw = VietnamWorksScraper().parse_detail(DETAIL_HTML, _hits()[0])
    assert raw.native_id == "2085932"
    assert "93664" not in raw.id


def test_detail_survives_a_page_with_no_json_ld():
    hit = SearchHit(
        native_id="2085932",
        url="https://www.vietnamworks.com/x-2085932-jv",
        title="From the card",
        company="Fubon",
        location="Hà Nội",
    )
    raw = VietnamWorksScraper().parse_detail(DETAIL_HTML.split("</head>")[1], hit)
    assert raw.title == "AD Application Deveroper ( Chuyên Viên Phát Triển Ứng Dụng)"  # the <h1>
    assert raw.company == "Fubon"
    assert "Yêu cầu công việc" in raw.description_html


def test_search_url_encodes_the_query():
    assert "q=java+spring" in VietnamWorksScraper().search_url("java spring")


def test_title_survives_being_wrapped_in_an_element():
    """Reading only the anchor's bare text nodes returns nothing once the title
    is wrapped (`<strong>…</strong>`), and the old fallback then handed back the
    badge-prefixed text — every job titled "Mới …"."""
    html = """
    <div class="new-job-card"><h2>
      <a data-new-job="Mới" href="/senior-backend-2099001-jv">
        <span>Mới</span><strong>Senior Backend Developer</strong></a>
    </h2></div>
    """
    (hit,) = VietnamWorksScraper().parse_search(html)
    assert hit.title == "Senior Backend Developer"
