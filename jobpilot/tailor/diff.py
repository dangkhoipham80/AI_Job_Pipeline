"""Structural diff between two CV documents (PLAN.md §5.6 CV Review).

Text diffing would be noisy here: the tailor mostly *moves* content, so a line
diff would report every bullet as changed. This walks the structure instead and
reports what actually happened — reordered, hidden, trimmed, rewritten — which is
what the reviewer needs in order to trust the result quickly.

Two callers, two vocabularies. Comparing Master → tailored, "hidden" means the
agent dropped a section *for this role*; comparing v3 → v7 of the same CV it just
means you switched the section off. The structural detection is identical, so
only the wording is parameterized — see ``DiffLabels``. Handing the tailor's
phrasing to a version diff would explain an edit you made by hand as a decision
the agent made for a job, which is the kind of confidently-wrong caption this
repo has been bitten by before.
"""

from __future__ import annotations

from pydantic import BaseModel, computed_field

from jobpilot.cv.schema import CvDocument, ParagraphSection, Section

# Section states, ordered by how much attention they deserve in the UI.
SectionStatus = str  # "rewritten" | "hidden" | "reordered" | "trimmed" | "unchanged"


class DiffLabels(BaseModel):
    """Phrases for the four structural events that need a human-readable note."""

    disabled: str
    enabled: str
    rewritten: str
    added: str
    removed: str


#: Master -> tailored, as the CV Review page reads it.
TAILOR_LABELS = DiffLabels(
    disabled="hidden from this CV to keep it to one page",
    enabled="shown in this CV",
    rewritten="summary rewritten for this role",
    added="new section",
    removed="removed from this CV",
)

#: Version N -> version M of one scope, as CV Studio's history reads it.
VERSION_LABELS = DiffLabels(
    disabled="section turned off",
    enabled="section turned on",
    rewritten="summary rewritten",
    added="section added",
    removed="section deleted",
)


class SectionDiff(BaseModel):
    key: str
    title: str
    status: SectionStatus
    notes: list[str] = []
    before: str | None = None  # only for rewritten prose
    after: str | None = None


class CvDiff(BaseModel):
    order_changed: bool = False
    order_before: list[str] = []
    order_after: list[str] = []
    sections: list[SectionDiff] = []

    @computed_field  # serialized, so the UI asks "did anything change?" once, here
    @property
    def changed(self) -> bool:
        return self.order_changed or any(s.status != "unchanged" for s in self.sections)


def _entry_labels(section: Section) -> list[str]:
    entries = getattr(section, "entries", None)
    if entries is None:
        return []
    return [getattr(e, "title", None) or getattr(e, "degree", "") for e in entries]


def _item_labels(section: Section) -> list[str]:
    items = getattr(section, "items", None)
    if items is None:
        return []
    return [(i.label or i.text)[:48] for i in items]


def _order_note(kind: str, before: list[str], after: list[str]) -> list[str]:
    """Describe a list change as dropped items and/or a new ordering."""
    notes: list[str] = []
    dropped = [x for x in before if x not in after]
    if dropped:
        notes.append(f"dropped {kind}: {', '.join(dropped)}")
    kept_before = [x for x in before if x in after]
    if kept_before != [x for x in after if x in before]:
        notes.append(f"reordered {kind}: {' → '.join(after)}")
    return notes


def _diff_section(before: Section, after: Section, labels: DiffLabels) -> SectionDiff:
    notes: list[str] = []
    status = "unchanged"
    out = SectionDiff(key=after.key, title=after.title, status=status)

    if before.enabled and not after.enabled:
        out.status = "hidden"
        out.notes = [labels.disabled]
        return out
    if not before.enabled and after.enabled:
        out.status = "reordered"
        out.notes = [labels.enabled]
        return out

    if isinstance(before, ParagraphSection) and isinstance(after, ParagraphSection):
        if before.text != after.text:
            out.status = "rewritten"
            out.before, out.after = before.text, after.text
            out.notes = [labels.rewritten]
        return out

    notes += _order_note("entries", _entry_labels(before), _entry_labels(after))
    notes += _order_note("items", _item_labels(before), _item_labels(after))

    # Entry-level bullet/stack edits, matched by title so a reordered section
    # still pairs the right entries up.
    before_entries = {
        lbl: e for lbl, e in zip(_entry_labels(before), getattr(before, "entries", []))
    }
    for lbl, entry in zip(_entry_labels(after), getattr(after, "entries", [])):
        original = before_entries.get(lbl)
        if original is None:
            continue
        notes += [f"{lbl}: {n}" for n in _order_note("bullets", original.items, entry.items)]
        old_stack = getattr(original, "tech_stack", [])
        new_stack = getattr(entry, "tech_stack", [])
        if old_stack != new_stack:
            notes += [f"{lbl}: {n}" for n in _order_note("tech stack", old_stack, new_stack)]

    if notes:
        out.status = "trimmed" if any("dropped" in n for n in notes) else "reordered"
        out.notes = notes
    return out


def diff_documents(
    master: CvDocument, tailored: CvDocument, labels: DiffLabels = TAILOR_LABELS
) -> CvDiff:
    """Compare the two documents section by section, matching on section key."""
    before_order = [s.key for s in master.sections]
    after_order = [s.key for s in tailored.sections]
    diff = CvDiff(
        order_changed=before_order != after_order,
        order_before=before_order,
        order_after=after_order,
    )

    by_key = {s.key: s for s in master.sections}
    for section in tailored.sections:
        original = by_key.get(section.key)
        if original is None:
            diff.sections.append(
                SectionDiff(
                    key=section.key, title=section.title, status="reordered", notes=[labels.added]
                )
            )
            continue
        diff.sections.append(_diff_section(original, section, labels))

    for key in by_key:
        if key not in after_order:
            diff.sections.append(
                SectionDiff(
                    key=key,
                    title=by_key[key].title,
                    status="hidden",
                    notes=[labels.removed],
                )
            )
    return diff
