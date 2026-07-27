"""Read job-alert emails from *your own* mailbox over IMAP.

This is the whole reason the LinkedIn source is possible at all. LinkedIn's
robots.txt forbids automated access to its job pages — including the logged-out
``/jobs-guest/`` endpoint — so JobPilot never crawls them. Instead you set up
LinkedIn **Job Alerts**, which is LinkedIn's own mechanism for pushing matching
jobs to you, and this reads the resulting messages out of your inbox.

Nothing here talks to LinkedIn. It talks to your mail server, with your
credentials, about your mail.

Gmail needs an **App Password** (2-Step Verification must be on) — a normal
account password is rejected.
"""

from __future__ import annotations

import email
import imaplib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import Message
from typing import Protocol

from jobpilot.config import Secrets, get_secrets
from jobpilot.timeutil import vn_now

log = logging.getLogger(__name__)

# Senders LinkedIn uses for job alerts. Kept broad: the exact address has
# changed over the years and varies by locale.
LINKEDIN_SENDERS = (
    "jobalerts-noreply@linkedin.com",
    "jobs-noreply@linkedin.com",
    "jobs-listings@linkedin.com",
    "notifications-noreply@linkedin.com",
)


class MailboxError(RuntimeError):
    """Could not reach or read the mailbox. The message is safe to show a user."""


@dataclass
class MailMessage:
    """One email, reduced to what a parser needs."""

    uid: str
    subject: str
    sender: str
    date: datetime | None
    html: str

    def __repr__(self) -> str:  # keep mail bodies out of logs and tracebacks
        return f"MailMessage(uid={self.uid!r}, subject={self.subject!r})"


class Mailbox(Protocol):
    """Anything that can hand back recent alert emails. Tests inject a fake."""

    def fetch(self, senders: tuple[str, ...], since_days: int, limit: int) -> list[MailMessage]: ...


def _best_html(message: Message) -> str:
    """The HTML part of a message, falling back to plain text."""
    html, text = "", ""
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")
            if part.get_content_type() == "text/html" and not html:
                html = body
            elif part.get_content_type() == "text/plain" and not text:
                text = body
    else:
        payload = message.get_payload(decode=True)
        if payload is not None:
            charset = message.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")
            if message.get_content_type() == "text/html":
                html = body
            else:
                text = body
    return html or text


def _decode_header(raw: str | None) -> str:
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    out = []
    for value, charset in parts:
        if isinstance(value, bytes):
            out.append(value.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(value)
    return "".join(out)


class ImapMailbox:
    """IMAP over SSL. Read-only: the mailbox is examined, never modified."""

    def __init__(self, secrets: Secrets | None = None, folder: str = "INBOX") -> None:
        self.secrets = secrets or get_secrets()
        self.folder = folder

    def _connect(self) -> imaplib.IMAP4_SSL:
        s = self.secrets
        if not s.imap_user or not s.imap_password:
            raise MailboxError(
                "IMAP_USER / IMAP_PASSWORD are not set in .env — for Gmail this must be "
                "an App Password (https://myaccount.google.com/apppasswords), not your "
                "account password"
            )
        try:
            conn = imaplib.IMAP4_SSL(s.imap_host, s.imap_port, timeout=30)
        except OSError as exc:
            raise MailboxError(f"cannot reach {s.imap_host}:{s.imap_port} — {exc}") from exc
        try:
            conn.login(s.imap_user, s.imap_password)
        except imaplib.IMAP4.error as exc:
            raise MailboxError(
                f"IMAP login rejected for {s.imap_user}. For Gmail: turn on 2-Step "
                f"Verification and use an App Password. ({exc})"
            ) from exc
        return conn

    def fetch(
        self, senders: tuple[str, ...] = LINKEDIN_SENDERS, since_days: int = 14, limit: int = 40
    ) -> list[MailMessage]:
        """Recent messages from any of ``senders``, newest first."""
        since = (vn_now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
        conn = self._connect()
        messages: list[MailMessage] = []
        try:
            # readonly=True: reading your mail must never mark it seen or move it.
            conn.select(self.folder, readonly=True)
            uids: list[bytes] = []
            for sender in senders:
                status, data = conn.search(None, "FROM", f'"{sender}"', "SINCE", since)
                if status == "OK" and data and data[0]:
                    uids.extend(data[0].split())

            # Newest first, and cap before fetching — bodies are large.
            for uid in sorted(set(uids), key=lambda b: int(b), reverse=True)[:limit]:
                status, payload = conn.fetch(uid, "(RFC822)")
                if status != "OK" or not payload or not isinstance(payload[0], tuple):
                    continue
                parsed = email.message_from_bytes(payload[0][1])
                messages.append(
                    MailMessage(
                        uid=uid.decode(),
                        subject=_decode_header(parsed.get("Subject")),
                        sender=_decode_header(parsed.get("From")),
                        date=_parse_date(parsed.get("Date")),
                        html=_best_html(parsed),
                    )
                )
        except imaplib.IMAP4.error as exc:
            raise MailboxError(f"IMAP error while reading {self.folder!r}: {exc}") from exc
        finally:
            try:
                conn.logout()
            except Exception:
                pass

        log.info("read %d alert email(s) from %s", len(messages), self.secrets.imap_host)
        return messages


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
