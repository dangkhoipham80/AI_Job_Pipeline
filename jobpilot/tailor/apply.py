"""Turn a validated ``TailorPlan`` into a tailored ``CvDocument``.

Pure and deterministic: the same (master, plan) pair always yields the same
document, and the Master CV is never mutated. The plan is checked first, so a
document produced here can only contain content that was already in the master
(plus the summary, which passed the lexical guard).
"""

from __future__ import annotations

from jobpilot.cv.schema import CvDocument, ParagraphSection
from jobpilot.tailor.guard import check_plan
from jobpilot.tailor.schema import TailorPlan


def _reordered(values: list, order: list[int]) -> list:
    """Select + reorder by master index; an empty order keeps the list as-is."""
    return [values[i] for i in order] if order else list(values)


def apply_plan(master: CvDocument, plan: TailorPlan, *, validate: bool = True) -> CvDocument:
    """Return a new document with the plan applied. Raises on guardrail violations."""
    if validate:
        check_plan(plan, master).raise_if_bad()

    doc = master.model_copy(deep=True)
    section_plans = {sp.key: sp for sp in plan.sections}
    entry_plans: dict[tuple[str, int], list] = {}
    for ep in plan.entries:
        entry_plans.setdefault((ep.section_key, ep.entry_index), []).append(ep)

    for section in doc.sections:
        # Per-entry edits are keyed by the entry's *master* index, so they must be
        # applied before the section-level reorder shuffles those positions.
        entries = getattr(section, "entries", None)
        if entries is not None:
            for index, entry in enumerate(entries):
                for ep in entry_plans.get((section.key, index), []):
                    entry.items = _reordered(entry.items, ep.bullet_order)
                    if hasattr(entry, "tech_stack"):
                        entry.tech_stack = _reordered(entry.tech_stack, ep.tech_stack_order)

        sp = section_plans.get(section.key)
        if sp is None:
            continue
        section.enabled = sp.enabled
        if entries is not None:
            section.entries = _reordered(entries, sp.entry_order)
        items = getattr(section, "items", None)
        if items is not None:
            section.items = _reordered(items, sp.item_order)

    if plan.section_order:
        by_key = {s.key: s for s in doc.sections}
        doc.sections = [by_key[k] for k in plan.section_order]

    if plan.summary:
        target = next((s for s in doc.sections if isinstance(s, ParagraphSection)), None)
        if target is not None:
            target.text = plan.summary

    return doc
