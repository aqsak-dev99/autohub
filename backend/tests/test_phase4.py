"""Phase 4 tests: WhatsApp webhook, live sending and the daily digest. No network:
Twilio's API is replaced with a fake, and the LLM with the scripted fake."""
import uuid
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

import app.channels as channels
import app.engine.executor as executor
from app.automations.daily_digest import collect_stats, format_digest
from app.channels import DeliveryError, send_reply, twilio_signature
from app.config import Settings, get_settings
from app.db import SessionLocal
from app.main import app
from app.models import InboundMessage, Lead, Run
from tests.fakes import make_llm
from tests.test_phase2 import QUALIFY_HOT, classify, draft, judge

TOKEN = "test-auth-token"
WEBHOOK = "/api/webhooks/twilio/whatsapp"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def twilio(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "twilio_auth_token", TOKEN)
    monkeypatch.setattr(settings, "twilio_validate_signature", True)
    monkeypatch.setattr(settings, "public_base_url", "")
    return settings


def whatsapp_form(sid=None, body="Assalam o alaikum, ads ka kitna charge hai?", sender="whatsapp:+923001234567"):
    return {"MessageSid": sid or f"SM{uuid.uuid4().hex}", "From": sender, "Body": body,
            "ProfileName": "Usman", "NumMedia": "0"}


def signed_post(client, form, url=f"http://testserver{WEBHOOK}", headers=None):
    sig = twilio_signature(TOKEN, url, form)
    return client.post(WEBHOOK, data=form, headers={"X-Twilio-Signature": sig, **(headers or {})})


def runs_for(sid):
    with SessionLocal() as db:
        return db.query(InboundMessage).filter_by(external_id=sid).all()


# ---------- webhook ----------

def test_signed_message_starts_a_lead_run(client, twilio, monkeypatch):
    monkeypatch.setattr(executor, "get_llm", lambda: make_llm([classify(language="roman_urdu"), QUALIFY_HOT,
                                                                  draft(), judge()]))
    form = whatsapp_form()
    resp = signed_post(client, form)
    assert resp.status_code == 200 and "<Response></Response>" in resp.text  # answered at once, empty TwiML
    [inbound] = runs_for(form["MessageSid"])
    with SessionLocal() as db:
        run = db.get(Run, inbound.run_id)
        lead = db.query(Lead).filter_by(run_id=run.id).one()
        assert run.status.value == "succeeded"
        assert (lead.channel, lead.contact, lead.name) == ("whatsapp", "+923001234567", "Usman")


def test_bad_or_missing_signature_is_rejected(client, twilio):
    form = whatsapp_form()
    assert client.post(WEBHOOK, data=form).status_code == 403
    assert client.post(WEBHOOK, data=form, headers={"X-Twilio-Signature": "forged"}).status_code == 403
    tampered = {**form, "Body": "changed after signing"}
    sig = twilio_signature(TOKEN, f"http://testserver{WEBHOOK}", form)
    assert client.post(WEBHOOK, data=tampered, headers={"X-Twilio-Signature": sig}).status_code == 403
    assert runs_for(form["MessageSid"]) == []


def test_signature_uses_the_public_url_behind_a_proxy(client, twilio, monkeypatch):
    monkeypatch.setattr(executor, "get_llm", lambda: make_llm([classify(), QUALIFY_HOT, draft(), judge()]))
    form = whatsapp_form()
    public = f"https://moonlit-cape-8000.app.github.dev{WEBHOOK}"
    resp = signed_post(client, form, url=public,
                       headers={"X-Forwarded-Host": "moonlit-cape-8000.app.github.dev", "X-Forwarded-Proto": "https"})
    assert resp.status_code == 200 and len(runs_for(form["MessageSid"])) == 1


def test_duplicate_delivery_creates_one_run(client, twilio, monkeypatch):
    monkeypatch.setattr(executor, "get_llm", lambda: make_llm([classify(), QUALIFY_HOT, draft(), judge()]))
    form = whatsapp_form()
    assert signed_post(client, form).status_code == 200
    assert signed_post(client, form).status_code == 200  # Twilio retried
    assert len(runs_for(form["MessageSid"])) == 1


def test_media_only_message_is_acknowledged_but_not_processed(client, twilio):
    form = {**whatsapp_form(body=""), "NumMedia": "1"}
    assert signed_post(client, form).status_code == 200
    assert runs_for(form["MessageSid"]) == []


