"""What the crawled market looks like — and how much of it we actually saw.

Each aggregate returns a :class:`Facet`: the rows to plot, plus ``covered`` /
``total`` so the page can say "23 of 73 jobs list skills" instead of implying it
read the whole market. A chart cannot caveat itself; the data has to carry it.

Everything is computed in Python over the job payloads rather than in SQL. The
facets live in JSONB and the corpus is small (hundreds, not millions); a
readable loop beats six dialect-specific JSON operators, and if this ever grows
past what a loop can carry, the shape of these functions is what a SQL version
would have to reproduce anyway.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field

#: Below this many contributing jobs, the page shows counts and a warning
#: rather than a ranking. Same reasoning as ``llm/stats.MIN_SAMPLE``: a top-10
#: drawn from four ads is a list of four ads.
MIN_SAMPLE = 8


@dataclass
class Facet:
    """One chart's worth of data, with the honesty attached."""

    #: [{"key": str, "count": int, ...}], already sorted for display.
    rows: list[dict] = field(default_factory=list)
    #: Jobs that contributed a value to this facet.
    covered: int = 0
    #: Jobs considered in total.
    total: int = 0
    #: Set when the facet is too thin to read as a ranking.
    note: str = ""

    @property
    def coverage(self) -> float | None:
        """Share of jobs that had this field, or ``None`` with nothing to divide."""
        return round(self.covered / self.total, 3) if self.total else None

    def as_dict(self) -> dict:
        return {**asdict(self), "coverage": self.coverage}


def _facet(rows: list[dict], covered: int, total: int, what: str) -> Facet:
    note = ""
    if covered == 0:
        note = f"No job in the database has {what} yet."
    elif covered < MIN_SAMPLE:
        note = f"Only {covered} job(s) list {what} — too few to read as a ranking."
    return Facet(rows=rows, covered=covered, total=total, note=note)


def _payloads(db) -> list[dict]:
    from sqlalchemy import select

    from jobpilot.store.models import Job

    return [dict(p or {}) for p in db.scalars(select(Job.payload))]


# --------------------------------------------------------------------------- #
# facets
# --------------------------------------------------------------------------- #
def top_skills(payloads: list[dict], limit: int = 15) -> Facet:
    """Most frequently listed technologies, from the canonical form.

    Counted per job, not per mention, so one ad repeating a tag cannot outvote
    a second ad. Reads ``skills_canonical`` — the raw board tags rank ``+2`` and
    ``Vollzeit`` as technologies (see ``crawler/skills``).
    """
    counter: Counter[str] = Counter()
    covered = 0
    for p in payloads:
        skills = p.get("skills_canonical") or []
        if skills:
            covered += 1
            counter.update(set(skills))
    rows = [{"key": name, "count": n} for name, n in counter.most_common(limit)]
    return _facet(rows, covered, len(payloads), "skills")


