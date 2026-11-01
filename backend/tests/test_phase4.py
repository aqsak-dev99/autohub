"""Phase 4 tests: the public contact form, live sending by email, and the daily digest.
No network: the mail server is replaced with a fake, and the LLM with the scripted fake."""
import smtplib
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import app.api.forms as forms
import app.engine.executor as executor
from app.automations.daily_digest import collect_stats, format_digest
from app.channels import send_reply
from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import InboundMessage, Lead, Run
from tests.fakes import make_llm
from tests.test_email import email_settings, fake_smtp
from tests.test_phase2 import QUALIFY_HOT, classify, draft, judge

FORM = "/api/forms/contact"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def no_dispatch(monkeypatch):
    """Record which runs the form would start, without executing them."""
    started = []
    monkeypatch.setattr("app.intake.dispatch", lambda run_id, background: started.append(run_id) or "test")
    forms._ip_hits.clear()
    return started


def form(**overrides):
    return {"name": "Zainab", "email": "zainab@bakery.pk",
            "message": "Hi, we run a bakery in Gulberg. How much for Instagram posts every month?", **overrides}


# ---------- website contact form ----------

def test_form_starts_a_web_form_lead(client, no_dispatch):
    resp = client.post(FORM, json=form(company="Zainab's Bakes"))
    assert resp.status_code == 202 and resp.json()["ok"] is True
    assert len(no_dispatch) == 1
    with SessionLocal() as db:
        run = db.get(Run, no_dispatch[0])
        assert run.input["channel"] == "web_form" and run.input["contact"] == "zainab@bakery.pk"
        assert run.input["message"].startswith("Company: Zainab's Bakes")
        assert run.input["subject"] == "Your enquiry to flowpath"


def test_form_double_submit_starts_one_run(client, no_dispatch):
    body = form(email="double@click.pk")
    assert client.post(FORM, json=body).status_code == 202
    assert client.post(FORM, json=body).status_code == 202  # same answer, so the visitor sees no error
    assert len(no_dispatch) == 1


def test_form_honeypot_looks_successful_but_does_nothing(client, no_dispatch):
    resp = client.post(FORM, json=form(email="bot@spam.io", website="http://cheap-pills.example"))
    assert resp.status_code == 202 and resp.json()["ok"] is True
    assert no_dispatch == []


def test_form_validates_email_and_message(client, no_dispatch):
    assert client.post(FORM, json=form(email="not-an-email")).status_code == 422
    assert client.post(FORM, json=form(message="hi")).status_code == 422
    assert no_dispatch == []


def test_form_rate_limit_per_email(client, no_dispatch, monkeypatch):
    monkeypatch.setattr(get_settings(), "form_rate_limit_per_hour", 2)
    for i in range(2):
        assert client.post(FORM, json=form(email="busy@x.pk", message=f"Question number {i} about ads")).status_code == 202
    assert client.post(FORM, json=form(email="busy@x.pk", message="Question number 3 about ads")).status_code == 429
    assert len(no_dispatch) == 2


def test_form_only_accepts_flowpaths_site_when_origins_are_set(client, no_dispatch, monkeypatch):
    monkeypatch.setattr(get_settings(), "form_allowed_origins", "https://flowpath.studio")
    assert client.post(FORM, json=form(email="o1@x.pk"), headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post(FORM, json=form(email="o2@x.pk"), headers={"Origin": "https://flowpath.studio"}).status_code == 202


def test_web_chat_replies_stay_on_screen():
    result = send_reply("web_chat", "chat-visitor-1", "hello", email_settings())
    assert result["mode"] == "dry_run" and "shown where the customer asked" in result["note"]


# ---------- live sending ----------

def test_form_lead_reply_is_emailed_when_live(client, monkeypatch):
    sent = fake_smtp(monkeypatch)
    llm = make_llm([classify(), QUALIFY_HOT, draft(), judge()])
    llm.settings = email_settings()
    payload = {"channel": "web_form", "contact": "zainab@bakery.pk", "name": "Zainab",
               "message": "Need Instagram ads, 3 lakh budget", "subject": "Your enquiry to flowpath"}
    with SessionLocal() as db:
        run_id = executor.create_run(db, "lead_handler", payload).id
    assert executor.execute_run(run_id, llm=llm) == "succeeded"
    with SessionLocal() as db:
        send = next(s for s in db.get(Run, run_id).steps if s.node_id == "send")
        assert send.output["mode"] == "smtp" and send.output["delivered"] is True
    assert sent[0]["To"] == "zainab@bakery.pk"


def test_failed_delivery_fails_the_run_so_it_can_be_retried(client, monkeypatch):
    fake_smtp(monkeypatch, error=smtplib.SMTPAuthenticationError(535, b"bad credentials"))
    llm = make_llm([classify(), QUALIFY_HOT, draft(), judge()])
    llm.settings = email_settings()
    payload = {"channel": "email", "contact": "client@shop.pk", "message": "Need Instagram ads"}
    with SessionLocal() as db:
        run_id = executor.create_run(db, "lead_handler", payload).id
    assert executor.execute_run(run_id, llm=llm) == "failed"
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert "app password" in run.error and db.query(Lead).filter_by(run_id=run_id).one().status == "failed"


# ---------- daily digest ----------

def add_leads(*specs):
    with SessionLocal() as db:
        for name, temperature, status in specs:
            db.add(Lead(channel="email", contact="someone@example.com", name=name, message="hi",
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
    sent = fake_smtp(monkeypatch)
    llm = make_llm([{"line": "Call the hot lead before noon."}])
    llm.settings = email_settings(digest_email_to="aqsa@example.com")
    status, output, steps = run_digest(llm)
    assert status == "succeeded" and list(steps) == ["schedule", "collect", "summarize", "deliver"]
    assert output["delivered"] and "→ Call the hot lead before noon." in output["text"]
    assert sent[0]["To"] == "aqsa@example.com" and sent[0]["Subject"].startswith("flowpath digest")


def test_digest_survives_llm_and_delivery_failures(client, monkeypatch):
    from tests.fakes import FakeStatusError

    add_leads(("Another", "warm", "replied"))
    fake_smtp(monkeypatch, error=smtplib.SMTPRecipientsRefused({"aqsa@example.com": (550, b"no such user")}))
    llm = make_llm([FakeStatusError(400)])
    llm.settings = email_settings(digest_email_to="aqsa@example.com")
    status, output, steps = run_digest(llm)
    assert status == "succeeded"  # the numbers still go out, just without the advice line
    assert steps["summarize"].output["fallback"] is True and "→" not in output["text"]
    [delivery] = steps["deliver"].output["deliveries"]
    assert delivery["code"] == 550 and output["delivered"] is False


def test_digest_preview_endpoint(client):
    body = client.get("/api/digest/preview").json()
    assert body["text"].startswith("flowpath digest ·") and "leads" in body["stats"]
