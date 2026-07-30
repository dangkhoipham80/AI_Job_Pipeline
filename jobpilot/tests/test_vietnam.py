"""Value-based field recognition shared by the Vietnamese job boards.

These boards give the parser no reliable structural hook (CLAUDE.md "Bài học
selector"), so fields are recognised by their *content*. That makes the
recognisers themselves the load-bearing part, and every case below is one a
looser version of them got wrong.
"""

from __future__ import annotations

from jobpilot.crawler.vietnam import (
    CITIES,
    clean_city,
    find_city,
    find_posted,
    find_salary,
    is_noise,
    looks_like_city,
    parse_salary,
)


# --------------------------------------------------------------------------- #
# cities
# --------------------------------------------------------------------------- #
def test_city_must_account_for_the_whole_label():
    """A substring test makes "Remote" match any text containing it.

    ``"remote" in "remote debugging".lower()`` is True, so a skill tag became the
    job's location — and a wrong location looks right, unlike a missing one.
    """
    assert looks_like_city("Remote")
    assert not looks_like_city("remote debugging")
    assert not looks_like_city("working remotely")
    assert not looks_like_city("Remote support engineer")
    assert find_city(["Java", "remote debugging", "Hà Nội"]) == "Hà Nội"


def test_real_city_labels_are_recognised():
    for label in ("Hà Nội", "Hồ Chí Minh", "Ho Chi Minh", "TP. Hồ Chí Minh", "Hue City"):
        assert looks_like_city(label), label


def test_page_furniture_is_not_a_city():
    """The ITviec bug that started all of this: "Hiring" as every job's location."""
    for label in ("Hiring", "At office", "Sign in to view salary", "3 days ago", ""):
        assert not looks_like_city(label), label


def test_multi_city_postings_are_kept_but_mixed_lists_are_not():
    """Every comma-separated part must be a city, or the label is not a location."""
    assert looks_like_city("Hà Nội, Hồ Chí Minh")
    assert find_city(["Hà Nội, Hồ Chí Minh"]) == "Hà Nội, Hồ Chí Minh"
    assert not looks_like_city("Java, Spring Boot, Hà Nội")


def test_administrative_rename_annotation_is_stripped():
    """TopCV renders "Hồ Chí Minh (mới)" after the 2025 province merger."""
    assert clean_city("Hồ Chí Minh (mới)") == "Hồ Chí Minh"
    assert find_city(["Hồ Chí Minh (mới)"]) == "Hồ Chí Minh"
    assert clean_city("   ") is None


def test_city_list_covers_provinces_seen_in_real_crawls():
    """A missing province yields location=None, which reads as "remote" on the
    dashboard. A live crawl surfaced an FPT Software job in Khánh Hòa."""
    for province in ("Khánh Hòa", "Thái Nguyên", "Đắk Lắk", "Cần Thơ", "Huế"):
        assert province in CITIES, province


# --------------------------------------------------------------------------- #
# salary
# --------------------------------------------------------------------------- #
def test_negotiable_is_not_a_salary():
    for label in ("Thoả thuận", "Thương lượng", "Cạnh tranh", "Negotiable", "Competitive"):
        assert parse_salary(label) is None, label


def test_real_salaries_survive():
    assert parse_salary("15 - 25 triệu") == "15 - 25 triệu"
    assert parse_salary("$ 1,500-2,500 /tháng") == "$ 1,500-2,500 /tháng"
    assert parse_salary("Tới 24 triệu") == "Tới 24 triệu"
    assert parse_salary("Nhân viên kinh doanh") is None  # no money, no salary


def test_a_perks_blurb_does_not_swallow_the_real_figure():
    """ "Competitive salary package" can precede the actual number in document
    order. Hard-stopping on the word "competitive" discarded a salary the job
    did publish."""
    assert find_salary(["Competitive salary package", "$2,000 - $3,000 USD"]) == (
        "$2,000 - $3,000 USD"
    )


def test_a_login_wall_does_stop_the_scan():
    """ITviec hides the figure behind sign-in and puts an "IT Salary Report"
    promo nearby. That banner's number belongs to no job in particular, so the
    scan must stop rather than adopt it."""
    assert find_salary(["Sign in to view salary", "IT Salary Report: 30 - 50 triệu"]) is None
    assert find_salary(["Đăng nhập để xem lương", "20 triệu"]) is None


# --------------------------------------------------------------------------- #
# posted date
# --------------------------------------------------------------------------- #
def test_relative_dates_parse_with_or_without_the_ago_suffix():
    """Requiring "ago"/"trước" silently dropped the timestamp on cards that
    render a bare duration, making a fresh job look undated."""
    for label in (
        "Posted 8 hours ago",
        "8 hours",
        "3 days",
        "2 days ago",
        "3 ngày trước",
        "5 giờ",
        "hôm nay",
        "Cập nhật hôm nay",
        "yesterday",
        "30/07/2026",
    ):
        assert find_posted([label]) is not None, label


def test_non_dates_are_not_dates():
    for label in ("Hà Nội", "Java", "15 - 25 triệu", ""):
        assert find_posted([label]) is None, label


# --------------------------------------------------------------------------- #
# noise
# --------------------------------------------------------------------------- #
def test_social_proof_and_badges_are_noise():
    """LinkedIn's "34 company alumni" leaking into `location` was this bug."""
    for label in ("+3", "Mới", "Tin mới", "Nổi bật", "Rất đông ứng viên", "|", "Xem thêm"):
        assert is_noise(label), label


def test_real_values_are_not_noise():
    for label in ("Hà Nội", "Java", "15 - 25 triệu", "Cập nhật hôm nay", "One Mount"):
        assert not is_noise(label), label


def test_a_stated_figure_beats_a_negotiable_word_in_the_same_label():
    """TopCV writes "Cạnh tranh từ 15-25 triệu". Checking the word first threw
    away a range the employer did publish, and unlike the two-leaf case there is
    no later leaf to recover it from."""
    assert parse_salary("Cạnh tranh từ 15-25 triệu") == "Cạnh tranh từ 15-25 triệu"
    assert parse_salary("Thương lượng, 20 - 30 triệu") == "Thương lượng, 20 - 30 triệu"
    # Still no figure, still not a salary.
    assert parse_salary("Cạnh tranh") is None


def test_rename_annotation_is_stripped_mid_string_too():
    """`_CITY_SUFFIX_RE` is anchored to end-of-string, so in a multi-city label
    the "(mới)" sits mid-string and survives — which used to make the whole label
    fail to read as a location."""
    assert looks_like_city("Hà Nội (mới), Hồ Chí Minh")
    assert find_city(["Hà Nội (mới), Hồ Chí Minh"]) is not None
