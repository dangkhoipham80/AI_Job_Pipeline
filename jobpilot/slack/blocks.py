"""Block Kit message builders — pure functions, no Slack SDK, no I/O.

Keeping these pure is what makes the Slack surface testable without a workspace:
every message shape is asserted in ``tests/test_slack.py`` against the same
limits Slack enforces (``check_blocks``).

Buttons carry the job id in ``value`` and the verb in ``action_id``, so the
handler in ``app.py`` is a small dispatch table and every action ends up calling
the REST API — never the database.
"""

from __future__ import annotations

from typing import Any

# Slack's documented limits. Exceeding them is a 400 from the API, so the
# builders truncate rather than gamble.
MAX_BLOCKS = 50
MAX_SECTION_TEXT = 3000
MAX_BUTTON_TEXT = 75
MAX_BUTTON_VALUE = 2000
MAX_ACTIONS_ELEMENTS = 25

# action_id -> the client method app.py should call. Adding a button means
# adding a row here; the handler needs no new branches.
ACTIONS = {
    "job_shortlist": "shortlist",
    "job_skip": "skip",
    "job_tailor": "tailor",
    "job_approve": "approve",
    "job_reject": "reject",
    "job_apply": "apply",
    "job_confirm_submit": "confirm_submit",
}


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def section(text: str) -> dict:
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": _truncate(text, MAX_SECTION_TEXT)},
    }


def context(text: str) -> dict:
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": _truncate(text, MAX_SECTION_TEXT)}],
    }


def button(text: str, action_id: str, value: str, style: str | None = None) -> dict:
    element: dict[str, Any] = {
        "type": "button",
        "text": {"type": "plain_text", "text": _truncate(text, MAX_BUTTON_TEXT), "emoji": True},
        "action_id": action_id,
        "value": _truncate(value, MAX_BUTTON_VALUE),
    }
    if style:
        element["style"] = style
    return element


def link_button(text: str, url: str) -> dict:
    """A link button needs no action_id handler — Slack just opens the URL."""
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": _truncate(text, MAX_BUTTON_TEXT), "emoji": True},
        "url": url,
        "action_id": f"open_{abs(hash(url)) % 10_000}",
    }


def actions(*elements: dict) -> dict:
    return {"type": "actions", "elements": list(elements[:MAX_ACTIONS_ELEMENTS])}


def check_blocks(blocks: list[dict]) -> list[str]:
    """Validate against Slack's limits. Empty list means the message will post."""
    problems: list[str] = []
    if len(blocks) > MAX_BLOCKS:
        problems.append(f"{len(blocks)} blocks (max {MAX_BLOCKS})")
    for i, block in enumerate(blocks):
        if block.get("type") == "section":
            text = block.get("text", {}).get("text", "")
            if len(text) > MAX_SECTION_TEXT:
                problems.append(f"block {i}: section text {len(text)} chars")
        if block.get("type") == "actions":
            elements = block.get("elements", [])
            if len(elements) > MAX_ACTIONS_ELEMENTS:
                problems.append(f"block {i}: {len(elements)} action elements")
            for element in elements:
                if "action_id" not in element:
                    problems.append(f"block {i}: an element has no action_id")
                value = element.get("value", "")
                if len(value) > MAX_BUTTON_VALUE:
                    problems.append(f"block {i}: button value {len(value)} chars")
                label = element.get("text", {}).get("text", "")
                if len(label) > MAX_BUTTON_TEXT:
                    problems.append(f"block {i}: button label {len(label)} chars")
    return problems


# --------------------------------------------------------------------------- #
# Messages
# --------------------------------------------------------------------------- #
def _web_url(job_id: str, web_base: str, suffix: str = "") -> str:
    from urllib.parse import quote

    return f"{web_base.rstrip('/')}/jobs/{quote(job_id, safe='')}{suffix}"


def _match(score: float | None) -> str:
    return f"{round((score or 0) * 100)}%"


def job_card(job: dict, web_base: str = "http://localhost:5173") -> list[dict]:
    """A newly discovered job: enough to decide shortlist vs skip, nothing more."""
    fresh = "🔥 " if job.get("is_fresh") else ""
    facts = [job.get("company") or "?"]
    for key in ("location", "salary", "level"):
        if job.get(key):
            facts.append(str(job[key]))
    facts.append(f"match {_match(job.get('match_score'))}")

    blocks = [
        section(f"*{fresh}{job.get('title', 'Untitled')}*\n{' · '.join(facts)}"),
    ]
    skills = job.get("skills") or []
    if skills:
        blocks.append(context("`" + "`  `".join(skills[:12]) + "`"))
    blocks.append(
        actions(
            button("Shortlist", "job_shortlist", job["id"], style="primary"),
            button("Skip", "job_skip", job["id"]),
            *([link_button("Posting", job["url"])] if job.get("url") else []),
        )
    )
    blocks.append(context(f"`{job['id']}` · <{_web_url(job['id'], web_base)}|open in dashboard>"))
    return blocks


