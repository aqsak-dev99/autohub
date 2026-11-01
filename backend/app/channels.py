"""Outbound replies: the single exit point for every message AutoHub sends.

`send_reply` is used by the Lead Handler and the Daily Digest. Every send ends as one of:

- dry_run:  SEND_MODE is dry_run, email isn't configured, the channel is answered
            on screen (website chat), or the address isn't on the allowlist.
            Recorded with the reason; nothing leaves.
- smtp:     really sent by email.
- DeliveryError: the mail server refused. The step fails visibly and the run can be retried.

Channels are pluggable: a new one (WhatsApp, Telegram, SMS) is another branch here
plus an intake route, and nothing else in the Lead Handler changes. WhatsApp was built
and tested this way, then removed because Meta only lets verified businesses send
(see docs/DECISIONS.md, decision 53).
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.config import Settings, get_settings

EMAIL_CHANNELS = {"email", "web_form"}  # contact-form leads leave an email address, so they get email replies


class DeliveryError(Exception):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


def _smtp_send(settings: Settings, message: EmailMessage) -> None:  # tests replace this
    with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)


def send_reply(channel: str, contact: str, text: str, settings: Settings | None = None, *,
               subject: str | None = None, in_reply_to: str | None = None) -> dict:
    """Send `text` to `contact`. For email, `subject` and `in_reply_to` keep the reply in the customer's thread."""
    settings = settings or get_settings()
    if channel in EMAIL_CHANNELS and "@" in contact:
        return _send_email(settings, channel, contact.strip(), text, subject, in_reply_to)
    return {"channel": channel, "to": contact, "characters": len(text), "delivered": False, "mode": "dry_run",
            "note": "website chat replies are shown where the customer asked, not sent"
            if channel == "web_chat" else f"no email address to reply to on {channel}"}


def reply_subject(original: str | None, fallback: str) -> str:
    if not original or not original.strip():
        return fallback
    original = original.strip()
    return original if original.lower().startswith("re:") else f"Re: {original}"


def _send_email(settings: Settings, channel: str, to: str, text: str, subject: str | None,
                in_reply_to: str | None) -> dict:
    subject = subject or f"Your enquiry to {settings.email_from_name}"
    base = {"channel": channel, "to": to, "subject": subject, "characters": len(text)}

    def dry_run(reason: str) -> dict:
        return {**base, "delivered": False, "mode": "dry_run", "note": reason}

    if settings.send_mode != "live":
        return dry_run("SEND_MODE is dry_run")
    if not settings.email_configured:
        return dry_run("SMTP_USERNAME / SMTP_PASSWORD are not set")
    allow = settings.email_allowlist
    if allow and to.lower() not in allow:
        return dry_run(f"{to} is not on EMAIL_SEND_ALLOWLIST")

    message = EmailMessage()
    message["From"] = formataddr((settings.email_from_name, settings.smtp_username))
    message["To"] = to
    message["Subject"] = subject
    message["Message-ID"] = make_msgid(domain=settings.smtp_username.split("@")[-1])
    if in_reply_to:
        # these two headers make Gmail, Outlook etc. show the reply inside the customer's conversation
        message["In-Reply-To"] = in_reply_to
        message["References"] = in_reply_to
    message.set_content(text)

    try:
        _smtp_send(settings, message)
    except smtplib.SMTPAuthenticationError as exc:
        raise DeliveryError("Gmail rejected the login: SMTP_PASSWORD must be a Google app password", 535) from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise DeliveryError(f"The mail server refused the address {to}", 550) from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise DeliveryError(f"Email not sent: {type(exc).__name__}: {exc}") from exc
    return {**base, "delivered": True, "mode": "smtp", "message_id": message["Message-ID"]}
