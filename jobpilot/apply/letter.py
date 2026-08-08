"""Cover letter generation (SKILL.md §2 step 4).

Same truthfulness problem as the CV, with one extra wrinkle: SKILL.md explicitly
*allows* the letter to acknowledge a missing skill as something the candidate is
willing to learn. A single free-text blob would make "I am experienced with
Kafka" and "I have not used Kafka yet but I am keen to" indistinguishable to any
checker, so the schema separates them:

* ``paragraphs`` — claims about the candidate. Checked strictly against the
  Master CV's vocabulary; a technology that isn't already on the CV is rejected.
* ``learning_note`` — the one place a MISSING requirement may be named, and only
  the requirements the tailor already classified as MISSING for this job.

That split is what makes the honest sentence expressible and the dishonest one
not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from jobpilot.cv.schema import CvDocument
from jobpilot.llm.base import Completion, LlmError, StructuredClient
from jobpilot.llm.usage import call_log
from jobpilot.store.models import Job
from jobpilot.tailor.engine import TailorError
from jobpilot.tailor.guard import GuardrailViolation, PlanReport, unknown_terms, vocabulary
from jobpilot.tailor.schema import TailorPlan

MAX_WORDS = 300  # SKILL.md §2 step 4


class CoverLetter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    greeting: str = Field(description='e.g. "Dear Hiring Team at ACME Corp,"')
    paragraphs: list[str] = Field(
        default_factory=list,
        description="Two or three short paragraphs. Every claim must be backed by "
        "the Master CV — name only technologies that already appear on it.",
    )
    learning_note: str = Field(
        default="",
        description="Optional single sentence acknowledging a requirement the "
        "candidate does not yet have, framed as willingness to learn. This is the "
        "only field allowed to name a MISSING requirement, and it must never claim "
        "the skill. Leave empty when there is no important gap.",
    )
    closing: str = Field(default="Best regards,", description='e.g. "Best regards,"')

    def body(self) -> str:
        """The letter as plain text — this is what an email actually carries."""
        parts = [self.greeting, "", *self._flow(), "", self.closing]
        return "\n".join(parts).strip()

    def _flow(self) -> list[str]:
        blocks = [p.strip() for p in self.paragraphs if p.strip()]
        if self.learning_note.strip():
            blocks.append(self.learning_note.strip())
        # Blank line between paragraphs.
        out: list[str] = []
        for i, block in enumerate(blocks):
            if i:
                out.append("")
            out.append(block)
        return out

    def word_count(self) -> int:
        return len(self.body().split())


# --------------------------------------------------------------------------- #
# Guardrail
# --------------------------------------------------------------------------- #
def _tokens(*values: str | None) -> set[str]:
    """Proper nouns the letter must be able to name: the company, the location."""
    out: set[str] = set()
    for value in values:
        for word in (value or "").replace("/", " ").split():
            cleaned = word.strip(".,()-").lower()
            if cleaned:
                out.add(cleaned)
    return out


def check_letter(
    letter: CoverLetter, master: CvDocument, job: Job, plan: TailorPlan | None = None
) -> PlanReport:
    """Claims are checked against the CV; only the learning note may name a gap."""
    violations: list[str] = []

    # The employer's name and city are facts about the job, not claims about the
    # candidate, so the letter is allowed to say them.
    claim_vocab = vocabulary(master) | _tokens(job.company, job.location)

    for i, para in enumerate(letter.paragraphs):
        invented = unknown_terms(para, claim_vocab)
        if invented:
            violations.append(
                f"paragraph {i + 1} claims experience with {', '.join(invented)}, which the "
                "Master CV does not support — move it to learning_note or drop it"
            )

    if letter.learning_note.strip():
        gaps = {g.text for g in plan.gaps()} if plan else set()
        note_vocab = claim_vocab | _tokens(*gaps)
        invented = unknown_terms(letter.learning_note, note_vocab)
        if invented:
            violations.append(
                f"learning_note names {', '.join(invented)}, which is neither on the CV nor "
                "a MISSING requirement of this job"
            )

    if letter.word_count() > MAX_WORDS:
        violations.append(f"letter is {letter.word_count()} words; keep it under {MAX_WORDS}")
    if not letter.paragraphs:
        violations.append("letter has no body paragraphs")

    return PlanReport(violations=violations)


# --------------------------------------------------------------------------- #
# Prompt
# --------------------------------------------------------------------------- #
LETTER_RULES = f"""\
Write a cover letter for one job application, on behalf of the candidate whose
CV appears below.

# Rules
- Never claim a skill, technology, employer, metric, or achievement the CV does
  not already show. The body paragraphs are claims about the candidate and are
  checked against the CV word by word.
