"""ATS readability of the compiled PDF.

The build step answers "did it compile?" and "how many pages?". These pin the
question that actually decides whether a human ever reads the CV: can a parser
get the contact details and the section headings back out of the file?

Every fixture here is a *text layer*, not a PDF — that is exactly what an ATS
receives, and it keeps the checks testable without a Docker build.
"""

from __future__ import annotations

from jobpilot.cv.ats import LIGATURES, AtsReport, check_text, normalize
from jobpilot.cv.sample import sample_document


def _doc():
    doc = sample_document()
    doc.header.first_name = "Khoi"
    doc.header.last_name = "Pham"
    doc.header.email = "khoi@example.com"
    doc.header.mobile = "+84 912 345 678"
    return doc


def _good_text(doc) -> str:
    parts = [
        f"{doc.header.first_name} {doc.header.last_name}",
        doc.header.email,
        doc.header.mobile,
        *[s.title for s in doc.sections if s.enabled and s.title],
        "Built Java and Spring Boot services on PostgreSQL. " * 12,
    ]
    return "\n".join(parts)


def _codes(report: AtsReport) -> set[str]:
    return {f.code for f in report.findings}


# --------------------------------------------------------------------------- #
# the catastrophic case
# --------------------------------------------------------------------------- #
def test_a_pdf_with_no_text_layer_is_an_error():
    """A CV rendered as an image looks perfect and arrives blank."""
    report = check_text("   ", _doc())
    assert report.ok is False
    assert _codes(report) == {"no_text_layer"}


def test_the_blank_pdf_finding_does_not_bury_itself_in_noise():
    """With no text, every other check would also fail and restate the same
    fact. One clear error beats eight derived ones."""
    assert len(check_text("", _doc()).findings) == 1


# --------------------------------------------------------------------------- #
# contact details — the ones that decide whether anyone can reply
# --------------------------------------------------------------------------- #
def test_a_readable_cv_passes_cleanly():
    doc = _doc()
    report = check_text(_good_text(doc), doc)
    assert report.ok is True
    assert report.errors == []


def test_missing_email_is_an_error():
    doc = _doc()
    text = _good_text(doc).replace(doc.header.email, "")
    report = check_text(text, doc)
    assert report.ok is False
    assert "email_missing" in _codes(report)


def test_a_wrong_email_names_what_the_parser_actually_found():
    """ "Your email is missing" is much less useful than showing the address the
    ATS would have written to instead."""
    doc = _doc()
    text = _good_text(doc).replace(doc.header.email, "typo@exmaple.com")
    finding = next(f for f in check_text(text, doc).findings if f.code == "email_missing")
    assert "typo@exmaple.com" in finding.message


def test_missing_name_is_an_error_but_split_across_lines_is_fine():
    doc = _doc()
    assert "name_missing" in _codes(check_text("Anonymous CV\n" + doc.header.email * 40, doc))
    # A two-line header is normal and must not be flagged.
    text = _good_text(doc).replace("Khoi Pham", "Khoi\nPham")
    assert "name_missing" not in _codes(check_text(text, doc))


def test_phone_matches_on_digits_not_formatting():
    """Extraction reflows spaces and brackets, and a leading +84 often loses its
    plus. Flagging that would be noise, so match the digits that matter."""
    doc = _doc()
    text = _good_text(doc).replace("+84 912 345 678", "(0)912.345.678")
    assert "phone_missing" not in _codes(check_text(text, doc))


def test_a_genuinely_absent_phone_is_only_a_warning():
    """A missing phone number costs you a field, not the application."""
    doc = _doc()
    text = _good_text(doc).replace(doc.header.mobile, "")
    report = check_text(text, doc)
    assert "phone_missing" in _codes(report)
    assert report.ok is True  # warnings never block


# --------------------------------------------------------------------------- #
# structure and encoding
# --------------------------------------------------------------------------- #
def test_missing_section_headings_are_reported():
    """Parsers split a CV on its headings. A heading the parser cannot see means
    the content under it is filed under whatever came before."""
    doc = _doc()
    title = next(s.title for s in doc.sections if s.enabled and s.title)
    text = _good_text(doc).replace(title, "")
    report = check_text(text, doc)
    assert "sections_missing" in _codes(report)
    assert title in next(f for f in report.findings if f.code == "sections_missing").message


