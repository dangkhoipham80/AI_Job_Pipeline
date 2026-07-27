"""Slack Bolt app (Socket Mode) — the secondary control surface.

Two halves, both thin:

* **Out** — a WebSocket subscriber that mirrors interesting API events into the
  channel (``events.notification_for``).
* **In**  — button handlers that call the REST API. Every action goes through
  the same endpoint the dashboard uses, so pressing Approve in Slack and
  pressing it in the browser are literally the same code path (PLAN.md §10:
  one source of truth).

Socket Mode means no public URL. Run with ``python -m jobpilot.cli slack``.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass

from jobpilot.config import get_secrets
from jobpilot.slack import blocks as B
from jobpilot.slack.client import ApiError, JobPilotClient
from jobpilot.slack.events import Notification, digest, notification_for

log = logging.getLogger("jobpilot.slack")

WEB_BASE = "http://localhost:5173"
API_BASE = "http://127.0.0.1:8000"


class SlackNotConfigured(RuntimeError):
    """Missing SDK or tokens — reported instead of a stack trace."""


@dataclass
class SlackConfig:
    bot_token: str
    app_token: str
    channel_id: str
    api_base: str = API_BASE
    web_base: str = WEB_BASE

    @classmethod
    def from_secrets(cls) -> "SlackConfig":
        s = get_secrets()
        missing = [
            name
            for name, value in (
                ("SLACK_BOT_TOKEN", s.slack_bot_token),
                ("SLACK_APP_TOKEN", s.slack_app_token),
                ("SLACK_CHANNEL_ID", s.slack_channel_id),
            )
            if not value
        ]
        if missing:
            raise SlackNotConfigured(
                "Slack is not configured — set " + ", ".join(missing) + " in .env"
            )
        return cls(
            bot_token=s.slack_bot_token,
            app_token=s.slack_app_token,
            channel_id=s.slack_channel_id,
        )


def _require_bolt():
    try:
        from slack_bolt import App
        from slack_bolt.adapter.socket_mode import SocketModeHandler
    except ImportError as exc:  # pragma: no cover - env dependent
        raise SlackNotConfigured(
            "slack-bolt is not installed — run: pip install -e '.[slack]'"
        ) from exc
    return App, SocketModeHandler


def build_app(cfg: SlackConfig, client: JobPilotClient):
    """Wire the button handlers. Split out so tests can inspect the dispatch table."""
    App, _ = _require_bolt()
    app = App(token=cfg.bot_token)

    def handle(action_id: str):
        method = B.ACTIONS[action_id]

        def _handler(ack, body, say, logger):  # pragma: no cover - needs Slack
            ack()
            job_id = body["actions"][0]["value"]
            try:
                getattr(client, method)(job_id)
                job = client.job(job_id)
                say(
                    text=f"{method} → {job['status']}",
                    blocks=[
                        B.section(f"*{job['title']}* → `{job['status']}`"),
                        B.context(f"{method} via Slack · `{job_id}`"),
                    ],
                )
            except ApiError as exc:
                logger.warning("slack action %s failed: %s", action_id, exc)
                say(
                    text=f"{method} failed",
                    blocks=B.error_card(job_id, f"Could not {method}", exc.detail),
                )

        return _handler

    for action_id in B.ACTIONS:
        app.action(action_id)(handle(action_id))

    # Link buttons carry a url and no server-side effect; ack them so Slack
    # doesn't show the "this app isn't responding" warning.
    app.action(re.compile(r"^open_\d+$"))(lambda ack: ack())
    return app


def post(client_slack, channel: str, note: Notification) -> None:
    """Post one notification, falling back to plain text if the blocks are bad."""
    problems = B.check_blocks(note.blocks)
    if problems:
        log.warning("dropping malformed blocks for %s: %s", note.job_id, problems)
        client_slack.chat_postMessage(channel=channel, text=note.text)
        return
    client_slack.chat_postMessage(channel=channel, text=note.text, blocks=note.blocks)


def mirror_events(
    cfg: SlackConfig, client: JobPilotClient, slack_client
) -> None:  # pragma: no cover
    """Subscribe to the API's WebSocket and mirror what matters into the channel."""
    try:
        from websockets.sync.client import connect
    except ImportError:
        log.warning("websockets not installed — Slack will not mirror live events")
        return

    ws_url = cfg.api_base.replace("http", "ws", 1) + f"/ws?token={client.token}"
    while True:
        try:
            with connect(ws_url) as ws:
                log.info("mirroring JobPilot events into Slack")
                while True:
                    event = json.loads(ws.recv())
                    try:
                        note = notification_for(event, client, cfg.web_base)
                    except ApiError as exc:
                        log.warning("could not build a message for %s: %s", event, exc)
                        continue
                    if note:
                        post(slack_client, cfg.channel_id, note)
        except Exception as exc:
            log.warning("event mirror disconnected (%s); retrying in 5s", exc)
            threading.Event().wait(5)


def run(api_base: str = API_BASE, web_base: str = WEB_BASE) -> None:  # pragma: no cover
    """Start the Slack app. Raises ``SlackNotConfigured`` with a clear message."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = SlackConfig.from_secrets()
    cfg.api_base, cfg.web_base = api_base, web_base

    _, SocketModeHandler = _require_bolt()
    client = JobPilotClient(base_url=api_base)
    try:
        client.health()
    except ApiError as exc:
        raise SlackNotConfigured(
            f"the JobPilot API is not reachable at {api_base} — start it with "
            f"`python -m jobpilot.cli serve` ({exc.detail})"
        ) from exc

    app = build_app(cfg, client)
    slack_client = app.client

    for note in digest(client, web_base=web_base):
        post(slack_client, cfg.channel_id, note)

    threading.Thread(target=mirror_events, args=(cfg, client, slack_client), daemon=True).start()
    SocketModeHandler(app, cfg.app_token).start()