def test_webhook_refuses_to_run_unverified_without_a_token(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "twilio_auth_token", "")
    monkeypatch.setattr(get_settings(), "twilio_validate_signature", True)
    assert client.post(WEBHOOK, data=whatsapp_form()).status_code == 503


# ---------- sending ----------

def live_settings(**overrides):
    base = dict(whatsapp_provider="twilio", twilio_account_sid="AC123", twilio_auth_token=TOKEN, send_mode="live",
                groq_api_key="test",
                database_url="sqlite:///./test.db")
    return Settings(**{**base, **overrides})


def fake_twilio(monkeypatch, status=201, payload=None):
    sent = []

    def post(settings, data):
        sent.append(data)
        return httpx.Response(status, json=payload or {"sid": "SM999", "status": "queued"})

    monkeypatch.setattr(channels, "_post_to_twilio", post)
    return sent


def test_dry_run_unless_everything_says_live(monkeypatch):
    sent = fake_twilio(monkeypatch)
    assert send_reply("web_form", "a@b.com", "hi", live_settings())["mode"] == "dry_run"  # not WhatsApp
    assert send_reply("whatsapp", "+923001234567", "hi", live_settings(send_mode="dry_run"))["mode"] == "dry_run"
    assert send_reply("whatsapp", "+923001234567", "hi", live_settings(twilio_account_sid=""))["mode"] == "dry_run"
    assert sent == []


def test_allowlist_blocks_strangers(monkeypatch):
    sent = fake_twilio(monkeypatch)
    s = live_settings(live_send_allowlist="+92 300 1234567")
    stranger = send_reply("whatsapp", "+923009999999", "hi", s)
    assert stranger["mode"] == "dry_run" and "not on LIVE_SEND_ALLOWLIST" in stranger["note"]
    me = send_reply("whatsapp", "whatsapp:+923001234567", "hi", s)
    assert me == {**me, "mode": "twilio", "delivered": True, "message_sid": "SM999"}
    assert sent == [{"From": "whatsapp:+14155238886", "To": "whatsapp:+923001234567", "Body": "hi"}]


def test_twilio_error_raises_and_long_text_is_trimmed(monkeypatch):
    sent = fake_twilio(monkeypatch, status=400, payload={"code": 63016, "message": "Outside the allowed window"})
    with pytest.raises(DeliveryError) as err:
        send_reply("whatsapp", "+923001234567", "x" * 2000, live_settings())
    assert err.value.code == 63016 and len(sent[0]["Body"]) == 1600


def test_lead_reply_really_sent_when_live(client, monkeypatch):
    sent = fake_twilio(monkeypatch)
    llm = make_llm([classify(), QUALIFY_HOT, draft(), judge()])
    llm.settings = live_settings()
    payload = {"channel": "whatsapp", "contact": "+923001234567", "message": "Need Instagram ads, 3 lakh budget"}
    with SessionLocal() as db:
        run_id = executor.create_run(db, "lead_handler", payload).id
    assert executor.execute_run(run_id, llm=llm) == "succeeded"
    with SessionLocal() as db:
        send = next(s for s in db.get(Run, run_id).steps if s.node_id == "send")
        assert send.output["mode"] == "twilio" and send.output["message_sid"] == "SM999"
    assert len(sent) == 1


def test_failed_delivery_fails_the_run_so_it_can_be_retried(client, monkeypatch):
    fake_twilio(monkeypatch, status=401, payload={"code": 20003, "message": "Authenticate"})
    llm = make_llm([classify(), QUALIFY_HOT, draft(), judge()])
    llm.settings = live_settings()
    payload = {"channel": "whatsapp", "contact": "+923001234567", "message": "Need Instagram ads"}
    with SessionLocal() as db:
        run_id = executor.create_run(db, "lead_handler", payload).id
    assert executor.execute_run(run_id, llm=llm) == "failed"
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert "20003" in run.error and db.query(Lead).filter_by(run_id=run_id).one().status == "failed"


# ---------- daily digest ----------

def add_leads(*specs):
    with SessionLocal() as db:
        for name, temperature, status in specs:
            db.add(Lead(channel="whatsapp", contact="+920000000000", name=name, message="hi",
                        temperature=temperature, status=status, score=100 if temperature == "hot" else 50, services=["social-media"], budget_band="150k_400k"))
        db.commit()