def test_disabled_sections_are_not_expected_in_the_pdf():
    doc = _doc()
    hidden = next(s for s in doc.sections if s.enabled and s.title)
    hidden.enabled = False
    text = _good_text(doc).replace(hidden.title, "")
    assert "sections_missing" not in _codes(check_text(text, doc))


def test_ligatures_are_flagged_because_they_break_keyword_search():
    doc = _doc()
    report = check_text(_good_text(doc) + "\nOﬃce of the CTO", doc)
    assert "ligatures" in _codes(report)
    assert report.ok is True  # a warning: the CV is still readable


def test_normalize_repairs_ligatures_and_accents():
    assert normalize("Oﬃce") == "Office"
    assert normalize("Khôi") == "Khoi"
    assert all(normalize(lig) == plain for lig, plain in LIGATURES.items())


# --------------------------------------------------------------------------- #
# keyword coverage against the job
# --------------------------------------------------------------------------- #
def test_keyword_coverage_splits_found_from_missing():
    doc = _doc()
    report = check_text(_good_text(doc), doc, job_skills=["Java", "Spring Boot", "Kubernetes"])
    assert "Java" in report.keywords_found
    assert "Spring Boot" in report.keywords_found  # multi-word: every token must appear
    assert report.keywords_missing == ["Kubernetes"]


def test_a_missing_keyword_never_blocks_approval():
    """The gap report already tells you what the CV lacks. Blocking here would
    push people to pad the CV with skills they don't have — the exact thing the
    tailor guardrail exists to prevent."""
    doc = _doc()
    report = check_text(_good_text(doc), doc, job_skills=["Kubernetes", "Terraform"])
    assert report.keywords_missing == ["Kubernetes", "Terraform"]
    assert report.ok is True


def test_keyword_matching_survives_a_ligature_in_the_pdf():
    doc = _doc()
    text = _good_text(doc) + "\nBuilt a workﬂow engine"
    report = check_text(text, doc, job_skills=["workflow"])
    assert report.keywords_found == ["workflow"]


# --------------------------------------------------------------------------- #
# the extractor is not the document
# --------------------------------------------------------------------------- #
def _squashed(doc) -> str:
    """What pypdf returned for a real, perfectly good Awesome-CV build."""
    return _good_text(doc).replace(" ", "")


def test_an_extractor_that_loses_spaces_does_not_invent_findings():
    """The first real build of this checker reported a good CV as broken:
    pypdf returned "FRESHERSOFTWAREENGINEER" and "WorkExperience", so the
    section headings looked missing. pdfminer.six read the same file correctly.
    Blaming the document for the tool's limitation is worse than not checking —
    it sends someone off to fix a template that was already right."""
    doc = _doc()
    report = check_text(_squashed(doc), doc, spacing_reliable=False)
    assert report.ok is True
    assert _codes(report) == set()


def test_the_same_text_from_a_trustworthy_extractor_is_still_judged_strictly():
    """Loosening is a concession to a weak engine, not the new default — a
    reliable extractor reporting run-together text is reporting a real fault."""
    doc = _doc()
    report = check_text(_squashed(doc), doc, spacing_reliable=True)
    assert "sections_missing" in _codes(report)


def test_keyword_coverage_also_tolerates_lost_spaces():
    doc = _doc()
    report = check_text(
        _squashed(doc), doc, job_skills=["Spring Boot", "Kubernetes"], spacing_reliable=False
    )
    assert report.keywords_found == ["Spring Boot"]
    assert report.keywords_missing == ["Kubernetes"]


def test_the_report_names_the_engine_that_read_the_pdf():
    """A finding means different things depending on which engine produced it,
    so the report says which one did."""
    doc = _doc()
    report = check_text(_good_text(doc), doc)
    report.engine = "pdfminer.six"
    assert report.as_dict()["engine"] == "pdfminer.six"
