"""Phase 17: the cover letter as a document (SKILL.md §2 step 4).

These tests stop at the ``.tex``. Whether that ``.tex`` compiles is a question
for Docker, and it was answered by building it for real — see PHASES.md.
"""

from __future__ import annotations

from datetime import date

import pytest

from jobpilot.apply.letter import CoverLetter
from jobpilot.apply.letter_pdf import letter_context, write_letter_tex
from jobpilot.cv.render import LETTER_FILE, render_letter
from jobpilot.cv.sample import sample_document
from jobpilot.store.models import Job

LETTER = CoverLetter(
    greeting="Dear Hiring Team at ACME Corp,",
    paragraphs=["I build APIs with Java.", "I test them with JUnit."],
    learning_note="I have not used Kafka yet, but I am keen to learn it.",
    closing="Best regards,",
)


def _job(**kw) -> Job:
    return Job(
        **{
            "id": "itviec:1",
            "source": "itviec",
            "url": "https://example.com/j",
            "title": "Backend Engineer",
            "company": "ACME Corp",
            "location": "Ha Noi",
            **kw,
        }
    )


def _render(letter=LETTER, job=None, doc=None):
    doc = doc or sample_document()
    ctx = letter_context(letter, doc, job or _job(), date(2026, 8, 7))
    return render_letter(doc, ctx)


def test_context_names_the_role_and_the_employer():
    ctx = letter_context(LETTER, sample_document(), _job(), date(2026, 8, 7))
    assert ctx["subject"] == "Application for Backend Engineer"
    assert ctx["recipient"] == "ACME Corp"
    assert ctx["recipient_location"] == "Ha Noi"
    assert ctx["date"] == "07 August 2026"


def test_signature_comes_from_the_cv_not_from_the_model():
    """Whose letter this is, is a fact we hold; asking Claude to restate it just
    adds a field that can disagree with the CV it ships next to."""
    assert letter_context(LETTER, sample_document(), _job())["signature"] == "ALEX EXAMPLE"


def test_every_part_of_the_letter_reaches_the_tex():
    out = _render()
    assert "Dear Hiring Team at ACME Corp," in out
    assert "I build APIs with Java." in out
    assert "I test them with JUnit." in out
    assert "keen to learn it" in out
    assert r"\cvsection{Application for Backend Engineer}" in out


def test_latex_specials_in_the_job_and_the_letter_are_escaped():
    """A company called "ACME & Co. 100%" is a build failure waiting to happen —
    the letter is prose from a model and a title from a job board, and neither
    has any reason to be LaTeX-safe."""
    job = _job(title="Engineer (C# & .NET) 100%", company="ACME & Co.")
    letter = CoverLetter(
        greeting="Dear ACME & Co.,",
        paragraphs=["I raised throughput 50% on service_name using C#."],
        closing="Best regards,",
    )
    out = _render(letter, job)
    body = out[out.index(r"\begin{cvparagraph}") : out.index(r"\end{cvparagraph}")]
    assert r"Dear ACME \& Co.,\par" in body
    assert r"I raised throughput 50\% on service\_name using C\#." in body
    assert r"\cvsection{Application for Engineer (C\# \& .NET) 100\%}" in out
    # No bare special survives: every &, %, _ and # in the body is backslashed.
    for ch in ("&", "%", "_", "#"):
        assert ch not in body.replace(f"\\{ch}", "")


def test_paragraphs_are_separated_by_explicit_par():
    """Jinja's trim_blocks eats the newline after every `%>`, so a blank line
    beside a tag silently collapses — and in LaTeX that is the difference between
    two paragraphs and one run-on line. This shipped once, reading
    "Ha Noi Dear Hiring Team at ACME"."""
    out = _render()
    body = out[out.index(r"\begin{cvparagraph}") : out.index(r"\end{cvparagraph}")]
    # The exact pair that regressed: the address block must close before the
    # greeting starts, or the two render on one line.
    assert r"Ha Noi\par" in body
    assert r"Dear Hiring Team at ACME Corp,\par" in body
    # Recipient, greeting, two paragraphs, learning note, closing.
    assert body.count(r"\par") == 6
    # No text line may be followed directly by another text line.
    lines = [ln for ln in body.splitlines() if ln.strip()][1:]
    for prev, nxt in zip(lines, lines[1:]):
        if not prev.startswith("\\vspace") and not nxt.startswith("\\vspace"):
            assert prev.endswith(r"\par"), f"{prev!r} runs into {nxt!r}"


def test_an_empty_learning_note_leaves_no_hole():
    out = _render(CoverLetter(greeting="Hi,", paragraphs=["One."], closing="Bye,"))
    assert "\\par\n\\vspace{2.5mm}\n\\par" not in out


def test_letter_uses_the_same_preamble_as_the_cv():
    """One preamble, so a theme colour that changes on the CV changes here too."""
    doc = sample_document()
    doc.theme.color = "#123ABC"
    out = _render(doc=doc)
    assert r"\definecolor{awesome}{HTML}{123ABC}" in out
    assert r"\documentclass[11pt, a4paper]{awesome-cv}" in out


def test_write_letter_tex_lands_next_to_the_cv(tmp_path):
    path = write_letter_tex(LETTER, sample_document(), _job(), tmp_path)
    assert path == tmp_path / LETTER_FILE
    assert path.read_text(encoding="utf-8").startswith("%!TEX")
    # The class and fonts the letter \documentclass needs came along with it.
    assert (tmp_path / "awesome-cv.cls").is_file()


def test_a_job_with_no_location_still_renders():
    out = _render(job=_job(location=None))
    assert r"\cvsection{Application for Backend Engineer}" in out


@pytest.mark.parametrize("title", ["", None])
def test_a_job_with_no_title_gets_a_generic_subject(title):
    ctx = letter_context(LETTER, sample_document(), _job(title=title))
    assert ctx["subject"] == "Application"