def test_stats_count_the_window(client):
    with SessionLocal() as db:
        before = collect_stats(db, 24)
    add_leads(("Hot One", "hot", "replied"), ("Warm One", "warm", "awaiting_approval"), ("Spammer", None, "spam"))
    with SessionLocal() as db:
        after = collect_stats(db, 24)
    assert after["leads"] == before["leads"] + 3
    assert after["by_status"].get("spam", 0) == before["by_status"].get("spam", 0) + 1
    assert any(h["name"] == "Hot One" for h in after["hot_leads"])


def test_digest_text_is_built_from_numbers():
    stats = {"hours": 24, "leads": 5, "by_temperature": {"hot": 2, "warm": 2, "cold": 1}, "by_language": {},
             "by_status": {"spam": 1}, "replied": 3, "auto_sent": 2, "pending_approvals": 1,
             "oldest_pending_hours": 3.5, "runs": 6, "failed_runs": 0, "cost_usd": 0.0031,
             "hot_leads": [{"name": "Ayesha", "services": ["social", "paid"], "budget": "Rs 150k–400k",
                            "status": "replied"}]}
    text = format_digest(stats, "Reply to the waiting review first.", datetime(2026, 10, 30, 4, 0, tzinfo=timezone.utc))
    assert text.splitlines()[0] == "flowpath digest · Fri 30 Oct"
    assert "Leads: 5 (hot 2, warm 2, cold 1) · spam 1" in text
    assert "Replied: 3 (2 auto-sent)" in text and "Waiting for review: 1 (oldest 3.5 h)" in text
    assert "🔥 Ayesha · social + paid, Rs 150k–400k · replied" in text
    assert text.endswith("→ Reply to the waiting review first.")


def run_digest(llm):
    with SessionLocal() as db:
        run_id = executor.create_run(db, "daily_digest", {"hours": 24, "source": "n8n"}).id
    status = executor.execute_run(run_id, llm=llm)
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        return status, run.output, {s.node_id: s for s in run.steps}


def test_digest_run_end_to_end(client, monkeypatch):
    add_leads(("Digest Hot", "hot", "replied"))
    sent = fake_twilio(monkeypatch)
    llm = make_llm([{"line": "Call the hot lead before noon."}])
    llm.settings = live_settings(digest_whatsapp_to="+923001234567")
    status, output, steps = run_digest(llm)
    assert status == "succeeded" and list(steps) == ["schedule", "collect", "summarize", "deliver"]
    assert output["delivered"] and "→ Call the hot lead before noon." in output["text"]
    assert sent[0]["To"] == "whatsapp:+923001234567"


def test_digest_survives_llm_and_delivery_failures(client, monkeypatch):
    from tests.fakes import FakeStatusError

    add_leads(("Another", "warm", "replied"))
    fake_twilio(monkeypatch, status=400, payload={"code": 63016, "message": "Outside the allowed window"})
    llm = make_llm([FakeStatusError(400)])
    llm.settings = live_settings(digest_whatsapp_to="+923001234567")
    status, output, steps = run_digest(llm)
    assert status == "succeeded"  # the numbers still go out, just without the advice line
    assert steps["summarize"].output["fallback"] is True and "→" not in output["text"]
    [delivery] = steps["deliver"].output["deliveries"]
    assert delivery["code"] == 63016 and output["delivered"] is False


def test_digest_preview_endpoint(client):
    body = client.get("/api/digest/preview").json()
    assert body["text"].startswith("flowpath digest ·") and "leads" in body["stats"]


# ---------- Meta WhatsApp Cloud API ----------

from app.channels import meta_signature  # noqa: E402

META_WEBHOOK = "/api/webhooks/meta/whatsapp"
APP_SECRET = "test-app-secret"


@pytest.fixture
def meta(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "meta_app_secret", APP_SECRET)
    monkeypatch.setattr(settings, "meta_verify_token", "my-verify-token")
    monkeypatch.setattr(settings, "meta_validate_signature", True)
    return settings


def meta_payload(wamid=None, body="Salam, Instagram ads ka kitna charge hai?", sender="923001234567", kind="text"):
    message = {"from": sender, "id": wamid or f"wamid.{uuid.uuid4().hex}{uuid.uuid4().hex}", "timestamp": "1761800000",
               "type": kind}
    if kind == "text":
        message["text"] = {"body": body}
    return {"object": "whatsapp_business_account", "entry": [{"id": "WABA1", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"display_phone_number": "15550000000", "phone_number_id": "PN1"},
        "contacts": [{"profile": {"name": "Aqsa"}, "wa_id": sender}], "messages": [message]}}]}]}


