"""Outbound replies (WhatsApp and email), and the webhook signature checks.

`send_reply` is the single exit point for messages, used by the Lead Handler
and the Daily Digest. Every send ends as one of:

- dry_run:  SEND_MODE is dry_run, the provider isn't configured, the channel
            can't be replied to yet (web chat), or the recipient isn't on the
            allowlist. Recorded with the reason; nothing leaves.
- meta / twilio / smtp: really sent.
- DeliveryError: the provider refused. The step fails visibly and the run can
            be retried.

Two providers sit behind the same function, chosen by WHATSAPP_PROVIDER:
Meta's WhatsApp Cloud API (the official API, used for the live demo) and
Twilio (built first; Twilio's account verification doesn't accept Pakistani
numbers). Plain httpx instead of either SDK: two small HTTP calls each don't
justify a dependency, and they're easy to read and to fake in tests.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import httpx

from app.config import Settings, get_settings, normalize_phone

TWILIO_API = "https://api.twilio.com/2010-04-01"
GRAPH_API = "https://graph.facebook.com"
WHATSAPP_MAX_CHARS = 1600  # keep under both providers' limits for one text message
EMAIL_CHANNELS = {"email", "web_form"}  # contact-form leads leave an email address, so they get email replies


class DeliveryError(Exception):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


# ---------- the two network calls (tests replace these) ----------

def _post_to_twilio(settings: Settings, data: dict) -> httpx.Response:
    return httpx.post(
        f"{TWILIO_API}/Accounts/{settings.twilio_account_sid}/Messages.json",
        data=data,
        auth=(settings.twilio_account_sid, settings.twilio_auth_token),
        timeout=15,
    )


def _post_to_meta(settings: Settings, payload: dict) -> httpx.Response:
    return httpx.post(
        f"{GRAPH_API}/{settings.meta_graph_version}/{settings.meta_phone_number_id}/messages",
        json=payload,
        headers={"Authorization": f"Bearer {settings.meta_access_token}"},
        timeout=15,
    )


def _smtp_send(settings: Settings, message: EmailMessage) -> None:
    with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)


# ---------- sending ----------

def send_reply(channel: str, contact: str, text: str, settings: Settings | None = None, *,
               subject: str | None = None, in_reply_to: str | None = None) -> dict:
    """Send `text` to `contact`. For email, `subject` and `in_reply_to` keep the reply in the customer's thread."""
    settings = settings or get_settings()
    if channel in EMAIL_CHANNELS and "@" in contact:
        return _send_email(settings, channel, contact.strip(), text, subject, in_reply_to)

    to = normalize_phone(contact) if channel == "whatsapp" else contact
    base = {"channel": channel, "to": to, "characters": len(text)}

    def dry_run(reason: str) -> dict:
        return {**base, "delivered": False, "mode": "dry_run", "note": reason}

    if channel != "whatsapp":
        return dry_run(f"{channel} replies are shown where the customer asked (website chat), not sent")
    if settings.send_mode != "live":
        return dry_run("SEND_MODE is dry_run")
    if not settings.whatsapp_configured:
        return dry_run(f"{settings.whatsapp_provider} credentials are not set")
    allow = settings.allowlist
    if allow and to not in allow:
        # the safety net that stops a demo or a test from messaging a stranger
        return dry_run(f"{to} is not on LIVE_SEND_ALLOWLIST")

    body = text if len(text) <= WHATSAPP_MAX_CHARS else text[: WHATSAPP_MAX_CHARS - 1] + "…"
    if settings.whatsapp_provider == "meta":
        return {**base, **_send_meta(settings, to, body)}
    return {**base, **_send_twilio(settings, to, body)}


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


def _send_meta(settings: Settings, to: str, body: str) -> dict:
    response = _post_to_meta(settings, {
        "messaging_product": "whatsapp", "recipient_type": "individual",
        "to": to.lstrip("+"), "type": "text", "text": {"preview_url": False, "body": body},
    })
    payload = response.json() if response.content else {}
    if response.status_code >= 400:
        error = payload.get("error") or {}
        code = error.get("code")
        raise DeliveryError(f"Meta {response.status_code} (code {code}): {error.get('message', 'unknown error')}",
                            code)
    message_id = ((payload.get("messages") or [{}])[0]).get("id")
    return {"delivered": True, "mode": "meta", "message_id": message_id}


def _send_twilio(settings: Settings, to: str, body: str) -> dict:
    response = _post_to_twilio(settings, {"From": settings.twilio_whatsapp_from, "To": f"whatsapp:{to}",
                                          "Body": body})
    payload = response.json() if response.content else {}
    if response.status_code >= 400:
        code = payload.get("code")
        raise DeliveryError(f"Twilio {response.status_code} (code {code}): {payload.get('message', 'unknown error')}",
                            code)
    return {"delivered": True, "mode": "twilio", "message_sid": payload.get("sid"),
            "twilio_status": payload.get("status")}


# ---------- webhook signatures ----------

def twilio_signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    """Twilio's X-Twilio-Signature: base64(HMAC-SHA1(token, url + each param name and value, sorted by name))."""
    data = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    digest = hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def valid_twilio_signature(auth_token: str, url: str, params: dict[str, str], signature: str | None) -> bool:
    if not signature:
        return False
    return hmac.compare_digest(twilio_signature(auth_token, url, params), signature)


def meta_signature(app_secret: str, raw_body: bytes) -> str:
    """Meta's X-Hub-Signature-256: 'sha256=' + hex(HMAC-SHA256(app secret, the exact request body))."""
    return "sha256=" + hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()


def valid_meta_signature(app_secret: str, raw_body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    return hmac.compare_digest(meta_signature(app_secret, raw_body), signature)
