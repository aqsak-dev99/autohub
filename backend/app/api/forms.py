"""The public contact form on flowpath's website: the second live channel.

The visitor leaves a name, an email address and a message; the Lead Handler
answers by email within seconds, or holds the reply for approval. This endpoint
is public (a browser posts it), so it gets the protections a public form needs:

- allowed origins:  only flowpath's own site may post it (FORM_ALLOWED_ORIGINS)
- honeypot:         a hidden "website" field people never see; bots fill it in
- rate limit:       a few messages per hour per email address and per IP
- dedupe:           a double-click or a resubmitted page doesn't start two runs
"""
import hashlib
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.intake import start_lead
from app.models import InboundMessage

router = APIRouter(prefix="/api/forms", tags=["contact form"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_ip_hits: dict[str, deque] = defaultdict(deque)  # in memory: resets on restart, which is fine for a soft limit


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(max_length=200)
    message: str = Field(min_length=5, max_length=4000)
    company: str | None = Field(default=None, max_length=120)
    website: str | None = Field(default=None, description="honeypot: leave empty")

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not EMAIL_RE.match(value):
            raise ValueError("that doesn't look like an email address")
        return value


class ContactOut(BaseModel):
    ok: bool
    message: str


THANKS = "Thanks! We'll reply to your email shortly."


def _check_origin(request: Request) -> None:
    allowed = {o.strip().rstrip("/") for o in get_settings().form_allowed_origins.split(",") if o.strip()}
    origin = (request.headers.get("origin") or "").rstrip("/")
    if not allowed and get_settings().app_env == "production":
        # a public server must say which site may use its form, or anyone could
        raise HTTPException(403, "The contact form isn't switched on for this server (set FORM_ALLOWED_ORIGINS)")
    if allowed and origin not in allowed:
        raise HTTPException(403, "This form can only be sent from flowpath's website")


def _too_many_from_ip(ip: str, limit: int) -> bool:
    now, hits = time.monotonic(), _ip_hits[ip]
    while hits and now - hits[0] > 3600:
        hits.popleft()
    if len(hits) >= limit:
        return True
    hits.append(now)
    return False


@router.post("/contact", response_model=ContactOut, status_code=202)
def contact(body: ContactIn, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    settings = get_settings()
    _check_origin(request)
    if body.website:
        return ContactOut(ok=True, message=THANKS)  # a bot: look successful, do nothing

    limit = settings.form_rate_limit_per_hour
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0]
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    recent = db.scalar(select(func.count()).select_from(InboundMessage).where(
        InboundMessage.provider == "form", InboundMessage.external_id.like(f"form:{body.email}:%"),
        InboundMessage.created_at >= since))
    if recent >= limit or _too_many_from_ip(ip.strip(), limit * 3):
        raise HTTPException(429, "Too many messages. Please try again in an hour.")

    message = body.message.strip()
    if body.company:
        message = f"Company: {body.company.strip()}\n\n{message}"
    # same person + same text = the same submission (double-click, page resubmitted)
    fingerprint = hashlib.sha256(f"{body.email}\n{message}".encode()).hexdigest()[:24]
    start_lead(db, background, provider="form", external_id=f"form:{body.email}:{fingerprint}", payload={
        "channel": "web_form", "contact": body.email, "name": body.name.strip(), "message": message,
        "subject": f"Your enquiry to {settings.email_from_name}",
    })
    return ContactOut(ok=True, message=THANKS)
