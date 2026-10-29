"""WhatsApp webhooks (Meta Cloud API and Twilio): a customer's message becomes a Lead Handler run.

Both providers expect a fast answer and the Lead Handler takes seconds, so
these endpoints only verify, record and queue the message, then answer at
once. The reply goes out later from the worker through the provider's API.
"""
import hmac
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.channels import valid_meta_signature, valid_twilio_signature
from app.config import get_settings, normalize_phone
from app.db import get_db
from app.engine.dispatch import dispatch
from app.engine.executor import create_run
from app.models import InboundMessage

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])
log = logging.getLogger("autohub.webhooks")

EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


def public_url(request: Request) -> str:
    """The URL Twilio called, which is what it signed.

    Behind a proxy (Codespaces, Render) the app sees an internal address,
    so use PUBLIC_BASE_URL if set, else the proxy's forwarded headers.
    """
    path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    base = get_settings().public_base_url.rstrip("/")
    if base:
        return base + path
    host = request.headers.get("x-forwarded-host")
    if host:
        proto = request.headers.get("x-forwarded-proto", "https").split(",")[0].strip()
        return f"{proto}://{host.split(',')[0].strip()}{path}"
    return str(request.url)


def twiml() -> Response:
    return Response(EMPTY_TWIML, media_type="application/xml")


@router.post("/twilio/whatsapp")
async def twilio_whatsapp(request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    settings = get_settings()
    params = {key: str(value) for key, value in (await request.form()).items()}

    if settings.twilio_validate_signature:
        if not settings.twilio_auth_token:
            raise HTTPException(503, "TWILIO_AUTH_TOKEN is not set, so the signature can't be checked")
        if not valid_twilio_signature(settings.twilio_auth_token, public_url(request), params,
                                      request.headers.get("x-twilio-signature")):
            # anyone can find a public URL; only Twilio knows the auth token
            log.warning("rejected WhatsApp webhook with a bad signature (url=%s)", public_url(request))
            raise HTTPException(403, "Invalid Twilio signature")

    sid = params.get("MessageSid") or params.get("SmsMessageSid")
    body = params.get("Body", "").strip()
    sender = normalize_phone(params.get("From", ""))
    if not sid or not sender:
        raise HTTPException(400, "Missing MessageSid or From")
    if not body:
        # photos, voice notes and stickers have no text to qualify; recorded in the log only
        log.info("ignored WhatsApp message %s with no text (media: %s)", sid, params.get("NumMedia", "0"))
        return twiml()

    start_lead(db, background, provider="twilio", external_id=sid,
               payload=whatsapp_payload(sender, params.get("ProfileName") or None, body))
    return twiml()


def whatsapp_payload(sender: str, name: str | None, body: str) -> dict:
    return {"channel": "whatsapp", "contact": sender, "name": name, "message": body[:4000]}


def start_lead(db: Session, background: BackgroundTasks, *, provider: str, external_id: str, payload: dict) -> bool:
    """Record a message once and queue a Lead Handler run for it. False if it was a duplicate.

    Shared by every channel: the Meta and Twilio webhooks and the email inbox poll."""
    # claim the message id first: the unique constraint makes a second delivery fail here,
    # before any run exists, even if two deliveries arrive at the same moment
    inbound = InboundMessage(provider=provider, external_id=external_id)
    db.add(inbound)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        log.info("duplicate delivery of %s ignored", external_id)
        return False

    run = create_run(db, "lead_handler", payload)
    inbound.run_id = run.id
    db.commit()
    dispatch(run.id, background)
    return True


# ---------- Meta WhatsApp Cloud API ----------

@router.get("/meta/whatsapp", response_class=PlainTextResponse)
def meta_verify(request: Request):
    """Meta calls this once when you save the webhook URL: echo the challenge if the token matches."""
    q = request.query_params
    expected = get_settings().meta_verify_token
    if (q.get("hub.mode") == "subscribe" and expected and q.get("hub.verify_token")
            and secrets_equal(q["hub.verify_token"], expected)):
        return q.get("hub.challenge", "")
    raise HTTPException(403, "Verify token doesn't match META_VERIFY_TOKEN")


@router.post("/meta/whatsapp")
async def meta_whatsapp(request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    settings = get_settings()
    raw = await request.body()  # the signature covers these exact bytes, so check before parsing

    if settings.meta_validate_signature:
        if not settings.meta_app_secret:
            raise HTTPException(503, "META_APP_SECRET is not set, so the signature can't be checked")
        if not valid_meta_signature(settings.meta_app_secret, raw, request.headers.get("x-hub-signature-256")):
            log.warning("rejected Meta webhook with a bad signature")
            raise HTTPException(403, "Invalid signature")

    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "Body is not JSON")

    started = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value") or {}
            # delivery receipts ("statuses") also arrive here; only customer messages start runs
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts", [])}
            for message in value.get("messages", []):
                if message.get("type") != "text":
                    log.info("ignored Meta %s message %s (no text)", message.get("type"), message.get("id"))
                    continue
                body = ((message.get("text") or {}).get("body") or "").strip()
                if not body or not message.get("id") or not message.get("from"):
                    continue
                if start_lead(db, background, provider="meta", external_id=message["id"],
                              payload=whatsapp_payload(normalize_phone(message["from"]), names.get(message["from"]),
                                                       body)):
                    started += 1
    # always 200 once verified: anything else makes Meta retry the same delivery
    return {"ok": True, "runs_started": started}


def secrets_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
