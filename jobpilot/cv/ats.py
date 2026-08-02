"""Can a machine read the PDF we just built?

Everything upstream of this file optimises the CV for a human reviewer, but the
first reader is almost always an applicant tracking system, and an ATS does not
see the page — it sees whatever ``pdftotext`` gets out of it. Those two can
disagree badly, and LaTeX is unusually good at making them disagree: xelatex
subsets fonts, glues ligatures together, and lays text out in an order that has
nothing to do with reading order. A CV can look immaculate and still arrive at
the recruiter as a wall of mojibake with no email address in it.

The build step already answers "did it compile?" and "how many pages?". This
answers the question that actually decides whether the application is read at
all, and it answers it *before* you approve the CV rather than after silence.

Nothing here guesses at a score. Each finding names one concrete thing a parser
could not recover, because "ATS score: 72/100" tells you nothing you can act on
while "your email address is not in the text layer" tells you exactly what to
fix. Findings the checker cannot be sure about are warnings, not errors: this
gate must never block a CV it merely dislikes.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from jobpilot.cv.schema import CvDocument

# Ligature codepoints xelatex emits that many extractors keep as-is. A recruiter
# searching "office" will not match "oﬃce".
LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"}

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_DIGITS_RE = re.compile(r"\d")
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#.]*")

#: Below this, the PDF almost certainly has no usable text layer at all.
MIN_TEXT_CHARS = 200


@dataclass
class Finding:
    """One concrete thing an ATS could not recover, plus how to fix it."""

    level: str  # "error" | "warning"
    code: str
    message: str
    fix: str = ""

    def as_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "message": self.message, "fix": self.fix}


@dataclass
class AtsReport:
    ok: bool = True
    chars: int = 0
    #: Which extractor produced the text — findings mean different things
    #: depending on how much it can be trusted.
    engine: str = ""
    findings: list[Finding] = field(default_factory=list)
    #: Job skills found / missing in the text layer (only when a job was given).
    keywords_found: list[str] = field(default_factory=list)
    keywords_missing: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "chars": self.chars,
            "engine": self.engine,
            "findings": [f.as_dict() for f in self.findings],
            "keywords_found": self.keywords_found,
            "keywords_missing": self.keywords_missing,
        }


@dataclass
class Extraction:
    """A PDF's text layer plus how much the extractor can be trusted.

    ``spacing_reliable`` exists because of a false alarm this checker raised on
    its very first real build. Read with pypdf, a perfectly good Awesome-CV PDF
    came back as ``FRESHERSOFTWAREENGINEER`` and ``WorkExperience`` — spaces
    gone — and the checker duly reported that the section headings were missing
    and the CV was unreadable. Read with pdfminer.six, the same file yields
    "FRESHER SOFTWARE ENGINEER" and "Work Experience", correctly spaced.

    The PDF was never broken; the extractor was. Reporting a tool's own
    limitation as a defect in the user's document is worse than not checking at
    all — it sends someone off to "fix" a template that was already right. So
    the engine that cannot be trusted on word spacing says so, and the checks
    that depend on spacing loosen accordingly.
    """

    text: str
    engine: str
    spacing_reliable: bool


def extract(pdf_path: Path) -> Extraction | None:
    """Read the text layer with the best extractor available, or ``None``.

    ``None`` means "unknown", not "empty" — the same distinction the page count
    had to learn. With no extractor installed we genuinely do not know what an
    ATS would see, and saying "your CV is unreadable" on that basis is a
    confident lie.
    """
    text = _pdfminer_text(pdf_path)
    if text is not None:
        return Extraction(text, "pdfminer.six", spacing_reliable=True)
    text = _pypdf_text(pdf_path)
    if text is not None:
        return Extraction(text, "pypdf", spacing_reliable=False)
    return None


def _pdfminer_text(pdf_path: Path) -> str | None:
    """pdfminer.six — the engine family real resume parsers are built on."""
    try:
        from pdfminer.high_level import extract_text as _extract
    except ImportError:
        return None
    try:
        return _extract(str(pdf_path))
    except Exception:
        return None


def _pypdf_text(pdf_path: Path) -> str | None:
    """Fallback. Fine for characters, unreliable for the spaces between them."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(str(pdf_path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return None


def extract_text(pdf_path: Path) -> str | None:
    """Just the text, for callers that don't care which engine produced it."""
    got = extract(pdf_path)
    return got.text if got else None


def normalize(text: str) -> str:
    """Undo the damage extraction does before matching anything against it."""
    for lig, plain in LIGATURES.items():
        text = text.replace(lig, plain)
    # NFKD then drop combining marks: "Khôi" extracts inconsistently as either a
    # precomposed character or a letter plus a floating accent, and a recruiter's
    # search box does neither.
    stripped = unicodedata.normalize("NFKD", text)
    return "".join(c for c in stripped if not unicodedata.combining(c))


def _words(text: str) -> set[str]:
    return set(_WORD_RE.findall(normalize(text).lower()))


