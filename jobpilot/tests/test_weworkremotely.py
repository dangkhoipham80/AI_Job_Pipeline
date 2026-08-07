"""We Work Remotely parser contract, pinned against a trimmed real RSS feed.

Item shapes are copied from ``/categories/remote-programming-jobs.rss``: the
``<title>`` really is ``"Company: Job Title"``, descriptions really arrive as
escaped HTML, and titles really do start with an emoji. Each of those is a way
to store a wrong job while every test about *finding* jobs stays green.
"""

from __future__ import annotations

import pytest

from jobpilot.crawler.feed import parse_rss_items
from jobpilot.crawler.normalize import parse_posted_at
from jobpilot.crawler.weworkremotely import (
    FEEDS,
    WeWorkRemotelyScraper,
    split_company_title,
)

FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:media="http://search.yahoo.com/mrss">
  <channel>
    <title>We Work Remotely</title>
    <link>https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss</link>
    <item>
      <title>Gusto, Inc.: Senior Java Backend Engineer</title>
      <region>Anywhere in the World</region>
      <category>Back-End Programming</category>
      <description>&lt;p&gt;&lt;strong&gt;Headquarters:&lt;/strong&gt; San Francisco, CA&lt;/p&gt;
&lt;p&gt;Build Java services on Spring Boot.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;5 years&lt;/li&gt;&lt;/ul&gt;</description>
      <pubDate>Wed, 22 Jul 2026 07:00:51 +0000</pubDate>
      <link>https://weworkremotely.com/remote-jobs/gusto-inc-senior-java-backend-engineer</link>
      <guid>https://weworkremotely.com/remote-jobs/gusto-inc-senior-java-backend-engineer</guid>
    </item>
    <item>
      <title>MapTiler:  \U0001f30d Location Services Engineer | Maps Platform</title>
      <region>Europe Only</region>
      <category>Full-Stack Programming</category>
      <description>&lt;p&gt;Go and Rust.&lt;/p&gt;</description>
      <pubDate>Tue, 21 Jul 2026 09:10:00 +0000</pubDate>
      <link>https://weworkremotely.com/remote-jobs/maptiler-location-services-engineer?utm=rss</link>
      <guid>https://weworkremotely.com/remote-jobs/maptiler-location-services-engineer</guid>
    </item>
    <item>
      <title>Customer Success Manager</title>
      <region>USA Only</region>
      <category>Customer Support</category>
      <description>&lt;p&gt;Talk to people.&lt;/p&gt;</description>
      <pubDate>Mon, 20 Jul 2026 09:10:00 +0000</pubDate>
      <link>https://weworkremotely.com/remote-jobs/acme-customer-success-manager</link>
    </item>
    <item>
      <title>Broken: no link at all</title>
      <region>Anywhere in the World</region>
      <category>Back-End Programming</category>
      <description>&lt;p&gt;nothing&lt;/p&gt;</description>
    </item>
  </channel>
