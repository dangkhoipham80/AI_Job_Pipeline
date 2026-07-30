"""Truthfulness guardrails for a tailor plan (SKILL.md §0).

Two layers:

1. **Structural** — every index in the plan must point at real Master CV content,
   with no duplicates. Because the plan can only reorder and drop, a structurally
   valid plan cannot introduce a skill, a metric, or an employer.
2. **Lexical** — the summary is the one free-text field. Any technology-looking
   token in it must already appear somewhere in the Master CV. Ordinary prose is
   left alone, so rewording stays possible while "also experienced with Kafka"
   does not.

Violations are returned rather than raised so the engine can feed them back to
the model for one corrective retry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from jobpilot.cv.schema import (
    BulletsSection,
    CvDocument,
    EducationSection,
    ExperienceSection,
    ParagraphSection,
    ProjectsSection,
)
from jobpilot.tailor.schema import TailorPlan


class GuardrailViolation(ValueError):
    """A plan that would put unsupported claims on the CV."""


# Words that look like a technology to the heuristic below but are ordinary English.
# Kept deliberately small: a false positive costs one retry, a false negative
# would let a fabricated skill onto the CV.
_ALLOWED_TERMS = frozenset("""
    i i'm my me english vietnamese vietnam a an the and or but for with without to from
    in on at by of as is are was were be been being have has had do does did will would
    can could should may might must not no yes if then than that this these those
    software engineer engineering developer development backend frontend fullstack full-stack
    system systems service services application applications platform platforms
    team teams project projects product production code coding clean architecture
    api apis rest restful microservice microservices database databases cloud devops
    test testing unit integration coverage pipeline pipelines deployment agile scrum
    experience experienced familiar comfortable focused building built build develop
    developed developing maintain maintained maintaining implement implemented
    design designed designing scalable reliable reliability quality performance
    computer science bachelor university graduate graduating fresher junior senior
    """.split())

# A token is "technology-looking" if it has an internal capital (PostgreSQL, JaCoCo),
# contains a digit or a tech punctuation mark (S3, C#, C++, Node.js), or is simply
# capitalised. Plain lowercase prose never trips the check.
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#._-]*")
_INTERNAL_CAPS = re.compile(r"[a-z][A-Z]")
_HAS_TECH_PUNCT = re.compile(r"[0-9+#]")


def _clean(token: str) -> str:
    """Drop trailing punctuation the token regex swallows (sentence-final ``Boot.``)
    while keeping it inside a name (``Node.js``, ``CI/CD`` halves, ``C++``)."""
    return token.rstrip("._-")


@dataclass
class PlanReport:
    """Outcome of checking a plan; ``ok`` means it is safe to apply."""

    violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def raise_if_bad(self) -> None:
        if self.violations:
            raise GuardrailViolation("; ".join(self.violations))


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #
def _iter_text(doc: CvDocument):
    h = doc.header
    yield from (h.first_name, h.last_name, h.position, h.address or "", h.quote or "")
    if h.extra_info:
        yield h.extra_info.label
    for s in doc.sections:
        yield s.title
        if isinstance(s, ParagraphSection):
            yield s.text
        elif isinstance(s, BulletsSection):
            for item in s.items:
                yield item.label or ""
                yield item.text
        elif isinstance(s, EducationSection):
            for e in s.entries:
                yield from (e.degree, e.institution, e.location, *e.items)
        elif isinstance(s, (ExperienceSection, ProjectsSection)):
            for e in s.entries:
                yield from (e.title, e.role or "", *e.items, *e.tech_stack)


def vocabulary(doc: CvDocument) -> set[str]:
    """Every word the Master CV actually contains, lowercased."""
    vocab: set[str] = set()
    for chunk in _iter_text(doc):
        for raw in _TOKEN_RE.findall(chunk or ""):
            token = _clean(raw)
            if not token:
                continue
            lowered = token.lower()
            vocab.add(lowered)
            # "CI/CD" and "Node.js" arrive as one token; also index the parts so a
            # summary saying "CI" or "Node" isn't flagged.
            vocab.update(p for p in re.split(r"[._-]", lowered) if p)
    return vocab


def _is_tech_looking(token: str, at_sentence_start: bool) -> bool:
    if _INTERNAL_CAPS.search(token) or _HAS_TECH_PUNCT.search(token):
        return True
    return token[:1].isupper() and not at_sentence_start


def unknown_terms(text: str, vocab: set[str]) -> list[str]:
    """Technology-looking tokens in ``text`` that the Master CV never mentions."""
    unknown: list[str] = []
    seen: set[str] = set()
    for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
        for i, m in enumerate(_TOKEN_RE.finditer(sentence)):
            token = _clean(m.group())
            if not token:
                continue
            lowered = token.lower()
            if lowered in vocab or lowered in _ALLOWED_TERMS or lowered in seen:
                continue
            if _is_tech_looking(token, at_sentence_start=i == 0):
                seen.add(lowered)
                unknown.append(token)
    return unknown


# --------------------------------------------------------------------------- #
# Plan checking
# --------------------------------------------------------------------------- #
def _check_order(order: list[int], size: int, label: str, out: list[str]) -> None:
    """An order must be a duplicate-free subset of the master indices."""
    if not order:
        return
    if len(set(order)) != len(order):
        out.append(f"{label}: duplicate indices {order}")
    bad = [i for i in order if not 0 <= i < size]
    if bad:
        out.append(f"{label}: indices {bad} out of range (0..{size - 1})")


def check_plan(plan: TailorPlan, master: CvDocument) -> PlanReport:
    """Validate a plan against the Master CV. Empty violations means safe to apply."""
    out: list[str] = []
    by_key = {s.key: s for s in master.sections}

    if plan.section_order:
        unknown_keys = [k for k in plan.section_order if k not in by_key]
        if unknown_keys:
            out.append(f"section_order: unknown section keys {unknown_keys}")
        if len(set(plan.section_order)) != len(plan.section_order):
            out.append("section_order: duplicate section keys")
        missing = set(by_key) - set(plan.section_order)
        if missing:
            out.append(f"section_order: must list every section, missing {sorted(missing)}")

    for sp in plan.sections:
        section = by_key.get(sp.key)
        if section is None:
            out.append(f"sections: unknown section key {sp.key!r}")
            continue
        entries = getattr(section, "entries", None)
        items = getattr(section, "items", None)
        if sp.entry_order:
            if entries is None:
                out.append(f"sections[{sp.key}]: entry_order on a section with no entries")
            else:
                _check_order(sp.entry_order, len(entries), f"sections[{sp.key}].entry_order", out)
        if sp.item_order:
            if items is None:
                out.append(f"sections[{sp.key}]: item_order on a section with no items")
            else:
                _check_order(sp.item_order, len(items), f"sections[{sp.key}].item_order", out)

    for ep in plan.entries:
        section = by_key.get(ep.section_key)
        entries = getattr(section, "entries", None) if section else None
        if entries is None:
            out.append(f"entries: {ep.section_key!r} is not a section with entries")
            continue
        if not 0 <= ep.entry_index < len(entries):
            out.append(
                f"entries[{ep.section_key}]: entry_index {ep.entry_index} out of range "
                f"(0..{len(entries) - 1})"
            )
            continue
        entry = entries[ep.entry_index]
        label = f"entries[{ep.section_key}#{ep.entry_index}]"
        _check_order(ep.bullet_order, len(entry.items), f"{label}.bullet_order", out)
        stack = getattr(entry, "tech_stack", [])
        _check_order(ep.tech_stack_order, len(stack), f"{label}.tech_stack_order", out)
        if ep.tech_stack_order and not stack:
            out.append(f"{label}: tech_stack_order on an entry with no tech stack")

    if plan.summary:
        invented = unknown_terms(plan.summary, vocabulary(master))
        if invented:
            out.append(
                "summary mentions technologies absent from the Master CV: "
                + ", ".join(invented)
                + " — remove them (SKILL.md §0: never claim a skill the CV cannot back up)"
            )

    for req in plan.requirements:
        if req.status == "MISSING" and req.evidence.strip():
            out.append(f"requirement {req.text!r}: MISSING must not cite evidence")

    return PlanReport(violations=out)
