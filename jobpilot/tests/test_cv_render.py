"""Phase 4.5: inline markup -> LaTeX, and CvDocument -> .tex rendering."""

from __future__ import annotations

import pytest

from jobpilot.cv.latex import escape_tex, tex
from jobpilot.cv.render import RenderError, list_templates, render_document, render_tex_snapshot
from jobpilot.cv.schema import (
    BulletItem,
    BulletsSection,
    CvDocument,
    EducationEntry,
    EducationSection,
    Entry,
    ExperienceSection,
    Header,
    ParagraphSection,
    ProjectsSection,
    Theme,
)
from jobpilot.cv.store import load_seed


# --------------------------------------------------------------------------- #
# latex.py
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("plain", "plain"),
        ("80% & rising", r"80\% \& rising"),
        ("snake_case #1", r"snake\_case \#1"),
        ("**bold**", r"\textbf{bold}"),
        ("`Spring Boot`", r"\tech{Spring Boot}"),
        ("~React~", r"\techfe{React}"),
        ("a **b** c `d` e", r"a \textbf{b} c \tech{d} e"),
        ("[Portfolio](https://x.dev/p)", r"\hreficon{https://x.dev/p}{Portfolio}"),
        # Link labels render recursively.
        ("[**Slide** `AI`](http://a.b)", r"\hreficon{http://a.b}{\textbf{Slide} \tech{AI}}"),
        # Unmatched markers degrade to literal text rather than eating the line.
        ("50% off * sale", r"50\% off * sale"),
        ("", ""),
    ],
)
def test_inline_markup(raw, expected):
    assert tex(raw) == expected


def test_escape_does_not_double_escape_backslash():
    assert escape_tex(r"a\b") == r"a\textbackslash{}b"


def test_markup_body_is_escaped():
    """Specials inside a marker still get escaped — no LaTeX injection via content."""
    assert tex("**100% done**") == r"\textbf{100\% done}"
    assert tex("`C#`") == r"\tech{C\#}"


def test_url_specials_escaped_in_links():
    assert tex("[x](https://a.b/c#d)") == r"\hreficon{https://a.b/c\#d}{x}"


# --------------------------------------------------------------------------- #
# render.py
# --------------------------------------------------------------------------- #
def _doc(**kw) -> CvDocument:
    return CvDocument(header=Header(first_name="A", last_name="B"), **kw)


def test_renders_one_file_per_enabled_section_plus_cv_tex():
    doc = _doc(
        sections=[
            ParagraphSection(key="summary", title="Summary", text="Hi"),
            BulletsSection(key="skills", title="Skills", enabled=False),
        ]
    )
    files = render_document(doc)
    assert set(files) == {"cv.tex", "resume/summary.tex"}
    # Disabled sections are neither emitted nor \input.
    assert "resume/skills.tex" not in files["cv.tex"]
    assert r"\input{resume/summary.tex}" in files["cv.tex"]


def test_section_order_follows_the_json_list():
    doc = _doc(
        sections=[
            BulletsSection(key="skills", title="Skills"),
            ParagraphSection(key="summary", title="Summary"),
        ]
    )
    body = render_document(doc)["cv.tex"]
    assert body.index("resume/skills.tex") < body.index("resume/summary.tex")


def test_bullets_render_label_and_date():
    doc = _doc(
        sections=[
            BulletsSection(
                key="honors",
                title="Honors & Awards",
                items=[BulletItem(label="Award", text="Won it", date="2024")],
            )
        ]
    )
    out = render_document(doc)["resume/honors.tex"]
    assert r"\cvsection{Honors \& Awards}" in out
    assert r"\item{\textbf{Award}: Won it\hfill\entrysimpledatestyle{2024}}" in out


def test_education_entry_macro():
    doc = _doc(
        sections=[
            EducationSection(
                key="education",
                title="Education",
                entries=[
                    EducationEntry(
                        degree="`BSc`, SE",
                        institution="FPT",
                        location="HCMC",
                        date="2022 -- 2026",
                        items=["GPA **3.2**"],
                    )
                ],
            )
        ]
    )
    out = render_document(doc)["resume/education.tex"]
    assert r"\cventry" in out
    assert r"{\tech{BSc}, SE}" in out
    assert r"\item {GPA \textbf{3.2}}" in out


def test_experience_and_projects_tech_stack_lines_differ():
    entry = Entry(title="T", date="D", items=["did a thing"], tech_stack=["Java", "Kafka"])
    exp = render_document(
        _doc(sections=[ExperienceSection(key="e", title="Work", entries=[entry])])
    )["resume/e.tex"]
    proj = render_document(
        _doc(
            sections=[
                ProjectsSection(
                    key="p",
                    title="Projects",
                    entries=[entry.model_copy(update={"role": "Team Lead"})],
                )
            ]
        )
    )["resume/p.tex"]

    assert r"\item {\tech{Tech Stack}: \textbf{Java}, \textbf{Kafka}}" in exp
    assert r"\textbf{Role}: Team Lead \quad | \quad \textbf{Tech Stack}:" in proj


def test_entry_url_wraps_title_in_hreficon():
    doc = _doc(
        sections=[
            ProjectsSection(
                key="p",
                title="Projects",
                entries=[Entry(title="Proj", date="2024", url="https://git.io/x")],
            )
        ]
    )
    out = render_document(doc)["resume/p.tex"]
    assert r"\hreficon{https://git.io/x}{\textbf{Proj}}" in out


def test_theme_named_colour_vs_hex():
    named = render_document(_doc(theme=Theme(color="awesome-emerald")))["cv.tex"]
    hexed = render_document(_doc(theme=Theme(color="#ca63a8")))["cv.tex"]
    assert r"\colorlet{awesome}{awesome-emerald}" in named
    assert r"\definecolor{awesome}{HTML}{CA63A8}" in hexed


def test_optional_header_fields_are_omitted():
    out = render_document(_doc())["cv.tex"]
    assert r"\address" not in out
    assert r"\quote" not in out


def test_unknown_template_rejected():
    with pytest.raises(RenderError):
        render_document(_doc(template="does_not_exist"))


def test_awesome_cv_template_is_listed():
    assert "awesome_cv" in list_templates()


# --------------------------------------------------------------------------- #
# The imported Master CV (seed) — the whole point of the phase.
# --------------------------------------------------------------------------- #
def test_seed_loads_and_renders_all_six_sections():
    doc = load_seed()
    files = render_document(doc)
    assert set(files) == {
        "cv.tex",
        "resume/summary.tex",
        "resume/education.tex",
        "resume/experience.tex",
        "resume/projects.tex",
        "resume/honors.tex",
        "resume/skills.tex",
    }


def test_seed_matches_the_original_master_cv_content():
    """Spot-check lines that must survive the .tex -> JSON import verbatim."""
    files = render_document(load_seed())
    assert r"\name{\textbf{KHOI}}{\tech{PHAM}}" in files["cv.tex"]
    assert (
        r"\item {Wrote \textbf{unit tests} with \tech{JUnit}, achieving "
        r"\textbf{over 80\% code coverage} measured by \textbf{JaCoCo}.}"
        in files["resume/experience.tex"]
    )
    assert (
        r"\item{\textbf{Languages \& Frameworks}: Java, Spring Boot, Python, FastAPI}"
        in files["resume/skills.tex"]
    )


def test_tex_snapshot_covers_every_rendered_file():
    snapshot = render_tex_snapshot(load_seed())
    for path in render_document(load_seed()):
        assert f"% ===== {path} =====" in snapshot