</rss>
"""


def _scraper() -> WeWorkRemotelyScraper:
    return WeWorkRemotelyScraper(fetcher=lambda url: FEED_XML)


# --------------------------------------------------------------------------- #
# title splitting — the trap that would rename every job
# --------------------------------------------------------------------------- #
def test_company_is_split_off_the_title():
    assert split_company_title("Gusto, Inc.: Business Money Engineering") == (
        "Gusto, Inc.",
        "Business Money Engineering",
    )


def test_only_the_first_colon_splits():
    """A role may contain a colon; splitting on the last one invents a company."""
    assert split_company_title("Cloudflare: Engineer: Platform") == (
        "Cloudflare",
        "Engineer: Platform",
    )


def test_title_without_a_colon_keeps_the_whole_title():
    """Missing company shows as missing rather than being guessed from the title."""
    assert split_company_title("Customer Success Manager") == ("", "Customer Success Manager")


def test_leading_emoji_is_stripped_but_tech_names_survive():
    assert split_company_title("MapTiler: \U0001f30d Maps Engineer")[1] == "Maps Engineer"
    assert split_company_title("Acme: .NET Developer")[1] == ".NET Developer"
    assert split_company_title("Acme: C++ Engineer")[1] == "C++ Engineer"


# --------------------------------------------------------------------------- #
# feed parsing
# --------------------------------------------------------------------------- #
def test_parse_search_reads_the_feed():
    hits = _scraper().parse_search(FEED_XML)
    # The item with no <link> has no stable id and is dropped, not guessed at.
    assert [h.native_id for h in hits] == [
        "gusto-inc-senior-java-backend-engineer",
        "maptiler-location-services-engineer",
        "acme-customer-success-manager",
    ]
    first = hits[0]
    assert first.title == "Senior Java Backend Engineer"
    assert first.company == "Gusto, Inc."
    assert first.location == "Anywhere in the World"


def test_tracking_query_is_stripped_from_the_url():
    hits = _scraper().parse_search(FEED_XML)
    assert (
        hits[1].url == "https://weworkremotely.com/remote-jobs/maptiler-location-services-engineer"
    )


def test_rfc822_pubdate_becomes_a_real_date():
    """RSS dates are RFC-822, not ISO. Without that, posted_at is silently None
    and a *feed* source — whose whole value is freshness — can never be fresh."""
    hits = _scraper().parse_search(FEED_XML)
    posted = parse_posted_at(hits[0].posted_raw)
    assert posted is not None
    assert (posted.year, posted.month, posted.day) == (2026, 7, 22)


def test_query_matching_uses_title_and_category_not_the_jd():
    scraper = _scraper()
    hits = scraper.parse_search(FEED_XML)
    java, maps, support = hits
    assert scraper.matches_query(java, "Java Spring Boot") is True
    # "Back-End Programming" is the category of the first item, so a backend
    # query keeps it even though the title never says "backend".
    assert scraper.matches_query(java, "Backend") is True
    assert scraper.matches_query(support, "Java Spring Boot") is False
    # Not matched on the description: the Go/Rust job must not answer a Java query.
    assert scraper.matches_query(maps, "Java") is False


def test_empty_query_keeps_everything():
    scraper = _scraper()
    hits = scraper.parse_search(FEED_XML)
    assert all(scraper.matches_query(h, "") for h in hits)


# --------------------------------------------------------------------------- #
# the crawl contract
# --------------------------------------------------------------------------- #
def test_crawl_needs_no_detail_request():
    """The feed is the whole job: 25 jobs must cost one request, not 26."""
    fetched: list[str] = []

    def fetcher(url: str) -> str:
        fetched.append(url)
        return FEED_XML

    scraper = WeWorkRemotelyScraper(fetcher=fetcher, max_pages=1)
    jobs = scraper.crawl("Java", limit=5)

    assert scraper.needs_detail is False
    assert fetched == ["https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss"]
    assert [j.title for j in jobs] == ["Senior Java Backend Engineer"]


def test_description_survives_into_the_job():
    jobs = WeWorkRemotelyScraper(fetcher=lambda url: FEED_XML, max_pages=1).crawl("Java", limit=1)
    job = jobs[0]
    assert "Spring Boot" in job.description_html
    assert job.apply_channel == "external"  # you submit it (principle 2)
    assert job.apply_target == job.url
    assert job.salary is None  # WWR publishes none — None, not ""


def test_pages_walk_distinct_category_feeds_then_stop():
    scraper = _scraper()
    urls = [scraper.search_url("java", p) for p in range(1, len(FEEDS) + 2)]
    assert len(set(urls[:-1])) == len(FEEDS)  # every feed distinct
    assert urls[0].endswith("remote-back-end-programming-jobs.rss")
    assert urls[-1] == ""  # past the last feed → the search loop stops


# --------------------------------------------------------------------------- #
# the RSS helper
# --------------------------------------------------------------------------- #
def test_rss_parser_strips_namespaces_and_reports_broken_xml():
    items = parse_rss_items(FEED_XML)
    assert len(items) == 4
    assert items[0]["region"] == "Anywhere in the World"
    with pytest.raises(Exception):
        parse_rss_items("<rss><channel><item>unclosed")
