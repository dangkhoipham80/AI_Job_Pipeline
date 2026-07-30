"""schema.org ``JobPosting`` extraction — pinned against real-world shapes.

Every fixture here is trimmed from a live TopCV or VietnamWorks page. The values
that look absurd (a currency of USD on an hourly "Thương lượng", an
``identifier`` that is the employer's id, ``Java`` listed twice) are quoted
verbatim from those pages — they are exactly what the parser has to survive.
"""

from __future__ import annotations

from jobpilot.crawler.jsonld import find_job_posting, parse_job_posting

# TopCV: the JD is complete here, salary is a real VND range, and `identifier`
# is the *company* id — 198409 also appears in the employer's own URL.
TOPCV_LD = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[]}
</script>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"JobPosting",
 "title":"Business Analyst (Domain CRM/Contract)",
 "description":"<h2>M\\u00f4 t\\u1ea3 c\\u00f4ng vi\\u1ec7c</h2><p>Build things.</p>",
 "identifier":{"@type":"PropertyValue","name":"C\\u00f4ng ty C\\u1ed5 ph\\u1ea7n MISA","value":198409},
 "datePosted":"2026-07-29",
 "employmentType":"FULL_TIME",
 "hiringOrganization":{"@type":"Organization","name":"C\\u00f4ng ty C\\u1ed5 ph\\u1ea7n MISA",
   "sameAs":"https://www.topcv.vn/cong-ty/cong-ty-co-phan-misa/198409.html"},
 "jobLocation":{"@type":"Place","address":{"@type":"PostalAddress",
   "streetAddress":"To\\u00e0 N03T2","addressLocality":"Ph\\u01b0\\u1ee3ng Xu\\u00e2n \\u0110\\u1ec9nh",
   "addressRegion":"H\\u00e0 N\\u1ed9i","addressCountry":"VN"}},
 "baseSalary":{"@type":"MonetaryAmount","currency":"VND",
   "value":{"@type":"QuantitativeValue","unitText":"MONTH","minValue":15000000,"maxValue":25000000}}}
</script>
</head><body></body></html>
"""

# VietnamWorks: "negotiable" parked in a numeric slot, and a duplicated skill.
VNW_LD = """
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"JobPosting",
 "title":"AD Application Deveroper",
 "description":"<p>Maintain systems.</p>",
 "datePosted":"2026-07-23T10:28:43.000Z",
 "hiringOrganization":{"@type":"Organization","name":"Fubon Life Insurance (Vietnam) Co., Ltd"},
 "jobLocation":{"@type":"Place","address":{"@type":"PostalAddress",
   "addressLocality":"H\\u00e0 N\\u1ed9i","addressRegion":"H\\u00e0 N\\u1ed9i"}},
 "baseSalary":{"@type":"MonetaryAmount","currency":"USD",
   "value":{"@type":"QuantitativeValue","value":"Th\\u01b0\\u01a1ng l\\u01b0\\u1ee3ng","unitText":"HOUR"}},
 "skills":"Java, Python, MariaDB, Oracle, Java, MySQL",
 "identifier":{"@type":"PropertyValue","name":"Fubon Life","value":93664}}
