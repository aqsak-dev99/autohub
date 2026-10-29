"""Email channel tests: parsing, loop guards, the inbox poll, threaded replies and the digest by email.
No network: IMAP and SMTP are replaced with fakes."""
from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient

import app.channels as channels
import app.email_inbox as inbox
import app.engine.executor as executor
from app.channels import DeliveryError, send_reply
from app.config import Settings, get_settings
from app.db import SessionLocal
from app.email_inbox import parse_email, search_criteria, strip_quoted
from app.main import app
from app.models import InboundMessage, Lead, Run
from tests.fakes import make_llm
from tests.test_phase2 import QUALIFY_HOT, classify, draft, judge

OWN = "flowpath.leads@gmail.com"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def raw_email(sender="Bilal Ahmed <bilal@clinic.pk>", subject="SEO for our dental clinic", body="Hi, we need SEO.",
              message_id=None, headers=None, html=None):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, OWN, subject
    msg["Message-ID"] = message_id or f"<{abs(hash((sender, subject, body)))}.{id(msg)}@mail.clinic.pk>"
    for k, v in (headers or {}).items():
        msg[k] = v
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg.as_bytes()


# ---------- parsing ----------

def test_parses_sender_subject_and_new_text_only():
    body = "We need Instagram ads, budget 3 lakh.\n\nOn Mon, 27 Oct 2026, flowpath <x@y.com> wrote:\n> Thanks!\n> More"
    parsed, reason = parse_email(raw_email(body=body), OWN)
    assert reason is None
    assert (parsed.sender, parsed.name, parsed.subject) == ("bilal@clinic.pk", "Bilal Ahmed", "SEO for our dental clinic")
    assert parsed.body == "We need Instagram ads, budget 3 lakh."


def test_html_only_and_urdu_are_read():
    msg = EmailMessage()
    msg["From"], msg["Subject"], msg["Message-ID"] = "Sana <sana@x.pk>", "مارکیٹنگ", "<u1@x.pk>"
    msg.set_content("<p>السلام علیکم،<br>انسٹاگرام مارکیٹنگ چاہیے</p>", subtype="html")
    parsed, _ = parse_email(msg.as_bytes(), OWN)
    assert parsed.subject == "مارکیٹنگ" and "انسٹاگرام مارکیٹنگ چاہیے" in parsed.body and "<p>" not in parsed.body


@pytest.mark.parametrize("sender,headers,reason", [
    ("Mail Delivery <mailer-daemon@googlemail.com>", {}, "no-reply sender"),
    ("Shop <no-reply@shop.com>", {}, "no-reply sender"),
    (f"flowpath <{OWN}>", {}, "sent by AutoHub itself"),
    ("Bob <bob@x.com>", {"Auto-Submitted": "auto-replied"}, "automated message (Auto-Submitted: auto-replied)"),
    ("Bob <bob@x.com>", {"Precedence": "bulk"}, "bulk or auto-reply (Precedence header)"),
    ("News <news@brand.com>", {"List-Unsubscribe": "<mailto:u@brand.com>"}, "newsletter or mailing list"),
])
def test_automated_mail_is_never_answered(sender, headers, reason):
    assert parse_email(raw_email(sender=sender, headers=headers), OWN) == (None, reason)


def test_auto_submitted_no_is_a_real_person():
    parsed, reason = parse_email(raw_email(headers={"Auto-Submitted": "no"}), OWN)
    assert reason is None and parsed is not None


def test_strip_quoted_variants():
    assert strip_quoted("Yes please.\n\n-----Original Message-----\nFrom: x") == "Yes please."
    assert strip_quoted("Sounds good\n\nSent from my iPhone") == "Sounds good"


def test_only_recent_unread_mail_is_searched():
    from datetime import datetime, timezone

    s = Settings(email_poll_since_days=1)
    assert search_criteria(s, datetime(2026, 10, 30, tzinfo=timezone.utc)) == "(UNSEEN SINCE 29-Oct-2026)"


# ---------- the poll ----------

