"""Making board tag-lists comparable enough to count.

Every board writes its own tags and JobPilot stored them verbatim, which is
right for provenance and useless for counting. Left raw, "most in-demand skill"
adds up ``Spring`` and ``Spring Boot`` as different things, ranks ``+2`` — an
ITviec card's overflow badge — as a technology, and treats ``Vollzeit``
(German for "full-time") as a skill.

So: a canonical form for counting, kept **beside** the raw list, never replacing
it. The raw tags are what the board actually said, and that is evidence.

The honest limit, stated because a chart cannot state it for itself: LinkedIn
supplies **no** tags at all, and LinkedIn is the largest source in this database.
Any ranking built here describes the boards that tag, not the market. Callers
must publish the sample size next to the ranking — see
``analytics/market.top_skills``.
"""

from __future__ import annotations

import re

#: Card UI overflow badges: "+1", "+2", "+12". Not technologies.
_OVERFLOW = re.compile(r"^\+\s*\d+$")

#: A **role**, not a skill: "backend developer", "software engineer". Boards put
#: these in the same tag strip as technologies, and they rank high enough to
#: crowd out the actual stack.
#:
#: Matched as whole words, and on the singular noun only, so the *discipline*
#: survives: "software engineer" goes, "data engineering" and "ai engineering"
#: stay. That distinction is the whole reason this is a regex and not a list.
_ROLE_RE = re.compile(
    r"\b(developer|engineer|programmer|architect|analyst|manager|specialist|consultant)\b",
    re.I,
)

#: An industry the employer operates in, which several boards also file as a
#: "skill": "IT Services and IT Consulting", "Financial Services".
#:
#: The bare word ``services`` is not enough, and getting that wrong cost a real
#: entry: it is a substring of **microservices**, so one of the most common tags
#: on the market was dropped from every ranking — silently, with the chart still
#: rendering perfectly and all 658 tests green. Same shape as ``"remote" in
#: "remote debugging"`` and ``intern`` inside ``internal``, both of which this
#: repo has already paid for. So the industry sense is matched as a *phrase*,
#: which also lets "web services" survive as the technology it is.
_INDUSTRY_RE = re.compile(
    r"\b(?:it|financial|professional|business|consumer|software development)\s+services\b"
    r"|consulting|\bindustry\b|phần mềm|outsourcing",
    re.I,
)

#: Places. A tag strip that includes "India" is describing the office, not the
#: work. Small and unapologetically incomplete — it removes the cases actually
#: seen rather than pretending to know every place name.
_PLACES = {"india", "vietnam", "singapore", "japan", "usa", "us", "uk", "germany", "europe"}

#: Tags that are employment terms, industries or soft labels rather than
#: technologies. Counting them buries the actual stack under noise.
_NOT_A_SKILL = {
    "vollzeit",
    "teilzeit",
    "full time",
    "full-time",
    "part time",
    "part-time",
    "remote",
    "hybrid",
    "onsite",
    "on-site",
    "internship",
    "freelance",
    "contract",
    "permanent",
    "engineering",
    "software development outsourcing",
    # Bare role fragments a board renders when the tag is truncated.
    "dev",
    "backend",
    "frontend",
    "fullstack",
    "full stack",
    "product",
    "banking",
    "consumer goods",
    "e-commerce",
    "fintech",
    "leadership",
    "communication",
    "teamwork",
    "english",
}

#: Written many ways, meaning one thing. Left side is already lowercased and
#: whitespace-collapsed. Kept deliberately small: every entry is a judgement
#: call, and a huge map becomes its own source of wrong answers.
_ALIASES = {
    "reactjs": "react",
    "react.js": "react",
    "react js": "react",
    "nodejs": "node.js",
    "node js": "node.js",
    "vuejs": "vue",
    "vue.js": "vue",
    "spring boot": "spring",
    "springboot": "spring",
    "postgres": "postgresql",
    "golang": "go",
    "k8s": "kubernetes",
    "js": "javascript",
    "ts": "typescript",
    "c #": "c#",
    "dotnet": ".net",
    ".net core": ".net",
    "ms sql": "sql server",
    "mssql": "sql server",
    "restful api": "rest",
    "restful": "rest",
    "rest api": "rest",
    "ci cd": "ci/cd",
    "cicd": "ci/cd",
}


def canonical(tag: str) -> str | None:
    """One tag, normalised — or ``None`` if it should not be counted."""
    text = re.sub(r"\s+", " ", (tag or "").strip().lower())
    if not text or _OVERFLOW.match(text):
        return None
    text = text.strip(" .,;/")
    if not text or text in _NOT_A_SKILL or text in _PLACES:
        return None
    if _ROLE_RE.search(text) or _INDUSTRY_RE.search(text):
        return None
    # A tag long enough to be a sentence is a job description fragment, not a
    # skill — the same reasoning as `MAX_SALARY_LEN`.
    if len(text) > 40:
        return None
    return _ALIASES.get(text, text)


def canonicalise(tags: list[str] | None) -> list[str]:
    """Canonical skills for one job, de-duplicated, order preserved.

    Order is kept because boards list the important tag first often enough to
    be worth something, and de-duplication is per job so one ad shouting
    "Java, java, JAVA" counts once.
    """
    seen: set[str] = set()
    out: list[str] = []
    for tag in tags or []:
        name = canonical(tag)
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out
