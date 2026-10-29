"""Reads new email from the AutoHub inbox and turns each real enquiry into a Lead Handler run.

Called every minute by n8n (POST /api/email/poll), or by hand with
`python scripts/poll_inbox.py`. Safety rules, because this reads a real inbox
and can reply to whatever it finds:

- Only unread mail from the last EMAIL_POLL_SINCE_DAYS, at most EMAIL_POLL_MAX
  per poll, so connecting a mailbox never replies to an old backlog.
- Automated mail is skipped: auto-replies, out-of-office, newsletters and
  mailing lists, "no-reply" senders, bounces, and our own sent mail. Two
  bots answering each other forever is the classic email-automation bug.
- Each message is claimed by its Message-ID (inbound_messages) before a run
  starts, so overlapping polls never answer the same email twice.
- Quoted history ("On Mon ... wrote:", "> ...") is removed so the AI only
  sees what the customer actually wrote this time.
"""
from __future__ import annotations

import email
import hashlib
import imaplib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr

from app.config import Settings

log = logging.getLogger("autohub.email")

NO_REPLY = re.compile(r"^(no-?reply|do-?not-?reply|mailer-daemon|postmaster|notifications?|bounce[s]?)([+.\-_].*)?$",
                      re.IGNORECASE)
QUOTE_HEADER = re.compile(r"^\s*(On .{4,200} wrote:|-{2,} ?Original Message ?-{2,}|From: .+|Sent from my \w+.*)\s*$",
                          re.IGNORECASE)


@dataclass
class ParsedEmail:
    message_id: str
    sender: str
    name: str | None
    subject: str
    body: str


@dataclass
class PollResult:
    fetched: int = 0
    started: int = 0
    duplicates: int = 0
    skipped: list[dict] = field(default_factory=list)


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", html)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    return re.sub(r"[ \t]+", " ", text)


def _body_text(msg: Message) -> str:
    plain, html = None, None
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_maintype() == "multipart" or part.get("Content-Disposition", "").startswith("attachment"):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if part.get_content_type() == "text/plain" and plain is None:
            plain = text
        elif part.get_content_type() == "text/html" and html is None:
            html = text
    return plain if plain is not None else _html_to_text(html or "")


def strip_quoted(text: str) -> str:
    """Keep only the new part of a reply: cut at 'On ... wrote:' and drop '>' lines."""
    kept = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if QUOTE_HEADER.match(line):
            break
        if line.lstrip().startswith(">"):
            continue
        kept.append(line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def skip_reason(msg: Message, sender: str, own_address: str) -> str | None:
    """Why this email must not get an automatic reply, or None if it's a real enquiry."""
    if not sender or "@" not in sender:
        return "no sender address"
    if sender.lower() == own_address.lower():
        return "sent by AutoHub itself"
    if NO_REPLY.match(sender.split("@")[0]):
        return "no-reply sender"
    auto = (msg.get("Auto-Submitted") or "").strip().lower()
    if auto and auto != "no":
        return f"automated message (Auto-Submitted: {auto})"
    if (msg.get("Precedence") or "").strip().lower() in {"bulk", "junk", "list", "auto_reply"}:
        return "bulk or auto-reply (Precedence header)"
    if msg.get("List-Id") or msg.get("List-Unsubscribe"):
        return "newsletter or mailing list"
    if msg.get("X-Autoreply") or msg.get("X-Autorespond"):
        return "auto-reply"
    return None


def parse_email(raw: bytes, own_address: str) -> tuple[ParsedEmail | None, str | None]:
    """(parsed email, None) for a real enquiry, or (None, reason) for one to skip."""
    msg = email.message_from_bytes(raw)
    name, sender = parseaddr(_decode(msg.get("From")))
    reason = skip_reason(msg, sender, own_address)
    if reason:
        return None, reason
    subject = _decode(msg.get("Subject")).strip()
    body = strip_quoted(_body_text(msg))
    if not body and not subject:
        return None, "empty email"
    message_id = (msg.get("Message-ID") or "").strip()
    if not message_id:
        # rare, but dedupe still needs a stable key
        message_id = "<generated-" + hashlib.sha256(raw).hexdigest()[:32] + "@autohub>"
    return ParsedEmail(message_id=message_id, sender=sender.lower(), name=name or None, subject=subject,
                       body=body or subject), None


def dedupe_key(message_id: str) -> str:
    """Message-IDs can be long and odd; store a fixed-size hash."""
    return "email:" + hashlib.sha256(message_id.encode()).hexdigest()[:48]


# ---------- IMAP (the only network part; tests replace these two functions) ----------

def search_criteria(settings: Settings, now: datetime | None = None) -> str:
    since = (now or datetime.now(timezone.utc)) - timedelta(days=settings.email_poll_since_days)
    return f"(UNSEEN SINCE {since:%d-%b-%Y})"


def _imap_fetch(settings: Settings) -> list[tuple[bytes, bytes]]:
    """Return [(uid, raw message)] for unread mail, without marking it read yet."""
    out = []
    with imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port, timeout=20) as imap:
        imap.login(settings.smtp_username, settings.smtp_password)
        imap.select(f'"{settings.imap_folder}"')
        _, data = imap.uid("search", None, search_criteria(settings))
        uids = (data[0] or b"").split()[: settings.email_poll_max]
        for uid in uids:
            _, parts = imap.uid("fetch", uid, "(BODY.PEEK[])")  # PEEK: stays unread until we've handled it
            raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
            if raw:
                out.append((uid, raw))
    return out


def _imap_mark_seen(settings: Settings, uids: list[bytes]) -> None:
    if not uids:
        return
    with imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port, timeout=20) as imap:
        imap.login(settings.smtp_username, settings.smtp_password)
        imap.select(f'"{settings.imap_folder}"')
        imap.uid("store", b",".join(uids), "+FLAGS", r"(\Seen)")


# ---------- the poll ----------

def lead_payload(parsed: ParsedEmail) -> dict:
    # the subject often says what they want ("SEO quote for our clinic"), so the AI sees it too
    message = parsed.body
    if parsed.subject and parsed.subject.lower() not in parsed.body.lower() and parsed.body != parsed.subject:
        message = f"Subject: {parsed.subject}\n\n{parsed.body}"
    return {"channel": "email", "contact": parsed.sender, "name": parsed.name, "message": message[:4000],
            "subject": parsed.subject or None, "in_reply_to": parsed.message_id}


def poll_inbox(db, background, settings: Settings) -> PollResult:
    """Fetch unread mail, start a run per real enquiry, then mark everything handled as read."""
    from app.api.webhooks import start_lead  # shared with the WhatsApp webhooks

    result = PollResult()
    handled: list[bytes] = []
    for uid, raw in _imap_fetch(settings):
        result.fetched += 1
        try:
            parsed, reason = parse_email(raw, settings.smtp_username)
            if reason:
                result.skipped.append({"reason": reason})
            elif start_lead(db, background, provider="email", external_id=dedupe_key(parsed.message_id),
                            payload=lead_payload(parsed)):
                result.started += 1
            else:
                result.duplicates += 1
            handled.append(uid)
        except Exception:
            # leave it unread so the next poll tries again; one bad email mustn't block the rest
            log.exception("could not handle email uid %s", uid)
    _imap_mark_seen(settings, handled)
    return result
