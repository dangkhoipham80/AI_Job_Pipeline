"""Inline markup -> LaTeX, with escaping.

CV content lives in JSON as plain text with a tiny Markdown-ish subset, so neither
the user (CV Studio forms) nor the agent (Phase 5 tailor) has to write LaTeX, and
stray ``%``/``&``/``_`` in a job description can't break the build:

    **bold**        -> \\textbf{bold}
    `Spring Boot`   -> \\tech{Spring Boot}       (bold + awesome accent colour)
    ~React~         -> \\techfe{React}           (front-end accent colour)
    [label](url)    -> \\hreficon{url}{label}    (link + external-link icon)

Everything outside those markers is escaped. Markup does not nest; the outermost
match wins and its body is escaped as plain text (link labels are the exception --
they are rendered recursively so ``[**Foo** `Java`](url)`` works).
"""

from __future__ import annotations

import re

# LaTeX special characters, longest-first so the backslash rule can't re-escape
# the replacements it just emitted.
_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_ESCAPE_RE = re.compile("|".join(re.escape(c) for c in _ESCAPES))

# Ordered: link first (its label may contain other markers), then the paired
# delimiters. Non-greedy bodies with no newline so an unmatched marker degrades
# to literal text instead of swallowing the rest of the line.
_INLINE_RE = re.compile(
    r"""
    (?P<link>\[(?P<link_label>[^\]\n]+)\]\((?P<link_url>[^)\s]+)\))
  | (?P<bold>\*\*(?P<bold_body>[^\n]+?)\*\*)
  | (?P<tech>`(?P<tech_body>[^`\n]+)`)
  | (?P<techfe>~(?P<techfe_body>[^~\n]+)~)
    """,
    re.VERBOSE,
)


def escape_tex(text: str) -> str:
    """Escape LaTeX specials in a plain-text run."""
    return _ESCAPE_RE.sub(lambda m: _ESCAPES[m.group()], text)


def tex(text: str | None) -> str:
    """Convert inline markup to LaTeX, escaping everything else.

    This is the only path from JSON content to ``.tex``; templates must never
    interpolate raw user text.
    """
    if not text:
        return ""
    out: list[str] = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        out.append(escape_tex(text[pos : m.start()]))
        if m.group("link"):
            # URLs go through \href verbatim except for '#' and '%', which xelatex
            # still reads as special even inside \href.
            url = m.group("link_url").replace("#", r"\#").replace("%", r"\%")
            out.append(rf"\hreficon{{{url}}}{{{tex(m.group('link_label'))}}}")
        elif m.group("bold"):
            out.append(rf"\textbf{{{escape_tex(m.group('bold_body'))}}}")
        elif m.group("tech"):
            out.append(rf"\tech{{{escape_tex(m.group('tech_body'))}}}")
        else:
            out.append(rf"\techfe{{{escape_tex(m.group('techfe_body'))}}}")
        pos = m.end()
    out.append(escape_tex(text[pos:]))
    return "".join(out)
