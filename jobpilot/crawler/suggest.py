"""Crawl keywords suggested from the Master CV.

Typing a query by hand means guessing what you look like on paper. The CV
already says it: the technologies live in ``tech_stack`` lists and the Skills
section, and the roles live in experience entry titles. This reads those two
structured places rather than mining prose, so a suggestion is always something
you can actually back up in an interview.

Ranking is by how often a term appears across entries — a stack you used on
three projects is a better search than one you touched once — with roles kept
separate from technologies because they belong in different parts of a query.
"""

from __future__ import annotations

import re
from collections import Counter

from jobpilot.cv.schema import (
    BulletsSection,
    CvDocument,
    ExperienceSection,
    ProjectsSection,
)

# Terms that describe a person, not a searchable skill. Putting "Team Player"
# in a job query returns noise.
_STOP = {
    "and",
    "or",
    "the",
    "with",
    "using",
    "etc",
    "team player",
    "teamwork",
    "communication",
    "problem solving",
    "english",
    "soft skills",
    "agile",
    "scrum",
}

# Seniority words are filters, not search terms — a "Junior" in the query
# matches the word in the posting body, not the level of the job.
_SENIORITY = re.compile(r"^(junior|senior|middle|mid|fresher|intern|lead|principal|staff)\b", re.I)

# What makes a phrase a job title rather than a company name.
_ROLE_NOUN = re.compile(
    r"\b(engineer|developer|dev|programmer|architect|analyst|intern|consultant"
    r"|specialist|administrator|scientist|designer|tester|qa)\b",
    re.I,
)

# Skills sections list stacks as "Java, Spring Boot, PostgreSQL" behind a label.
_SPLIT = re.compile(r"\s*[,;/|·•]\s*|\s+and\s+", re.I)


def _clean(term: str) -> str:
    term = re.sub(r"\(.*?\)", " ", term)  # "Java (8/11/17)" -> "Java"
    term = re.sub(r"[*_`~]", "", term)  # strip inline markup
    return " ".join(term.split()).strip(" .,:;-")


def _usable(term: str) -> bool:
    if len(term) < 2 or len(term) > 32:
        return False
    if term.lower() in _STOP:
        return False
    # Whole sentences are bullet text that leaked in, not a skill.
    return len(term.split()) <= 4 and not term.endswith(".")


def _role_terms(title: str) -> list[str]:
    """Pull the job title out of an entry heading.

    Headings are written either way round — ``"FPT Software, Junior Software
    Engineer - Backend"`` or ``"Backend Engineer @ ACME"`` — so rather than
    assuming which side the company is on, this keeps the segment that contains
    an actual job noun. "FPT Software" has none; "Software Engineer" does.

    Seniority is dropped: a "Junior" in a search query matches the word in the
    posting body, not the level of the job.
    """
    for segment in re.split(r"\s*[,|@]\s*", title):
        if not _ROLE_NOUN.search(segment):
            continue
        role = _SENIORITY.sub("", _clean(segment)).strip(" -–")
        role = re.sub(r"\s*[-–]\s*", " ", role)  # "Engineer - Backend" -> "Engineer Backend"
        if _usable(role):
            return [role]
    return []


def suggest_keywords(doc: CvDocument, limit: int = 14) -> dict[str, list[str]]:
    """Technologies and roles worth searching for, most-supported first.

    Returns ``{"tech": [...], "roles": [...]}``. Empty lists are a truthful
    answer for an empty CV — better than inventing a default stack the user
    never claimed.
    """
    tech: Counter[str] = Counter()
    roles: Counter[str] = Counter()

    for section in doc.sections:
        if isinstance(section, (ExperienceSection, ProjectsSection)):
            for entry in section.entries:
                for raw in entry.tech_stack:
                    for part in _SPLIT.split(raw):
                        term = _clean(part)
                        if _usable(term):
                            tech[term] += 1
                if isinstance(section, ExperienceSection):
                    for role in _role_terms(entry.role or entry.title):
                        roles[role] += 1

        elif isinstance(section, BulletsSection):
            # Only a section that looks like Skills — otherwise Honors and
            # Certifications would flood the list with prose.
            if "skill" not in (section.key + section.title).lower():
                continue
            for item in section.items:
                for part in _SPLIT.split(item.text):
                    term = _clean(part)
                    if _usable(term):
                        tech[term] += 1

    # most_common is stable for ties, so equally-supported terms keep the order
    # they appear in the CV — which is the order you wrote them in, strongest
    # material first.
    return {
        "tech": [t for t, _ in tech.most_common(limit)],
        "roles": [r for r, _ in roles.most_common(4)],
    }
