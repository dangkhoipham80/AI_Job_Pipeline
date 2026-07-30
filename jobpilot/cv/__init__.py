"""CV Studio: structured JSON is the source of truth for CV content (PLAN.md §5.6.1).

Pipeline: ``CvDocument`` (JSON) -> Jinja2 -> ``cv.tex`` + ``resume/*.tex`` -> Docker
LaTeX -> PDF. Both the human editor (web CV Studio) and the agent tailor (Phase 5)
write the same JSON, so every change round-trips and is versioned in ``cv_versions``.
"""

from jobpilot.cv.schema import CvDocument

__all__ = ["CvDocument"]
