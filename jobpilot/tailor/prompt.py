"""Prompt construction for the tailor agent.

The Master CV is rendered as an **indexed outline** because the plan schema
addresses content by position (``tailor/schema.py``). The indices printed here
are the contract: ``entry[2]``/``bullet[0]``/``tech[3]`` in the outline are
exactly what ``entry_index``/``bullet_order``/``tech_stack_order`` refer to.

Split by stability so the prompt caches well once the Master CV is large enough:
the rules + outline go in ``system`` (same for every job), the JD goes in the
user turn (different every job).
"""

from __future__ import annotations

from jobpilot.cv.schema import (
    BulletsSection,
    CvDocument,
    EducationSection,
    ExperienceSection,
    ParagraphSection,
    ProjectsSection,
)
from jobpilot.store.models import Job
from jobpilot.tailor.schema import TailorPlan

# Encodes SKILL.md §0 (truthfulness) and §2 (the five steps). Kept in the prompt
# rather than read from SKILL.md at runtime so the wording the model sees is
# reviewed alongside the schema it has to satisfy.
RULES = """\
You tailor a software engineer's CV to one specific job posting.

# The one rule that overrides everything
Never claim a skill, technology, employer, metric, or achievement that is not
already in the Master CV below. You may re-order, emphasise, drop, and re-word;
you may not add. If the job wants something the candidate does not have, record
it as a MISSING requirement — that is useful, honest information for them. Do
not smuggle it onto the CV, and do not infer adjacent skills ("uses Spring Boot,
so probably knows Hibernate" is a fabrication).

# What you return
A plan that edits the Master CV **by index**. You cannot write CV content except
the summary, so most of your work is deciding what to promote and what to hide.

- `requirements`: every requirement you find in the job description, each marked
  must_have / nice_to_have / soft, and classified HAVE (the CV shows it),
  PARTIAL (the CV shows something equivalent, e.g. JD says "RESTful
  microservices" and the CV has "RESTful APIs" plus "microservices"), or MISSING.
  Cite `evidence` (section key + entry title) for HAVE and PARTIAL; leave it
  empty for MISSING.
- `match_score`: (HAVE + 0.5 x PARTIAL) / total, counting must_have twice.
- `summary`: rewrite the Summary in 2-3 sentences aimed at this role, using the
  job's vocabulary **only where the CV already supports it**. Every technology
  you name must appear somewhere in the Master CV. Keep it one paragraph.
- `section_order`: list every section key, most relevant to this job first.
  Education and honors usually stay where they are.
- `sections`: set `enabled: false` on a section only if the CV would otherwise
  run past one page. Use `entry_order` / `item_order` to put the most relevant
  entries and skill lines first; dropping an index removes that entry entirely.
- `entries`: within an entry, `bullet_order` promotes the bullets that match the
  job (and may drop the least relevant ones), and `tech_stack_order` puts the
  technologies the job asks for at the front.
- `changes`: one short line per edit, each naming the requirement that motivated
  it. This is what the human reads before approving, so make it specific:
  "Slide AI moved to first project" beats "reordered projects".

Leave a list empty when you would not change that thing. An empty plan is a
valid answer for a job that already matches the CV as written.

# Formatting inside the summary
Plain text with a small markup subset: `**bold**` for emphasis and backticks
around a technology name to give it the CV's accent colour. No LaTeX, no
markdown headings, no bullet points.
"""


def render_master(doc: CvDocument) -> str:
    """The Master CV as an indexed outline — the address space for the plan."""
    lines: list[str] = ["MASTER CV", ""]
    for section in doc.sections:
        state = "" if section.enabled else "  [currently hidden]"
        lines.append(
            f'SECTION {section.key}  (type={section.type}, title="{section.title}"){state}'
        )

        if isinstance(section, ParagraphSection):
            lines.append(f"  text: {section.text}")
        elif isinstance(section, BulletsSection):
            for i, item in enumerate(section.items):
                label = f"{item.label}: " if item.label else ""
                date = f"   [{item.date}]" if item.date else ""
                lines.append(f"  item[{i}] {label}{item.text}{date}")
        elif isinstance(section, EducationSection):
            for i, e in enumerate(section.entries):
                lines.append(f"  entry[{i}] {e.degree} — {e.institution} ({e.date})")
                for j, bullet in enumerate(e.items):
                    lines.append(f"    bullet[{j}] {bullet}")
        elif isinstance(section, (ExperienceSection, ProjectsSection)):
            for i, e in enumerate(section.entries):
                lines.append(f"  entry[{i}] {e.title}  ({e.date})")
                if e.role:
                    lines.append(f"    role: {e.role}")
                for j, bullet in enumerate(e.items):
                    lines.append(f"    bullet[{j}] {bullet}")
                for j, tech in enumerate(e.tech_stack):
                    lines.append(f"    tech[{j}] {tech}")
        lines.append("")
    return "\n".join(lines)


def render_job(job: Job) -> str:
    """The job posting, trimmed to what the tailor actually reasons over."""
    payload = job.payload or {}
    skills = payload.get("skills") or []
    parts = [
        "JOB POSTING",
        f"title: {job.title}",
        f"company: {job.company}",
        f"level: {job.level or 'unspecified'}",
        f"location: {job.location or 'unspecified'}",
    ]
    if skills:
        parts.append(f"skills listed by the site: {', '.join(skills)}")
    parts += ["", "description:", (payload.get("description_md") or "").strip() or "(empty)"]
    return "\n".join(parts)


def system_prompt(master: CvDocument) -> str:
    """Stable across jobs — rules plus the Master CV outline."""
    return f"{RULES}\n\n{render_master(master)}"


def user_prompt(
    job: Job, instruction: str | None = None, previous: TailorPlan | None = None
) -> str:
    """Volatile per request — the job, plus the edit-loop instruction if any."""
    parts = [render_job(job)]
    if instruction:
        parts += [
            "",
            "REVISION REQUESTED",
            "You already produced a plan for this job (below). The reviewer asked for:",
            f"  {instruction}",
            "",
            "Produce a complete new plan applying that instruction. If following it "
            "would require claiming something the Master CV does not support, do not "
            "do it — leave that part unchanged and say so in `changes`.",
        ]
        if previous is not None:
            parts += ["", "previous plan:", previous.model_dump_json(indent=2)]
    return "\n".join(parts)


def retry_prompt(violations: list[str]) -> str:
    """Sent after a plan fails the guardrails, to get one corrected attempt."""
    listed = "\n".join(f"  - {v}" for v in violations)
    return (
        "That plan was rejected by the CV guardrails:\n"
        f"{listed}\n\n"
        "Return a corrected plan. Indices must point at content that exists in the "
        "Master CV outline, and the summary may only name technologies the CV "
        "already contains."
    )