def salary_bands(payloads: list[dict]) -> Facet:
    """Pay distribution in US dollars per month.

    One axis for ads quoted in different currencies and periods, which needs a
    conversion — so the number is an *estimate* and the UI says so, with the
    rate's date from ``crawler/salary.FX_CHECKED_ON``.
    """
    from jobpilot.crawler.salary import FX_CHECKED_ON, USD_VND_RATE

    bands = [(0, 500), (500, 1000), (1000, 2000), (2000, 3000), (3000, 5000), (5000, 10**9)]
    labels = ["<$500", "$500–1k", "$1k–2k", "$2k–3k", "$3k–5k", "$5k+"]
    counts = [0] * len(bands)
    values: list[float] = []

    for p in payloads:
        money = p.get("salary_range") or {}
        usd = money.get("usd_month")
        if usd is None:
            continue
        values.append(usd)
        for i, (lo, hi) in enumerate(bands):
            if lo <= usd < hi:
                counts[i] += 1
                break

    rows = [{"key": label, "count": n} for label, n in zip(labels, counts)]
    facet = _facet(rows, len(values), len(payloads), "a parsable salary")
    if values:
        ordered = sorted(values)
        facet.rows.append(
            {
                "key": "_summary",
                "count": len(values),
                "median_usd_month": round(ordered[len(ordered) // 2], 2),
                "min_usd_month": round(ordered[0], 2),
                "max_usd_month": round(ordered[-1], 2),
                "fx_rate": USD_VND_RATE,
                "fx_checked_on": FX_CHECKED_ON,
            }
        )
    return facet


def by_city(payloads: list[dict], limit: int = 12) -> Facet:
    """Jobs per recognised city, with remote counted as its own place."""
    counter: Counter[str] = Counter()
    covered = 0
    for p in payloads:
        if p.get("is_remote"):
            counter["Remote"] += 1
            covered += 1
            continue
        city = p.get("city")
        if city:
            counter[city] += 1
            covered += 1
    rows = [{"key": name, "count": n} for name, n in counter.most_common(limit)]
    return _facet(rows, covered, len(payloads), "a recognised location")


def by_level(payloads: list[dict]) -> Facet:
    """Seniority mix. ``level`` is inferred from the title and JD, so a job with
    neither — a LinkedIn alert — is unknown rather than junior."""
    order = ["intern", "fresher", "junior", "middle", "senior"]
    counter: Counter[str] = Counter()
    covered = 0
    for p in payloads:
        level = p.get("level")
        if level:
            counter[level] += 1
            covered += 1
    rows = [{"key": lv, "count": counter.get(lv, 0)} for lv in order if counter.get(lv)]
    return _facet(rows, covered, len(payloads), "an inferred level")


def match_score_histogram(payloads: list[dict]) -> Facet:
    """How well the crawled corpus matches your configured stacks.

    The one facet with full coverage: every job is scored at crawl time. A
    corpus clustered low means the crawl queries are off, not that the market
    is.
    """
    edges = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]
    labels = ["0–20%", "20–40%", "40–60%", "60–80%", "80–100%"]
    counts = [0] * len(edges)
    covered = 0
    for p in payloads:
        score = p.get("match_score")
        if score is None:
            continue
        covered += 1
        for i, (lo, hi) in enumerate(edges):
            if lo <= score < hi:
                counts[i] += 1
                break
    rows = [{"key": label, "count": n} for label, n in zip(labels, counts)]
    return _facet(rows, covered, len(payloads), "a match score")


def quality_flags(payloads: list[dict]) -> Facet:
    """How trustworthy the postings are. ``clean`` is jobs with no flag at all."""
    counter: Counter[str] = Counter()
    for p in payloads:
        flags = ((p.get("quality") or {}).get("flags")) or []
        if flags:
            counter.update(flags)
        else:
            counter["clean"] += 1
    rows = [{"key": name, "count": n} for name, n in counter.most_common()]
    # Every job lands in exactly one bucket or a flag, so coverage is total.
    return _facet(rows, len(payloads), len(payloads), "a quality signal")


def posting_calendar(payloads: list[dict], days: int = 30) -> Facet:
    """Ads per *posting* day.

    Deliberately ``posted_at``, not ``crawled_at``: the dashboard's existing
    by-day chart shows when *you* ran the crawler, which is a fact about your
    habits. This is a fact about the market.
    """
    counter: Counter[str] = Counter()
    covered = 0
    for p in payloads:
        posted = p.get("posted_at")
        if not posted:
            continue
        covered += 1
        counter[str(posted)[:10]] += 1
    rows = [{"key": day, "count": counter[day]} for day in sorted(counter)][-days:]
    return _facet(rows, covered, len(payloads), "a posting date")


def by_source(payloads: list[dict]) -> Facet:
    """Where the corpus came from — the denominator behind every other facet."""
    counter: Counter[str] = Counter(p.get("source", "?") for p in payloads)
    rows = [{"key": name, "count": n} for name, n in counter.most_common()]
    return _facet(rows, len(payloads), len(payloads), "a source")


def market_report(db) -> dict:
    """Every facet in one payload, so the page makes a single request."""
    payloads = _payloads(db)
    return {
        "total_jobs": len(payloads),
        "min_sample": MIN_SAMPLE,
        "skills": top_skills(payloads).as_dict(),
        "salary": salary_bands(payloads).as_dict(),
        "cities": by_city(payloads).as_dict(),
        "levels": by_level(payloads).as_dict(),
        "match_scores": match_score_histogram(payloads).as_dict(),
        "quality": quality_flags(payloads).as_dict(),
        "calendar": posting_calendar(payloads).as_dict(),
        "sources": by_source(payloads).as_dict(),
    }