@pytest.fixture
def mailbox(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_username", OWN)
    monkeypatch.setattr(settings, "smtp_password", "app-password")
    state = {"inbox": [], "seen": []}
    monkeypatch.setattr(inbox, "_imap_fetch", lambda s: [(str(i).encode(), raw) for i, raw in enumerate(state["inbox"])])
    monkeypatch.setattr(inbox, "_imap_mark_seen", lambda s, uids: state["seen"].extend(uids))
    return state


def test_poll_starts_runs_skips_bots_and_ignores_repeats(client, mailbox, monkeypatch):
    monkeypatch.setattr(executor, "get_llm", lambda: make_llm([classify(), QUALIFY_HOT, draft(), judge()]))
    real = raw_email(message_id="<real-1@clinic.pk>")
    mailbox["inbox"] = [real, raw_email(sender="Shop <no-reply@shop.com>")]
    body = client.post("/api/email/poll").json()
    assert (body["fetched"], body["started"], body["duplicates"]) == (2, 1, 0)
    assert body["skipped"] == [{"reason": "no-reply sender"}]
    assert mailbox["seen"] == [b"0", b"1"]  # both marked read, so neither is fetched again

    mailbox["inbox"] = [real]  # an overlapping poll sees the same email
    assert client.post("/api/email/poll").json()["duplicates"] == 1

    with SessionLocal() as db:
        run_id = db.query(InboundMessage).filter_by(provider="email").order_by(InboundMessage.id.desc()).first().run_id
        run = db.get(Run, run_id)
        lead = db.query(Lead).filter_by(run_id=run_id).one()
        assert run.input["in_reply_to"] == "<real-1@clinic.pk>" and run.input["subject"] == "SEO for our dental clinic"
        assert run.input["message"].startswith("Subject: SEO for our dental clinic")
        assert (lead.channel, lead.contact, lead.name) == ("email", "bilal@clinic.pk", "Bilal Ahmed")


def test_one_bad_email_stays_unread_and_doesnt_block_others(client, mailbox, monkeypatch):
    monkeypatch.setattr(executor, "get_llm", lambda: make_llm([classify(), QUALIFY_HOT, draft(), judge()]))
    original = inbox.parse_email

    def flaky(raw, own):
        if b"BROKEN" in raw:
            raise ValueError("cannot parse")
        return original(raw, own)

    monkeypatch.setattr(inbox, "parse_email", flaky)
    mailbox["inbox"] = [raw_email(body="BROKEN"), raw_email(message_id="<ok-2@clinic.pk>")]
    assert client.post("/api/email/poll").json()["started"] == 1
    assert mailbox["seen"] == [b"1"]  # the broken one is retried next time


def test_poll_needs_credentials(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "smtp_password", "")
    assert client.post("/api/email/poll").status_code == 400


# ---------- sending ----------

def email_settings(**overrides):
    base = dict(smtp_username=OWN, smtp_password="app-password", send_mode="live", groq_api_key="test",
                database_url="sqlite:///./test.db")
    return Settings(**{**base, **overrides})


def fake_smtp(monkeypatch, error=None):
    sent = []

    def send(settings, message):
        if error:
            raise error
        sent.append(message)

    monkeypatch.setattr(channels, "_smtp_send", send)
    return sent


def test_reply_is_threaded_and_from_flowpath(monkeypatch):
    sent = fake_smtp(monkeypatch)
    result = send_reply("email", "bilal@clinic.pk", "Thanks, Bilal!", email_settings(),
                        subject="Re: SEO for our dental clinic", in_reply_to="<real-1@clinic.pk>")
    assert result["mode"] == "smtp" and result["delivered"]
    [msg] = sent
    assert msg["From"] == f"flowpath <{OWN}>" and msg["To"] == "bilal@clinic.pk"
    assert msg["Subject"] == "Re: SEO for our dental clinic"
    assert msg["In-Reply-To"] == msg["References"] == "<real-1@clinic.pk>"
    assert msg.get_content().strip() == "Thanks, Bilal!"


def test_email_dry_runs_and_allowlist(monkeypatch):
    sent = fake_smtp(monkeypatch)
    assert send_reply("email", "a@b.com", "hi", email_settings(send_mode="dry_run"))["mode"] == "dry_run"
    assert send_reply("email", "a@b.com", "hi", email_settings(smtp_password=""))["mode"] == "dry_run"
    limited = email_settings(email_send_allowlist="Me@Example.com")
    assert send_reply("email", "stranger@x.com", "hi", limited)["mode"] == "dry_run"
    assert send_reply("email", "me@example.com", "hi", limited)["mode"] == "smtp"
    assert len(sent) == 1


def test_web_form_leads_get_an_email_reply(monkeypatch):
    sent = fake_smtp(monkeypatch)
    result = send_reply("web_form", "ayesha@example.com", "Hi Ayesha", email_settings())
    assert result["mode"] == "smtp" and sent[0]["Subject"] == "Your enquiry to flowpath"


def test_gmail_login_failure_is_explained(monkeypatch):
    import smtplib

    fake_smtp(monkeypatch, error=smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted"))
    with pytest.raises(DeliveryError) as err:
        send_reply("email", "a@b.com", "hi", email_settings())
    assert err.value.code == 535 and "app password" in str(err.value)


def test_email_lead_end_to_end_replies_in_thread(client, monkeypatch):
    sent = fake_smtp(monkeypatch)
    llm = make_llm([classify(), QUALIFY_HOT, draft(), judge()])
    llm.settings = email_settings()
    payload = {"channel": "email", "contact": "bilal@clinic.pk", "name": "Bilal", "message": "We need SEO",
               "subject": "SEO quote", "in_reply_to": "<q-1@clinic.pk>"}
    with SessionLocal() as db:
        run_id = executor.create_run(db, "lead_handler", payload).id
    assert executor.execute_run(run_id, llm=llm) == "succeeded"
    assert sent[0]["Subject"] == "Re: SEO quote" and sent[0]["In-Reply-To"] == "<q-1@clinic.pk>"


def test_digest_goes_to_email(client, monkeypatch):
    sent = fake_smtp(monkeypatch)
    llm = make_llm([{"line": "Reply to the waiting lead first."}])
    llm.settings = email_settings(digest_email_to="aqsa@example.com")
    with SessionLocal() as db:
        db.add(Lead(channel="email", contact="z@z.com", message="hi", status="replied", temperature="warm"))
        db.commit()
        run_id = executor.create_run(db, "daily_digest", {"hours": 24}).id
    assert executor.execute_run(run_id, llm=llm) == "succeeded"
    assert sent[0]["To"] == "aqsa@example.com" and sent[0]["Subject"].startswith("flowpath digest ·")
