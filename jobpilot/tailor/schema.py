"""The tailor plan — what the agent is allowed to return (SKILL.md §0-§3).

The plan is deliberately **index-based**: the agent reorders, hides, and selects
existing content by position, and the only free text it may write is the summary.
Fabricating a skill or a metric is therefore not a policy the agent is asked to
respect, it is a shape the schema cannot express. The one free-text field is
checked against the Master CV's vocabulary in ``tailor/guard.py``.

Indices always refer to the **Master CV** as rendered in the prompt outline
(``tailor/prompt.py``), never to intermediate state.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PLAN_VERSION = 1

RequirementKind = Literal["must_have", "nice_to_have", "soft"]
RequirementStatus = Literal["HAVE", "PARTIAL", "MISSING"]


class _Model(BaseModel):
    # Structured outputs require additionalProperties:false on every object.
    model_config = ConfigDict(extra="forbid")


class Requirement(_Model):
    """One requirement extracted from the JD, classified against the Master CV."""

    text: str = Field(description="The requirement, as stated in the job description.")
    kind: RequirementKind = Field(description="How strongly the JD asks for it.")
    status: RequirementStatus = Field(
        description="HAVE = present in the Master CV; PARTIAL = closely related "
        "experience exists; MISSING = not in the CV at all."
    )
    evidence: str = Field(
        default="",
        description="Where in the Master CV this is evidenced (section key and entry "
        "title). Must be empty when status is MISSING.",
    )


class EntryPlan(_Model):
    """Reordering inside one experience/project/education entry."""

    section_key: str = Field(description="Key of the section the entry belongs to.")
    entry_index: int = Field(description="Index of the entry in the Master CV outline.")
    bullet_order: list[int] = Field(
        default_factory=list,
        description="Master bullet indices in their new order. May drop indices to "
        "shorten. Empty means keep the original bullets unchanged.",
    )
    tech_stack_order: list[int] = Field(
        default_factory=list,
        description="Master tech-stack indices in their new order, most JD-relevant "
        "first. May drop indices. Empty means keep unchanged.",
    )


class SectionPlan(_Model):
    """Reordering and visibility for one section."""

    key: str = Field(description="Section key from the Master CV outline.")
    enabled: bool = Field(
        default=True,
        description="Set false to hide a low-relevance section so the CV stays one page.",
    )
    entry_order: list[int] = Field(
        default_factory=list,
        description="Master entry indices in their new order, most JD-relevant first. "
        "May drop indices. Empty means keep the original order.",
    )
    item_order: list[int] = Field(
        default_factory=list,
        description="For bullet sections (skills, honors): master item indices in their "
        "new order. Empty means keep the original order.",
    )


class Change(_Model):
    """One human-readable line for the review diff (SKILL.md §3)."""

    section: str = Field(description="Section key the change applies to.")
    what: str = Field(description="What changed, in one short sentence.")
    reason: str = Field(description="Which JD requirement motivated it.")


class TailorPlan(_Model):
    """The agent's complete, validated output for one job."""

    plan_version: int = PLAN_VERSION
    # No ge/le here: structured outputs don't support `minimum`/`maximum`, and a
    # slightly out-of-range score is a display glitch, not a reason to burn a
    # second API call — so it is clamped instead of rejected.
    match_score: float = Field(
        description="Weighted share of requirements satisfied, between 0 and 1: "
        "(HAVE + 0.5*PARTIAL) / total, with must_have weighted double.",
    )
    requirements: list[Requirement] = Field(
        default_factory=list, description="Every requirement found in the JD."
    )
    summary: str = Field(
        default="",
        description="Rewritten Summary section, 2-3 sentences, aimed at this role. "
        "Inline markup only (**bold**, `accent`). It may only mention technologies "
        "that already appear in the Master CV. Empty keeps the master summary.",
    )
    section_order: list[str] = Field(
        default_factory=list,
        description="All Master section keys in their new order. Empty keeps the "
        "original order.",
    )
    sections: list[SectionPlan] = Field(default_factory=list)
    entries: list[EntryPlan] = Field(default_factory=list)
    changes: list[Change] = Field(
        default_factory=list, description="Changes to show the user in the review diff."
    )

    @field_validator("match_score")
    @classmethod
    def _clamp_score(cls, value: float) -> float:
        return min(1.0, max(0.0, value))

    def gaps(self) -> list[Requirement]:
        """Requirements the CV genuinely cannot back up — surfaced, never papered over."""
        return [r for r in self.requirements if r.status == "MISSING"]

    def keywords(self) -> list[str]:
        """Requirement texts the CV does support — the ATS keywords worth emphasising."""
        return [r.text for r in self.requirements if r.status in ("HAVE", "PARTIAL")]
