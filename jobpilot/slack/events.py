"""Turn WebSocket events from the API into Slack messages.

The backend broadcasts thin events (an id and a status) and knows nothing about
Slack. This module is the whole coupling: it decides which events are worth a
notification and fetches the detail over REST to render them.

Deliberately quiet. Mirroring every transition would make the channel unusable —
the dashboard is the place to watch things move. Slack gets the moments where a
human decision or a failure is involved.
"""

from __future__ import annotations

from dataclasses import dataclass

from jobpilot.slack import blocks as B
from jobpilot.slack.client import ApiError, JobPilotClient

# Statuses that are only ever reached as a side effect of an event we already
# report, so mirroring them would double-post.
_QUIET_STATUSES = {"DISCOVERED", "SHORTLISTED", "TAILORING", "REVIEW", "APPROVED", "SUBMITTING"}

# Outcomes worth interrupting someone for: the employer moved. The rest
# (``replied``, ``withdrawn``, ``ghosted``) are things you just typed in
# yourself, and echoing them back is how a channel becomes noise you mute.
_LOUD_OUTCOMES = {"interview", "offer", "rejected"}


@dataclass
class Notification:
    kind: str  # review | apply | error
    job_id: str | None
    text: str  # plain-text fallback, used for the push notification
    blocks: list[dict]


def outcome_from_application(app: dict) -> dict:
    """Adapt an Applications-board row to the shape ``apply_card`` renders."""
    meta = app.get("meta") or {}
    detail = app.get("error_msg") or ""
    if not detail:
        handoff = meta.get("handoff") or {}
        detail = handoff.get("note", "")
    return {
        "result": app.get("result"),
        "channel": app.get("channel"),
        "detail": detail,
        "email": meta.get("email"),
        "handoff": meta.get("handoff"),
    }


def notification_for(
    event: dict, client: JobPilotClient, web_base: str = "http://localhost:5173"
) -> Notification | None:
    """The Slack message this event deserves, or None to stay quiet."""
    kind = event.get("type")
    job_id = event.get("id")

    if kind == "tailor_done" and job_id:
        job = client.job(job_id)
        review = client.review(job_id)
        return Notification(
            kind="review",
            job_id=job_id,
            text=f"CV tailored for {job.get('title')} at {job.get('company')}",
            blocks=B.review_card(job, review, web_base),
        )

    if kind == "apply_done" and job_id:
        job = client.job(job_id)
        row = client.application_for(job_id)
        outcome = (
            outcome_from_application(row)
            if row
            else {"result": event.get("result"), "channel": event.get("channel"), "detail": ""}
        )
        return Notification(
            kind="apply",
            job_id=job_id,
            text=f"Apply {outcome.get('result')} — {job.get('title')}",
            blocks=B.apply_card(job, outcome, web_base),
        )

    if kind == "outcome_recorded":
        event_type = event.get("event_type")
        outcome_job_id = event.get("job_id")
        if event_type not in _LOUD_OUTCOMES or not outcome_job_id:
            return None
        try:
            job = client.job(outcome_job_id)
        except ApiError:
            return None
        return Notification(
            kind="outcome",
            job_id=outcome_job_id,
            text=f"{event_type.title()} — {job.get('title')} at {job.get('company')}",
            blocks=B.result_card(job, event_type, event.get("label") or "", web_base),
        )

    if kind == "job_updated" and job_id and event.get("status") == "FAILED":
        try:
            job = client.job(job_id)
        except ApiError:
            return None
        row = client.application_for(job_id)
        reason = (row.get("error_msg") if row else None) or "see the dashboard for details"
        return Notification(
            kind="error",
            job_id=job_id,
            text=f"Failed — {job.get('title')}",
            blocks=B.error_card(job_id, f"{job.get('title')} at {job.get('company')}", reason),
        )

    if kind == "job_updated" and event.get("status") in _QUIET_STATUSES:
        return None
    return None


def digest(
    client: JobPilotClient, limit: int = 5, web_base: str = "http://localhost:5173"
) -> list[Notification]:
    """A crawl summary plus the freshest undecided jobs — what Slack is for."""
    out = [
        Notification(
            kind="crawl",
            job_id=None,
            text="JobPilot digest",
            blocks=B.crawl_card(client.stats(), web_base),
        )
    ]
    for job in client.jobs(status="DISCOVERED", limit=limit):
        detail = client.job(job["id"])
        out.append(
            Notification(
                kind="job",
                job_id=job["id"],
                text=f"{detail.get('title')} at {detail.get('company')}",
                blocks=B.job_card(detail, web_base),
            )
        )
    return out
