"""The email channel — the only one that can send without a second confirmation.

Because of that it is deliberately hard to fire by accident. ``build_email`` is
pure: it assembles the message and reports which gate would stop it, without
touching a socket. ``send_email`` is the only function that talks to a mail
server, and it refuses unless every gate is open.

Gate order (jobpilot/config.py ``EmailCfg``):
  1. ``apply.email.enabled``       — off: nothing is built for sending at all
  2. ``apply.email.dry_run``       — on: message is built and recorded, not sent
  3. ``apply.email.test_recipient``— set: delivered to you, not the employer
"""

from __future__ import annotations

import re
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

from jobpilot.config import ApplyCfg, Secrets

# Good enough to catch "apply via the website" sitting in apply_target; real
# validation is the mail server's job.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailError(RuntimeError):
    """The message could not be built or delivered."""


@dataclass
class OutgoingEmail:
    """A fully assembled message plus why it will or won't be sent."""

    to: str
    subject: str
    body: str
    from_addr: str
    from_name: str = ""
    attachments: list[Path] = field(default_factory=list)
    # Set when test_recipient redirected delivery away from the employer.
    intended_to: str | None = None
    dry_run: bool = True
    # Our own Message-ID, minted here rather than left to the SMTP server.
    # A reply quotes it back in In-Reply-To, which is the one way to tie an
    # employer's answer to this application without guessing from names and
    # domains — so it has to be a value we recorded, not one we never saw.
    message_id: str = field(default_factory=lambda: make_msgid(domain="jobpilot.local"))

    @property
    def redirected(self) -> bool:
        return self.intended_to is not None and self.intended_to != self.to

    def as_message(self) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = f"{self.from_name} <{self.from_addr}>" if self.from_name else self.from_addr
        msg["To"] = self.to
        msg["Subject"] = self.subject
        msg["Message-ID"] = self.message_id
        body = self.body
        if self.redirected:
            # Make it obvious in the inbox that this is a rehearsal.
            body = (
                f"[JobPilot test delivery — this would have gone to {self.intended_to}]\n\n{body}"
            )
        msg.set_content(body)
        for path in self.attachments:
            data = Path(path).read_bytes()
            msg.add_attachment(
                data, maintype="application", subtype="pdf", filename=Path(path).name
            )
        return msg

    def summary(self) -> dict:
        """Recorded on the Application row — everything except the attachment bytes."""
        return {
            "to": self.to,
            "intended_to": self.intended_to,
            "redirected": self.redirected,
            "subject": self.subject,
            "from": self.from_addr,
            "attachments": [Path(p).name for p in self.attachments],
            "dry_run": self.dry_run,
            "body_preview": self.body[:400],
            # Recorded even on a dry run, where it addresses nothing — the row
            # then says plainly that no thread exists to match a reply against,
            # rather than leaving a reader to wonder whether one was lost.
            "message_id": self.message_id,
        }


def recipient_of(apply_target: str | None) -> str:
    """The employer address from ``Job.apply_target``, or '' if it isn't one."""
    target = (apply_target or "").strip()
    if target.lower().startswith("mailto:"):
        target = target[7:]
    return target if _EMAIL_RE.match(target) else ""


def build_email(
    *,
    cfg: ApplyCfg,
    to: str,
    subject: str,
    body: str,
    attachments: list[Path] | None = None,
) -> OutgoingEmail:
    """Assemble the message. Raises ``EmailError`` if a gate or input blocks it."""
    blocker = cfg.email_blocker()
    if blocker:
        raise EmailError(blocker)
    if not recipient_of(to):
        raise EmailError(f"no usable email address for this job (apply_target={to!r})")

    target = cfg.email.test_recipient.strip() or to
    return OutgoingEmail(
        to=target,
        intended_to=to,
        subject=subject,
        body=body,
        from_addr=cfg.email.from_addr,
        from_name=cfg.email.from_name,
        attachments=[Path(a) for a in (attachments or [])],
        dry_run=cfg.email.dry_run,
    )


def send_email(email: OutgoingEmail, secrets: Secrets, timeout: int = 30) -> str:
    """Hand the message to an SMTP server. Returns a short delivery note.

    Refuses on a dry run — callers decide whether to send; this never guesses.
    """
    if email.dry_run:
        raise EmailError("refusing to send: apply.email.dry_run is on")
    if not secrets.smtp_host:
        raise EmailError("SMTP_HOST is not set — configure .env or turn dry_run back on")

    message = email.as_message()
    port = secrets.smtp_port or 587
    try:
        if port == 465:
            server: smtplib.SMTP = smtplib.SMTP_SSL(secrets.smtp_host, port, timeout=timeout)
        else:
            server = smtplib.SMTP(secrets.smtp_host, port, timeout=timeout)
        with server:
            if port != 465:
                # STARTTLS where the server offers it; a local test server won't.
                server.ehlo()
                if server.has_extn("starttls"):
                    server.starttls()
                    server.ehlo()
            if secrets.smtp_user:
                server.login(secrets.smtp_user, secrets.smtp_password)
            server.send_message(message)
    except smtplib.SMTPException as exc:
        raise EmailError(f"SMTP error: {exc}") from exc
    except OSError as exc:
        raise EmailError(f"could not reach {secrets.smtp_host}:{port} — {exc}") from exc

    return f"sent to {email.to} via {secrets.smtp_host}:{port}"
