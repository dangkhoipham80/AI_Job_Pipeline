"""What a fresh database gets: an empty CV.

The repository ships **no CV content at all** — not even placeholder names.
Personal data lives in the ``cv_versions`` table and is read and written through
the API (``GET/PUT /cv/{scope}``), which is what CV Studio uses.

So the bootstrap can only be *structure*: the sections a CV normally has, with
every field blank. You fill them in the UI, or import an existing document with
``jobpilot cv import <file.json>``.
"""

from __future__ import annotations

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
)


def empty_document() -> CvDocument:
    """A blank CV with the usual sections, ready to be filled in."""
    return CvDocument(
        header=Header(position="Software Engineer"),
        sections=[
            ParagraphSection(key="summary", title="Summary", text=""),
            EducationSection(
                key="education",
                title="Education",
                entries=[EducationEntry(items=[""])],
            ),
            ExperienceSection(
                key="experience",
                title="Work Experience",
                entries=[Entry(items=[""])],
            ),
            ProjectsSection(
                key="projects",
                title="Projects",
                entries=[Entry(items=[""])],
            ),
            BulletsSection(key="skills", title="Skills", items=[BulletItem()]),
            BulletsSection(key="honors", title="Honors & Awards", items=[BulletItem()]),
        ],
    )
