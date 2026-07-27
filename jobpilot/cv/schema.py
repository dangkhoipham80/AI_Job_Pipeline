"""Structured CV document model — the source of truth for CV content.

Text fields carry the inline markup described in ``cv/latex.py`` (``**bold**``,
```tech```, ``[label](url)``); no field ever holds raw LaTeX. Sections are an
ordered list so the editor can reorder/disable them without schema changes, and
each section subtype maps to one Awesome-CV macro family:

    paragraph  -> \\begin{cvparagraph}
    education  -> \\cventry      (degree / institution / location / date)
    experience -> \\cvsimpleentry (title / date)      + optional tech stack line
    projects   -> \\cvsimpleentry (linked title/date) + optional role/tech line
    bullets    -> \\begin{cvempty} + \\cvitems        (skills, honors)
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Theme(_Model):
    """Presentation knobs applied to the document preamble."""

    # An Awesome-CV named colour (awesome-red, awesome-emerald, ...) or #RRGGBB.
    color: str = "awesome-red"
    section_highlight: bool = True
    font_dir: str = "fonts/"


class Link(_Model):
    label: str
    url: str


class Header(_Model):
    """Personal information block (\\makecvheader)."""

    first_name: str = ""
    last_name: str = ""
    position: str = ""
    address: str | None = None
    mobile: str | None = None
    email: str | None = None
    homepage: str | None = None
    github: str | None = None
    linkedin: str | None = None
    extra_info: Link | None = None
    quote: str | None = None


class _Section(_Model):
    """Common section fields. ``key`` also names the generated resume/<key>.tex."""

    key: str
    title: str
    enabled: bool = True


class ParagraphSection(_Section):
    type: Literal["paragraph"] = "paragraph"
    text: str = ""
    # Awesome-CV's summary is set one size down; keep it toggleable per section.
    small: bool = True


class BulletItem(_Model):
    """One \\item. ``label`` renders as a bold lead-in, ``date`` right-aligned."""

    label: str | None = None
    text: str = ""
    date: str | None = None


class BulletsSection(_Section):
    type: Literal["bullets"] = "bullets"
    items: list[BulletItem] = Field(default_factory=list)


class EducationEntry(_Model):
    degree: str = ""
    institution: str = ""
    location: str = ""
    date: str = ""
    items: list[str] = Field(default_factory=list)


class EducationSection(_Section):
    type: Literal["education"] = "education"
    entries: list[EducationEntry] = Field(default_factory=list)


class Entry(_Model):
    """A \\cvsimpleentry: one job or one project."""

    title: str = ""
    date: str = ""
    url: str | None = None
    items: list[str] = Field(default_factory=list)
    # role + tech_stack render as one trailing bullet ("Role: X | Tech Stack: ...").
    # Kept structured rather than free-text so the tailor can reorder the stack
    # against a JD without rewriting the sentence -- SKILL.md §2.
    role: str | None = None
    tech_stack: list[str] = Field(default_factory=list)


class ExperienceSection(_Section):
    type: Literal["experience"] = "experience"
    entries: list[Entry] = Field(default_factory=list)


class ProjectsSection(_Section):
    type: Literal["projects"] = "projects"
    entries: list[Entry] = Field(default_factory=list)


Section = Annotated[
    Union[
        ParagraphSection,
        BulletsSection,
        EducationSection,
        ExperienceSection,
        ProjectsSection,
    ],
    Field(discriminator="type"),
]


class CvDocument(_Model):
    """A complete CV. Serialized into ``cv_versions.content``."""

    schema_version: int = SCHEMA_VERSION
    template: str = "awesome_cv"
    theme: Theme = Field(default_factory=Theme)
    header: Header = Field(default_factory=Header)
    sections: list[Section] = Field(default_factory=list)

    def active_sections(self) -> list[Section]:
        return [s for s in self.sections if s.enabled]