class _Haystack:
    """Answers "is this in the PDF?" as precisely as the extractor allows.

    When word spacing is unreliable, "Work Experience" and "WorkExperience" are
    the same observation and the difference carries no information — so both
    sides are squashed before comparing. That keeps a weak extractor from
    inventing findings, at the cost of not being able to detect a genuine
    spacing fault. A checker that is quiet when unsure beats one that is loud
    when wrong.
    """

    def __init__(self, text: str, spacing_reliable: bool = True) -> None:
        self.spacing_reliable = spacing_reliable
        self.text = normalize(text)
        self.lower = self.text.lower()
        self.squashed = re.sub(r"\s+", "", self.lower)
        self.words = _words(text)

    def contains(self, needle: str) -> bool:
        probe = normalize(needle).lower()
        if probe in self.lower:
            return True
        if self.spacing_reliable:
            return False
        return re.sub(r"\s+", "", probe) in self.squashed

    def has_all_words(self, phrase: str) -> bool:
        """Every word of ``phrase`` present — as words, or squashed together."""
        wanted = _words(phrase)
        if not wanted:
            return False
        if wanted <= self.words:
            return True
        return not self.spacing_reliable and self.contains(phrase)


def check_pdf(
    pdf_path: Path, doc: CvDocument, job_skills: list[str] | None = None
) -> AtsReport | None:
    """Compare what the CV *says* against what a parser can pull back out.

    Returns ``None`` when the text layer could not be read at all (no extractor
    installed), which callers must treat as "not checked", not "passed".
    """
    got = extract(pdf_path)
    if got is None:
        return None
    report = check_text(got.text, doc, job_skills, spacing_reliable=got.spacing_reliable)
    report.engine = got.engine
    return report


def check_text(
    text: str,
    doc: CvDocument,
    job_skills: list[str] | None = None,
    spacing_reliable: bool = True,
) -> AtsReport:
    """The pure half of :func:`check_pdf` — testable without building a PDF."""
    report = AtsReport(chars=len(text.strip()))
    hay = _Haystack(text, spacing_reliable)
    flat = hay.text

    if report.chars < MIN_TEXT_CHARS:
        report.findings.append(
            Finding(
                "error",
                "no_text_layer",
                f"The PDF has almost no extractable text ({report.chars} characters). "
                "An ATS would receive a blank document.",
                "The CV was probably rendered as an image. Rebuild it through CV Studio "
                "rather than attaching a scan or screenshot.",
            )
        )
        report.ok = False
        return report  # every later check would just restate this one

    header = doc.header
    full_name = f"{header.first_name} {header.last_name}".strip()
    if full_name and not hay.has_all_words(full_name):
        report.findings.append(
            Finding(
                "error",
                "name_missing",
                f"Your name ({full_name}) is not recoverable from the text layer.",
                "The name is usually set in a display font; check that font is embedded "
                "with a normal encoding rather than as outlines.",
            )
        )

    if header.email:
        found = _EMAIL_RE.findall(flat)
        if header.email.lower() not in (e.lower() for e in found):
            report.findings.append(
                Finding(
                    "error",
                    "email_missing",
                    f"Your email ({header.email}) is not in the text layer"
                    + (f" — the parser found {found[0]} instead." if found else "."),
                    "An ATS that cannot read your email cannot reply to you. Check the "
                    "header renders the address as text, not inside an icon or a link label.",
                )
            )

    if header.mobile and not _contains_phone(flat, header.mobile):
        report.findings.append(
            Finding(
                "warning",
                "phone_missing",
                f"Your phone number ({header.mobile}) did not survive extraction.",
                "Spacing and separators often shift; this only matters if the ATS "
                "requires a phone field.",
            )
        )

    missing_sections = [
        s.title for s in doc.sections if s.enabled and s.title and not hay.contains(s.title)
    ]
    if missing_sections:
        report.findings.append(
            Finding(
                "warning",
                "sections_missing",
                "These section headings are not in the text layer: "
                + ", ".join(missing_sections)
                + ".",
                "ATS parsers split a CV on its headings. A heading it cannot see means the "
                "content underneath is filed under whatever came before.",
            )
        )

    damaged = sorted(lig for lig in LIGATURES if lig in text)
    if damaged:
        report.findings.append(
            Finding(
                "warning",
                "ligatures",
                "The text layer contains ligature characters ("
                + ", ".join(repr(d) for d in damaged)
                + ") which break keyword search.",
                'A recruiter searching "office" will not match "oﬃce". Usually fixed by '
                "disabling ligatures for the body font.",
            )
        )

    if job_skills:
        for skill in job_skills:
            if hay.has_all_words(skill):
                report.keywords_found.append(skill)
            else:
                report.keywords_missing.append(skill)

    report.ok = not report.errors
    return report


def _contains_phone(text: str, phone: str) -> bool:
    """Compare digits only — extraction reflows spaces, dots and brackets."""
    wanted = "".join(_DIGITS_RE.findall(phone))
    if not wanted:
        return True
    got = "".join(_DIGITS_RE.findall(text))
    # Match on the last 8 digits: a leading "+84" is often rendered as "84" or
    # dropped with the plus sign, and that is not a real problem.
    return wanted[-8:] in got if len(wanted) >= 8 else wanted in got
