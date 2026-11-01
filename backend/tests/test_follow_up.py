"""Follow-up Nudge: which leads are due, exactly-once scans, and the run's routes."""
import itertools
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import app.engine.executor as executor
import app.intake as intake
from app.db import SessionLocal
from app.main import app
from app.models import Approval, ApprovalStatus, Lead, Run, StepStatus
from tests.fakes import make_llm
from tests.test_phase2 import TRANSLATION, draft, judge

FOLLOW_UP = "Hi Sana, just checking in on your Instagram ads question. Would a 15-minute call this week help? Team flowpath"
_n = itertools.count()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(intake, "dispatch", lambda run_id, background: "test")  # runs are executed by hand below
    with TestClient(app) as c:
        yield c


def make_lead(days_ago=3, temperature="hot", channel="email", language="english", **extra) -> int:
    replied = datetime.now(timezone.utc) - timedelta(days=days_ago)
    with SessionLocal() as db:
        if db.bind.dialect.name == "sqlite":
            replied = replied.replace(tzinfo=None)  # SQLite keeps naive UTC times
        lead = Lead(channel=channel, contact=f"quiet{next(_n)}@example.com", name="Sana", language=language,
                    intent="new_business", message="How much do Instagram ads cost for a bakery?",
                    reply="Most clients spend Rs 150,000 to Rs 400,000 a month. Team flowpath", replied=True,
                    status="replied", temperature=temperature, score=80, replied_at=replied, **extra)
        db.add(lead)
        db.commit()
        return lead.id


def due_ids(client):
    return {d["lead_id"] for d in client.get("/api/follow-ups/due").json()}


def follow_up_run(lead_id, script):
    with SessionLocal() as db:
        run_id = executor.create_run(db, "follow_up", {"lead_id": lead_id}).id
    return run_id, executor.execute_run(run_id, llm=make_llm(script))


def steps(run_id):
    with SessionLocal() as db:
        return [(s.node_id, s.status) for s in db.get(Run, run_id).steps]


def test_which_leads_are_due(client):
    due = make_lead()
    too_soon = make_lead(days_ago=1)
    too_old = make_lead(days_ago=20)
    cold = make_lead(temperature="cold")
    chat = make_lead(channel="web_chat")  # nowhere to send a follow-up
    wrote_again = make_lead()
    with SessionLocal() as db:
        contact = db.get(Lead, wrote_again).contact
        db.add(Lead(channel="email", contact=contact, message="Any update?", status="new"))
        db.commit()
    ids = due_ids(client)
    assert due in ids
    assert not ids & {too_soon, too_old, cold, chat, wrote_again}


def test_a_scan_starts_each_follow_up_once(client):
    lead_id = make_lead()
    first = client.post("/api/follow-ups/scan").json()
    assert lead_id in first["lead_ids"]
    second = client.post("/api/follow-ups/scan").json()
    assert lead_id not in second["lead_ids"]  # claimed: overlapping scans can't nudge twice
    assert lead_id not in due_ids(client)


def test_confident_follow_up_is_sent_and_recorded(client):
    lead_id = make_lead()
    run_id, status = follow_up_run(lead_id, [draft(FOLLOW_UP), judge()])
    assert status == "succeeded"
    assert [n for n, _ in steps(run_id)] == ["pick", "retrieve", "draft", "score", "send", "save"]
    with SessionLocal() as db:
        lead = db.get(Lead, lead_id)
        assert lead.followed_up_at is not None and lead.follow_up_reply == FOLLOW_UP
        assert lead.status == "replied"  # still the same conversation


def test_urdu_follow_up_is_translated_and_held_then_approved(client, monkeypatch):
    lead_id = make_lead(language="urdu")
    run_id, status = follow_up_run(lead_id, [draft(FOLLOW_UP), judge(), TRANSLATION])
    assert status == "waiting_approval"
    assert steps(run_id)[-2:] == [("translate", StepStatus.succeeded), ("approval", StepStatus.waiting)]
    with SessionLocal() as db:
        approval = db.query(Approval).filter_by(run_id=run_id).one()
        assert approval.kind == "follow_up" and approval.payload["translation"] == TRANSLATION
        assert approval.payload["follow_up"]["days_quiet"] >= 2.9
    monkeypatch.setattr(executor, "get_llm", lambda: make_llm([]))
    resp = client.post(f"/api/approvals/{approval.id}/decision", json={"action": "approve"})
    assert resp.status_code == 200
    assert [n for n, _ in steps(run_id)][-3:] == ["approval", "send", "save"]
    with SessionLocal() as db:
        assert db.get(Lead, lead_id).follow_up_reply == FOLLOW_UP


def test_a_skipped_follow_up_sends_nothing_and_is_not_offered_again(client, monkeypatch):
    lead_id = make_lead()
    assert lead_id in client.post("/api/follow-ups/scan").json()["lead_ids"]
    with SessionLocal() as db:
        run_id = db.query(Run).filter(Run.input["lead_id"].as_integer() == lead_id).one().id
    executor.execute_run(run_id, llm=make_llm([draft(FOLLOW_UP), judge(unsupported=1)]))  # a promise: held
    with SessionLocal() as db:
        approval_id = db.query(Approval).filter_by(run_id=run_id).one().id
    monkeypatch.setattr(executor, "get_llm", lambda: make_llm([]))
    client.post(f"/api/approvals/{approval_id}/decision", json={"action": "reject"})
    assert "send" not in [n for n, _ in steps(run_id)]
    with SessionLocal() as db:
        assert db.get(Lead, lead_id).followed_up_at is None
    assert lead_id not in due_ids(client)


def test_run_stops_if_the_customer_wrote_back_after_the_scan(client):
    lead_id = make_lead()
    with SessionLocal() as db:
        db.add(Lead(channel="email", contact=db.get(Lead, lead_id).contact, message="Yes let's talk", status="new"))
        db.commit()
    run_id, status = follow_up_run(lead_id, [])  # no AI calls at all
    assert status == "succeeded"
    assert steps(run_id) == [("pick", StepStatus.skipped)]


def test_conversation_shows_the_follow_up(client):
    lead_id = make_lead()
    with SessionLocal() as db:
        lead = db.get(Lead, lead_id)
        first = executor.create_run(db, "lead_handler", {"channel": "email", "contact": lead.contact, "message": lead.message})
        lead.run_id = first.id
        db.commit()
        first_id = first.id
    assert client.get(f"/api/conversations/{first_id}").json()["follow_up"] is None
    client.post("/api/follow-ups/scan")
    with SessionLocal() as db:
        fu_id = db.query(Run).filter(Run.input["lead_id"].as_integer() == lead_id).one().id
    executor.execute_run(fu_id, llm=make_llm([draft(FOLLOW_UP), judge()]))
    fu = client.get(f"/api/conversations/{first_id}").json()["follow_up"]
    assert fu["status"] == "succeeded" and fu["reply"] == FOLLOW_UP and fu["approval"] is None