def meta_post(client, payload, secret=APP_SECRET):
    import json as _json

    raw = _json.dumps(payload).encode()
    return client.post(META_WEBHOOK, content=raw, headers={"Content-Type": "application/json",
                                                           "X-Hub-Signature-256": meta_signature(secret, raw)})


def test_meta_verification_handshake(client, meta):
    ok = client.get(META_WEBHOOK, params={"hub.mode": "subscribe", "hub.verify_token": "my-verify-token",
                                          "hub.challenge": "12345"})
    assert ok.status_code == 200 and ok.text == "12345"  # Meta needs the challenge echoed back, as plain text
    bad = client.get(META_WEBHOOK, params={"hub.mode": "subscribe", "hub.verify_token": "guess", "hub.challenge": "1"})
    assert bad.status_code == 403


def test_meta_signed_message_starts_a_lead_run(client, meta, monkeypatch):
    monkeypatch.setattr(executor, "get_llm", lambda: make_llm([classify(language="roman_urdu"), QUALIFY_HOT,
                                                                  draft(), judge()]))
    payload = meta_payload()
    wamid = payload["entry"][0]["changes"][0]["value"]["messages"][0]["id"]
    resp = meta_post(client, payload)
    assert resp.status_code == 200 and resp.json()["runs_started"] == 1
    [inbound] = runs_for(wamid)
    assert len(wamid) > 64  # real wamids are long; the column holds them
    with SessionLocal() as db:
        lead = db.query(Lead).filter_by(run_id=inbound.run_id).one()
        assert (lead.channel, lead.contact, lead.name, lead.status) == ("whatsapp", "+923001234567", "Aqsa", "replied")


def test_meta_bad_signature_and_missing_secret(client, meta, monkeypatch):
    assert meta_post(client, meta_payload(), secret="wrong").status_code == 403
    assert client.post(META_WEBHOOK, json=meta_payload()).status_code == 403  # no signature header
    monkeypatch.setattr(get_settings(), "meta_app_secret", "")
    assert meta_post(client, meta_payload()).status_code == 503


def test_meta_duplicates_statuses_and_media_start_nothing(client, meta, monkeypatch):
    monkeypatch.setattr(executor, "get_llm", lambda: make_llm([classify(), QUALIFY_HOT, draft(), judge()]))
    payload = meta_payload()
    assert meta_post(client, payload).json()["runs_started"] == 1
    assert meta_post(client, payload).json()["runs_started"] == 0  # Meta redelivered
    assert meta_post(client, meta_payload(kind="image")).json()["runs_started"] == 0
    status_only = {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
        "statuses": [{"id": "wamid.x", "status": "delivered", "recipient_id": "923001234567"}]}}]}]}
    assert meta_post(client, status_only).json()["runs_started"] == 0


def meta_settings(**overrides):
    base = dict(whatsapp_provider="meta", meta_access_token="EAAtoken", meta_phone_number_id="PN1", send_mode="live",
                groq_api_key="test", database_url="sqlite:///./test.db")
    return Settings(**{**base, **overrides})


def fake_meta(monkeypatch, status=200, payload=None):
    sent = []

    def post(settings, body):
        sent.append(body)
        return httpx.Response(status, json=payload or {"messaging_product": "whatsapp",
                                                       "messages": [{"id": "wamid.SENT1"}]})

    monkeypatch.setattr(channels, "_post_to_meta", post)
    return sent


def test_meta_send_and_allowlist(monkeypatch):
    sent = fake_meta(monkeypatch)
    s = meta_settings(live_send_allowlist="+923001234567")
    assert send_reply("whatsapp", "+923009999999", "hi", s)["mode"] == "dry_run"
    result = send_reply("whatsapp", "+923001234567", "hi", s)
    assert result["mode"] == "meta" and result["message_id"] == "wamid.SENT1"
    assert sent == [{"messaging_product": "whatsapp", "recipient_type": "individual", "to": "923001234567",
                     "type": "text", "text": {"preview_url": False, "body": "hi"}}]
    assert send_reply("whatsapp", "+923001234567", "hi", meta_settings(meta_access_token=""))["mode"] == "dry_run"


def test_meta_error_raises_with_code(monkeypatch):
    fake_meta(monkeypatch, status=400, payload={"error": {"message": "Re-engagement message", "code": 131047}})
    with pytest.raises(DeliveryError) as err:
        send_reply("whatsapp", "+923001234567", "hi", meta_settings())
    assert err.value.code == 131047