</script>
"""


def test_finds_the_job_posting_past_other_blocks():
    """Pages carry several JSON-LD blocks; the type is matched, not the position."""
    obj = find_job_posting(TOPCV_LD)
    assert obj is not None
    assert obj["@type"] == "JobPosting"


def test_no_job_posting_returns_none():
    assert find_job_posting("<html><body>nothing here</body></html>") is None
    assert parse_job_posting("<html></html>") is None


def test_malformed_block_does_not_lose_the_posting():
    """A broken script tag is skipped rather than aborting the parse."""
    html = '<script type="application/ld+json">{"@type":"JobPosting", oops</script>' + TOPCV_LD
    posting = parse_job_posting(html)
    assert posting is not None
    assert posting.title == "Business Analyst (Domain CRM/Contract)"


def test_graph_wrapped_posting_is_found():
    html = """
    <script type="application/ld+json">
    {"@context":"https://schema.org","@graph":[
      {"@type":"WebSite","name":"x"},
      {"@type":"JobPosting","title":"Wrapped Role"}]}
    </script>
    """
    posting = parse_job_posting(html)
    assert posting is not None and posting.title == "Wrapped Role"


def test_identifier_is_the_employer_never_the_job():
    """`identifier` is the company id — 198409 matches the employer's own URL.

    Using it as ``native_id`` would collapse every job from one company into a
    single row and make each crawl overwrite the last, so it is surfaced under a
    name that says what it is and the scrapers take ids from the URL instead.
    """
    posting = parse_job_posting(TOPCV_LD)
    assert posting is not None
    assert posting.employer_id == "198409"
    assert "198409" in TOPCV_LD.split('"sameAs":"')[1]  # it is the company URL id
    assert not hasattr(posting, "native_id")


def test_salary_range_is_formatted_with_currency_and_unit():
    posting = parse_job_posting(TOPCV_LD)
    assert posting is not None
    assert posting.salary == "15,000,000 - 25,000,000 VND/month"


def test_negotiable_salary_in_a_numeric_slot_is_not_a_salary():
    """VietnamWorks sends value="Thương lượng" with currency USD, unit HOUR.

    Coercing that would invent "0 USD/hour" for a job that disclosed nothing.
    """
    posting = parse_job_posting(VNW_LD)
    assert posting is not None
    assert posting.salary is None


def test_region_wins_over_locality_for_the_city():
    """TopCV puts the ward in addressLocality and the city in addressRegion."""
    assert parse_job_posting(TOPCV_LD).location == "Hà Nội"  # not "Phường Xuân Đỉnh"
    assert parse_job_posting(VNW_LD).location == "Hà Nội"  # both fields agree here


def test_skills_string_is_split_and_deduped():
    posting = parse_job_posting(VNW_LD)
    assert posting is not None
    assert posting.skills == ["Java", "Python", "MariaDB", "Oracle", "MySQL"]


def test_multi_location_postings_keep_every_city():
    html = """
    <script type="application/ld+json">{"@type":"JobPosting","title":"t",
     "jobLocation":[{"@type":"Place","address":{"addressRegion":"H\\u00e0 N\\u1ed9i"}},
                    {"@type":"Place","address":{"addressRegion":"H\\u1ed3 Ch\\u00ed Minh"}},
                    {"@type":"Place","address":{"addressRegion":"H\\u00e0 N\\u1ed9i"}}]}</script>
    """
    assert parse_job_posting(html).location == "Hà Nội, Hồ Chí Minh"


def test_core_fields_and_absolute_date():
    """The absolute datePosted is a reason to prefer JSON-LD over "3 ngày trước"."""
    topcv = parse_job_posting(TOPCV_LD)
    vnw = parse_job_posting(VNW_LD)
    assert topcv.company == "Công ty Cổ phần MISA"
    assert topcv.posted_raw == "2026-07-29"
    assert topcv.employment_type == "FULL_TIME"
    assert "Build things." in topcv.description_html
    assert vnw.company == "Fubon Life Insurance (Vietnam) Co., Ltd"
    assert vnw.posted_raw == "2026-07-23T10:28:43.000Z"


def test_open_ended_ranges():
    def salary(base: str) -> str | None:
        html = f'<script type="application/ld+json">{{"@type":"JobPosting","baseSalary":{base}}}</script>'
        return parse_job_posting(html).salary

    assert salary('{"currency":"VND","value":{"minValue":20000000,"unitText":"MONTH"}}') == (
        "from 20,000,000 VND/month"
    )
    assert salary('{"currency":"USD","value":{"maxValue":3000,"unitText":"MONTH"}}') == (
        "up to 3,000 USD/month"
    )
    # An unknown unit must not invent a suffix.
    assert salary('{"currency":"USD","value":{"value":2500,"unitText":"FORTNIGHT"}}') == "2,500 USD"
