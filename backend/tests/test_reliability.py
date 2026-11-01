"""The engine's guarantees under bad timing: double clicks, duplicate jobs, retries, restarts."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import app.engine.executor as executor
from app.db import SessionLocal
from app.engine.executor import INTERRUPTED, RetryRefused, claim, recover_interrupted, reset_for_retry
from app.main import app
from app.models import Approval, ApprovalStatus, Lead, Run, RunStatus, StepStatus
from tests.fakes import FakeStatusError, make_llm
from tests.test_phase2 import QUALIFY_HOT, classify, draft, judge, run_lead


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def held_reply():
    run_id, status, _ = run_lead([classify(), QUALIFY_HOT, draft(), judge(unsupported=1), draft(), judge(unsupported=1)])
    assert status == "waiting_approval"
    with SessionLocal() as db:
        return run_id, db.query(Approval).filter_by(run_id=run_id).one().id


def test_two_decisions_arriving_together_only_one_wins(client):
    _, approval_id = held_reply()
    # two requests that both read the approval as pending before either writes
    a, b = SessionLocal(), SessionLocal()
    assert a.get(Approval, approval_id).status == b.get(Approval, approval_id).status == ApprovalStatus.pending
    first = claim(a, Approval, approval_id, ApprovalStatus.pending, status=ApprovalStatus.approved)
    second = claim(b, Approval, approval_id, ApprovalStatus.pending, status=ApprovalStatus.rejected)
    a.close(), b.close()
    assert (first, second) == (True, False)
    with SessionLocal() as db:
        assert db.get(Approval, approval_id).status == ApprovalStatus.approved  # the loser changed nothing


def test_a_resume_delivered_twice_sends_once(client, monkeypatch):
    run_id, approval_id = held_reply()
    sends = []
    import app.automations.lead_handler as lh
    real = lh.send_reply
    monkeypatch.setattr(lh, "send_reply", lambda *a, **k: sends.append(1) or real(*a, **k))
    with SessionLocal() as db:
        approval = db.get(Approval, approval_id)
        approval.status, approval.final_payload = ApprovalStatus.approved, {"reply": "ok"}
        db.commit()
    assert executor.resume_run(run_id, approval_id, llm=make_llm([])) == "succeeded"
    assert executor.resume_run(run_id, approval_id, llm=make_llm([])) == "succeeded"  # the duplicate is a no-op
    assert len(sends) == 1


def test_a_job_delivered_twice_runs_once():
    with SessionLocal() as db:
        run_id = executor.create_run(db, "system_check", {}).id
    with SessionLocal() as db:
        assert claim(db, Run, run_id, RunStatus.queued, status=RunStatus.running)
    # the second delivery finds it already claimed and leaves it alone
    assert executor.execute_run(run_id, llm=make_llm([])) == "running"


def test_retry_keeps_the_failed_attempt():
    run_id, status, _ = run_lead([classify(), FakeStatusError(400)])
    assert status == "failed"
    with SessionLocal() as db:
        reset_for_retry(db, db.get(Run, run_id))
    executor.execute_run(run_id, llm=make_llm([classify(), QUALIFY_HOT, draft(), judge()]))
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run.status == RunStatus.succeeded
        attempt = run.output["previous_attempts"][0]
        assert [s["node_id"] for s in attempt["steps"]] == ["intake", "classify", "retrieve", "qualify"]
        assert attempt["steps"][-1]["status"] == "failed" and "400" in attempt["steps"][-1]["error"]
        assert "400" in run.output["previous_errors"][0]


def test_no_retry_after_the_reply_was_sent(client, monkeypatch):
    # the email goes out, then saving the lead fails: a retry would email the customer again
    import app.automations.lead_handler as lh
    monkeypatch.setattr(lh.LeadHandler, "_save", staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db hiccup"))))
    run_id, status, _ = run_lead([classify(), QUALIFY_HOT, draft(), judge()])
    assert status == "failed"
    with SessionLocal() as db:
        with pytest.raises(RetryRefused, match="send"):
            reset_for_retry(db, db.get(Run, run_id))
    resp = client.post(f"/api/runs/{run_id}/retry")
    assert resp.status_code == 409 and "send" in resp.json()["detail"]


def test_runs_left_running_by_a_dead_process_are_marked_failed():
    with SessionLocal() as db:
        old = executor.create_run(db, "lead_handler", {"channel": "email", "contact": "x@example.com", "message": "hello there"})
        fresh = executor.create_run(db, "system_check", {})
        stored = (lambda t: t.replace(tzinfo=None)) if db.bind.dialect.name == "sqlite" else (lambda t: t)
        old.status, old.started_at = RunStatus.running, stored(datetime.now(timezone.utc) - timedelta(minutes=30))
        fresh.status, fresh.started_at = RunStatus.running, stored(datetime.now(timezone.utc))
        db.add(Lead(run_id=old.id, channel="email", contact="x@example.com", message="hello there"))
        db.commit()
        old_id, fresh_id = old.id, fresh.id
    with SessionLocal() as db:
        assert recover_interrupted(db) >= 1
    with SessionLocal() as db:
        assert db.get(Run, old_id).status == RunStatus.failed and db.get(Run, old_id).error == INTERRUPTED
        assert db.query(Lead).filter_by(run_id=old_id).one().status == "failed"
        assert db.get(Run, fresh_id).status == RunStatus.running  # maybe a worker is still on it
        db.get(Run, fresh_id).status = RunStatus.failed
        db.commit()
