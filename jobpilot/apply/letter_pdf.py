"""Render a ``CoverLetter`` to ``cover_letter.tex`` and build it to PDF.

SKILL.md §2 step 4 asks for a cover letter *document*, not just an email body.
The letter builds in the same dir as the tailored CV (``out/cv/<slug>/``) and
reuses its assets, so the two PDFs share one identity block, one accent colour
and one set of fonts.

Two things this module deliberately does not do:

* It does not replace the plain-text letter. Email carries text in the body --
  a PDF in the body is not a thing -- so ``CoverLetter.body()`` stays the
  canonical form and the PDF is an artifact built from the same fields.
* It does not decide whether the build failing should fail the application. A
  cover letter that won't compile is not a reason to withhold a CV that already
  built; the caller sees the exception and chooses.
"""

from __future__ import annotations

from datetime import date as date_cls
from pathlib import Path

from jobpilot.apply.letter import CoverLetter
from jobpilot.cv.compile import sync_assets
from jobpilot.cv.render import LETTER_FILE, render_letter
from jobpilot.cv.schema import CvDocument
from jobpilot.store.models import Job
from jobpilot.tailor.build import BuildResult, build_cv


def letter_context(
    letter: CoverLetter,
    doc: CvDocument,
    job: Job,
    today: date_cls | None = None,
) -> dict:
    """Template variables for ``cover_letter.tex.j2``.

    The signature line falls back to the CV header rather than to the model's
    closing: whose letter this is, is a fact we already hold, not something worth
    asking Claude to restate.
    """
    name = " ".join(p for p in (doc.header.first_name, doc.header.last_name) if p).strip()
    return {
        "date": (today or date_cls.today()).strftime("%d %B %Y"),
        "subject": f"Application for {job.title}" if job.title else "Application",
        "recipient": job.company or "",
        "recipient_location": job.location or "",
        "greeting": letter.greeting,
        "paragraphs": [p.strip() for p in letter.paragraphs if p.strip()],
        "learning_note": letter.learning_note.strip(),
        "closing": letter.closing,
        "signature": name,
    }


def write_letter_tex(
    letter: CoverLetter,
    doc: CvDocument,
    job: Job,
    dest: Path,
    today: date_cls | None = None,
) -> Path:
    """Write ``cover_letter.tex`` into ``dest`` and return its path.

    ``dest`` is passed in rather than derived from the job id: the caller has
    already resolved where this job's CV was built, and re-deriving it here would
    be a second opinion about the same location — one that silently disagreed
    with the dispatcher's under test.
    """
    sync_assets(dest)
    path = dest / LETTER_FILE
    path.write_text(render_letter(doc, letter_context(letter, doc, job, today)), encoding="utf-8")
    return path


def compile_letter(
    letter: CoverLetter,
    doc: CvDocument,
    job: Job,
    dest: Path,
    today: date_cls | None = None,
) -> BuildResult:
    """Render + build the letter. Raises ``BuildError`` if LaTeX or Docker fails."""
    path = write_letter_tex(letter, doc, job, dest, today)
    return build_cv(path.parent, entry=LETTER_FILE)