- If the job needs something the candidate does not have and it matters, put a
  single honest sentence in `learning_note` — willingness to learn, never a
  claim of experience. That field is the only place a missing skill may appear.
  Leave it empty if there is no important gap.
- Two or three short paragraphs: why this role, then two concrete strengths
  drawn from the CV with evidence, then a brief close.
- Under {MAX_WORDS} words in total. Plain prose — no markdown, no bullet points,
  no LaTeX. Professional, specific, and free of filler.
"""


def letter_prompt(job: Job, plan: TailorPlan | None) -> str:
    payload = job.payload or {}
    parts = [
        "JOB",
        f"title: {job.title}",
        f"company: {job.company}",
        f"location: {job.location or 'unspecified'}",
        "",
        "description:",
        (payload.get("description_md") or "").strip() or "(empty)",
    ]
    if plan is not None:
        strengths = [r for r in plan.requirements if r.status in ("HAVE", "PARTIAL")]
        if strengths:
            parts += ["", "REQUIREMENTS THE CV SUPPORTS (use these as your evidence):"]
            parts += [f"  - {r.text} — {r.evidence or 'see CV'}" for r in strengths]
        gaps = plan.gaps()
        if gaps:
            parts += ["", "REQUIREMENTS THE CANDIDATE DOES NOT HAVE:"]
            parts += [f"  - {g.text}" for g in gaps]
            parts += [
                "",
                "Only these may appear in learning_note, and only as something to learn.",
            ]
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Engines
# --------------------------------------------------------------------------- #
@dataclass
class LetterResult:
    letter: CoverLetter
    attempts: int = 1


class LetterEngine(Protocol):
    def write(
        self, master: CvDocument, job: Job, plan: TailorPlan | None = None
    ) -> LetterResult: ...


@dataclass
class ModelLetterEngine:
    """One letter, one corrective round, whichever backend is configured.

    Same shape as ``ModelTailorEngine`` and for the same reason: the retry is
    what stops an unsupported claim reaching an employer, so it cannot be
    something each backend gets its own copy of. Until Phase 20b this file held
    two near-identical copies of the loop below — one per provider — which is
    the arrangement ``tailor/diff.py`` was refactored to avoid two phases
    earlier.

    The letter is the call where model quality shows most: it is free prose a
    person will judge you on rather than a permutation of numbered items. The
    vocabulary guardrail still holds — no backend can claim a technology the CV
    lacks — but "true" and "well written" are different bars and only the first
    is enforceable. Read it before sending; the approval gate is already there.
    """

    client: StructuredClient

    def _ask(self, system: str, messages: list[dict]) -> Completion[CoverLetter]:
        try:
            return self.client.structured(system=system, messages=messages, schema=CoverLetter)
        except LlmError as exc:
            raise TailorError(str(exc)) from exc

    def write(self, master: CvDocument, job: Job, plan: TailorPlan | None = None) -> LetterResult:
        from jobpilot.tailor.prompt import render_master

        system = f"{LETTER_RULES}\n\n{render_master(master)}"
        messages: list[dict] = [{"role": "user", "content": letter_prompt(job, plan)}]

        with call_log("letter", job_id=job.id) as usage:
            letter = usage.add_from(self._ask(system, messages))
            report = check_letter(letter, master, job, plan)
            if report.ok:
                usage.succeeded()
                return LetterResult(letter=letter)

            messages += [
                {"role": "assistant", "content": letter.model_dump_json()},
                {
                    "role": "user",
                    "content": "That letter was rejected:\n"
                    + "\n".join(f"  - {v}" for v in report.violations)
                    + "\n\nRewrite it within the rules.",
                },
            ]
            retried = usage.add_from(self._ask(system, messages))
            second = check_letter(retried, master, job, plan)
            if not second.ok:
                raise GuardrailViolation(
                    "cover letter still unsupported after one retry: "
                    + "; ".join(second.violations)
                )
            usage.succeeded()
            return LetterResult(letter=retried, attempts=2)


@dataclass
class FixtureLetterEngine:
    """Canned letter for tests and offline runs."""

    letter: CoverLetter
    calls: list[str] = field(default_factory=list)

    def write(self, master: CvDocument, job: Job, plan: TailorPlan | None = None) -> LetterResult:
        self.calls.append(job.id)
        check_letter(self.letter, master, job, plan).raise_if_bad()
        return LetterResult(letter=self.letter)


def default_letter_engine() -> LetterEngine:
    """The engine `llm.letter` (or `llm.provider`) asks for."""
    from jobpilot.llm.registry import client_for

    return ModelLetterEngine(client_for("letter"))