def review_card(job: dict, review: dict, web_base: str = "http://localhost:5173") -> list[dict]:
    """A tailored CV waiting for a decision — the gaps are shown, never hidden."""
    plan = review.get("plan") or {}
    pages = review.get("pages")
    page_note = "" if pages in (None, 1) else f"  ⚠️ *{pages} pages*"

    blocks = [
        section(
            f"*CV tailored — {job.get('title', 'Untitled')}*\n"
            f"{job.get('company', '?')} · match {_match(review.get('match_score'))} · "
            f"v{review.get('version', 0)}{page_note}"
        )
    ]

    changes = plan.get("changes") or []
    if changes:
        lines = [f"• {c['what']} _({c['reason']})_" for c in changes[:6]]
        blocks.append(section("*Changes*\n" + "\n".join(lines)))

    gaps = review.get("gaps") or []
    if gaps:
        listed = ", ".join(g["text"] for g in gaps[:8])
        blocks.append(section(f"*Not on your CV* — left off deliberately\n{listed}"))

    blocks.append(
        actions(
            button("Approve", "job_approve", job["id"], style="primary"),
            button("Skip", "job_reject", job["id"], style="danger"),
            link_button("Review in browser", _web_url(job["id"], web_base, "/review")),
        )
    )
    blocks.append(context("To ask for a change, use the dashboard — Slack keeps the quick calls."))
    return blocks


def apply_card(job: dict, outcome: dict, web_base: str = "http://localhost:5173") -> list[dict]:
    """What happened when we dispatched. ``result`` drives the wording *and* the
    buttons, so a dry run never looks like a delivered application."""
    result = outcome.get("result")
    channel = outcome.get("channel", "?")
    headline = {
        "success": "✅ *Application sent*",
        "dry_run": "🧪 *Prepared — not sent* (dry run)",
        "awaiting_user": "🙋 *Your turn to submit*",
        "failed": "❌ *Apply failed*",
    }.get(result, f"*{result}*")

    blocks = [
        section(
            f"{headline}\n{job.get('title', 'Untitled')} · {job.get('company', '?')} · {channel}"
        ),
        context(outcome.get("detail", "")),
    ]

    email = outcome.get("email")
    if email:
        line = f"→ `{email['to']}`"
        if email.get("redirected"):
            line += f"  _(test redirect; the employer address is {email['intended_to']})_"
        if email.get("attachments"):
            line += f" · {', '.join(email['attachments'])}"
        blocks.append(context(line))

    handoff = outcome.get("handoff")
    if handoff:
        fields = handoff.get("fields") or {}
        pairs = "\n".join(f"• *{k}*: {v}" for k, v in list(fields.items())[:8])
        blocks.append(section(f"*Paste these into the form*\n{pairs}"))

    elements = []
    if result == "awaiting_user":
        elements.append(button("I submitted it", "job_confirm_submit", job["id"], style="primary"))
        if handoff and handoff.get("url"):
            elements.append(link_button("Open form", handoff["url"]))
    elif result in ("failed", "dry_run"):
        elements.append(button("Try again", "job_apply", job["id"]))
    elements.append(link_button("Dashboard", f"{web_base.rstrip('/')}/applications"))
    blocks.append(actions(*elements))
    return blocks


def crawl_card(stats: dict, web_base: str = "http://localhost:5173") -> list[dict]:
    """Posted after a crawl so you know there is something to look at."""
    by_source = stats.get("by_source") or {}
    sources = ", ".join(f"{k} {v}" for k, v in sorted(by_source.items())) or "none"
    return [
        section(
            f"*Crawl finished* — {stats.get('total', 0)} jobs tracked, "
            f"{stats.get('fresh', 0)} posted in the last 48h"
        ),
        context(f"by source: {sources} · <{web_base.rstrip('/')}/jobs|browse>"),
    ]


def result_card(
    job: dict, event_type: str, label: str = "", web_base: str = "http://localhost:5173"
) -> list[dict]:
    """An employer moved (Phase 18): an interview, an offer, a rejection.

    No buttons. Recording an outcome from a phone is a Phase 19 problem, and a
    button that only re-opens the dashboard is worse than a link that says so.
    """
    headline = {
        "interview": "🎙️ *Interview*",
        "offer": "🎉 *Offer*",
        "rejected": "🙅 *Rejected*",
    }.get(event_type, f"*{event_type}*")

    blocks = [
        section(f"{headline}\n{job.get('title', 'Untitled')} · {job.get('company', '?')}"),
    ]
    if label:
        blocks.append(context(_truncate(label, 200)))
    blocks.append(actions(link_button("Dashboard", f"{web_base.rstrip('/')}/applications")))
    return blocks


def error_card(job_id: str, title: str, reason: str) -> list[dict]:
    """Failures get a message too — PLAN.md §5.4 wants the cause, not a silence."""
    return [
        section(f"❌ *{title}*\n```{_truncate(reason, 1500)}```"),
        context(f"`{job_id}`"),
    ]
