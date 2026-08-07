"""Why a job scored what it scored, and whether the posting is worth answering.

Two complaints about the pipeline as it stood, both fair:

**"0.75 of what?"** ``match_score`` is a bare float, so a job that scores 0.25
and a job that scores 0.75 look like a judgement handed down with no reasons.
The score is computed from a list you configured, so the reasons are already
sitting there — :func:`stack_coverage` just names them. Nothing new is
calculated; the same arithmetic is reported instead of hidden.

**"Is this posting even real?"** Boards keep dead listings up: reqs filled
months ago, evergreen ads that never close, and postings with a title and
almost no description. Answering those costs a tailored CV and a cover letter
each. :func:`flags_for` marks them from data already in the payload.

Everything here is a pure function of a job's own fields — no network, no LLM,
no scoring model. That matters: a flag you cannot explain is one you cannot
argue with, and none of these flags *hide* a job. They annotate it and let the
person decide, the same way the crawler surfaces a gap rather than closing it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from jobpilot.timeutil import vn_now

#: A posting older than this has usually been filled or abandoned. Deliberately
#: generous: ATS boards carry genuinely open evergreen reqs for weeks.
DEFAULT_STALE_DAYS = 45

#: Below this, a "job description" is a headline. There is nothing for the
#: tailor to work from and nothing for you to answer.
THIN_JD_CHARS = 400


@dataclass
class Quality:
    """Signals about one job. All advisory — nothing here filters anything out."""

    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"matched": self.matched, "missing": self.missing, "flags": self.flags}


def stack_coverage(haystack: str, stacks: list[str]) -> tuple[list[str], list[str]]:
    """Split ``stacks`` into the ones this job mentions and the ones it doesn't.

    Matched case-insensitively on the raw substring, exactly as
    ``normalize.stack_match_score`` does. Reusing its rule rather than inventing
    a better one is the point: if the explanation disagreed with the number it
    explains, the explanation would be a second, competing score.
    """
    hay = (haystack or "").lower()
    matched = [s for s in stacks if s.lower() in hay]
    missing = [s for s in stacks if s.lower() not in hay]
    return matched, missing


def flags_for(
    *,
    description_md: str,
    posted_at: datetime | None,
    needs_jd: bool = False,
    now: datetime | None = None,
    stale_days: int = DEFAULT_STALE_DAYS,
) -> list[str]:
    """Reasons to look twice before spending a tailored CV on this posting."""
    now = now or vn_now()
    flags: list[str] = []

    if needs_jd:
        # LinkedIn alert emails carry a title and no description. Not the
        # posting's fault, but the tailor still has nothing to work from.
        flags.append("no_jd")
    elif len((description_md or "").strip()) < THIN_JD_CHARS:
        flags.append("thin_jd")

    if posted_at is None:
        # Distinct from `stale`: unknown age is not old age, and a source that
        # publishes no date shouldn't have its jobs quietly aged out.
        flags.append("undated")
    elif now - posted_at > timedelta(days=stale_days):
        flags.append("stale")

    return flags


def quality_for_payload(payload: dict, stacks: list[str], stale_days: int, now=None) -> Quality:
    """Recompute the signals from a stored job payload.

    Kept alongside the crawl-time path rather than replacing it: the score and
    its explanation are both snapshots of the moment the job was crawled, and
    if one were recomputed while the other stayed frozen they would eventually
    disagree — an explanation that contradicts the number it explains is worse
    than no explanation.
    """
    from jobpilot.crawler.normalize import parse_posted_at

    haystack = " ".join(
        [
            str(payload.get("title") or ""),
            " ".join(str(s) for s in (payload.get("skills") or [])),
            str(payload.get("description_md") or ""),
        ]
    )
    matched, missing = stack_coverage(haystack, stacks)
    return Quality(
        matched=matched,
        missing=missing,
        flags=flags_for(
            description_md=str(payload.get("description_md") or ""),
            posted_at=parse_posted_at(payload.get("posted_at"), now),
            needs_jd=bool(payload.get("needs_jd")),
            now=now,
            stale_days=stale_days,
        ),
    )


def backfill(session, cfg, *, now=None) -> int:
    """Attach signals to jobs crawled before this existed. Returns rows touched.

    Without it, every job already in the database stays unexplained forever —
    and the ones that need the flags most are exactly the ones that will never
    be re-crawled, like LinkedIn alerts that carry no description at all.
    """
    from sqlalchemy import select

    from jobpilot.store.models import Job

    touched = 0
    for job in session.scalars(select(Job)):
        payload = dict(job.payload or {})
        if payload.get("quality"):
            continue
        payload["quality"] = quality_for_payload(
            payload, cfg.crawl.stacks, cfg.crawl.stale_days, now
        ).as_dict()
        job.payload = payload
        touched += 1
    session.commit()
    return touched


def describe(flag: str) -> str:
    """One line a person can act on, for each flag."""
    return {
        "no_jd": "No description — paste the job description in before tailoring.",
        "thin_jd": "Very short description. There may not be enough here to tailor against.",
        "stale": "Posted a while ago; the role may already be filled.",
        "undated": "The source didn't publish a date, so freshness is unknown.",
    }.get(flag, flag)
