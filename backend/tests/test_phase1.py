"""Phase 1 tests: the LLM client and run engine, using a fake Groq SDK.
No API key or network needed, so these run in CI too."""
import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

import app.engine.executor as executor
from app.db import SessionLocal
from app.engine.base import IMPLEMENTATIONS, BaseAutomation, NeedsApproval
from app.llm.client import LLMOutputError
from app.main import app
from app.models import Approval, Run, StepStatus
from tests.fakes import FakeStatusError, make_llm


# ---------- LLM client ----------

def test_cost_is_calculated_from_tokens():
    result = make_llm(["hi"]).complete([{"role": "user", "content": "x"}])
    # 100 * 0.075/1M + 20 * 0.30/1M
    assert result.cost_usd == pytest.approx(0.0000135)
    assert result.priced and result.attempts == 1


def test_transient_errors_are_retried_then_succeed():
    llm = make_llm([FakeStatusError(429), FakeStatusError(503), "ok"])
    result = llm.complete([{"role": "user", "content": "x"}])
    assert result.content == "ok" and result.attempts == 3


def test_non_transient_error_fails_immediately():
    llm = make_llm([FakeStatusError(400), "never reached"])
    with pytest.raises(FakeStatusError):
        llm.complete([{"role": "user", "content": "x"}])
    assert len(llm.sdk.calls) == 1


class Intent(BaseModel):
    intent: str
    confidence: float


def test_json_repair_feeds_errors_back_and_counts_all_tokens():
    llm = make_llm(['{"intent": "pricing"}', '{"intent": "pricing", "confidence": 0.9}'])
    result = llm.complete_json([{"role": "user", "content": "x"}], Intent)
    assert result.parsed.confidence == 0.9
    assert result.repairs == 1
    assert result.prompt_tokens == 200  # both calls counted
    # the second call must include the validation error so the model can fix it
    assert "confidence" in llm.sdk.calls[1]["messages"][-1]["content"]


def test_json_gives_up_after_max_repairs():
    llm = make_llm(["not json", "still not json"])
    with pytest.raises(LLMOutputError):
        llm.complete_json([{"role": "user", "content": "x"}], Intent, max_repairs=1)


# ---------- run engine ----------

def _new_run(slug: str, payload: dict | None = None) -> str:
    with SessionLocal() as db:
        return str(executor.create_run(db, slug, payload or {}).id)


def _load(run_id: str) -> Run:
    with SessionLocal() as db:
        run = db.get(Run, uuid.UUID(run_id))
        _ = run.steps  # load before session closes
        return run


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_system_check_succeeds_and_traces_every_step(client):
    llm = make_llm(["pong", '{"status": "ok", "model_says": "It runs automations."}'])
    run_id = _new_run("system_check")
    assert executor.execute_run(run_id, llm=llm) == "succeeded"

    run = _load(run_id)
    assert [s.node_id for s in run.steps] == ["models", "llm_text", "llm_json"]
    assert all(s.status == StepStatus.succeeded for s in run.steps)
    assert run.steps[0].model is None and run.steps[1].prompt_tokens == 100
    assert run.total_tokens == 240  # two LLM calls x 120
    assert run.output["ok"] is True


def test_missing_model_fails_run_at_the_right_step(client):
    llm = make_llm([], models=("openai/gpt-oss-20b",))  # the draft model is missing
    run_id = _new_run("system_check")
    assert executor.execute_run(run_id, llm=llm) == "failed"
    run = _load(run_id)
    assert run.steps[-1].node_id == "models" and run.steps[-1].status == StepStatus.failed
    assert "gpt-oss-120b" in run.error


def test_needs_approval_pauses_run_and_creates_approval(client):
    class Pauser(BaseAutomation):
        slug = "system_check"

        def run(self, ctx, payload):
            with ctx.step("draft") as s:
                s.output = {"reply": "draft text"}
                raise NeedsApproval("reply_draft", "low confidence", {"reply": "draft text"})

    original = IMPLEMENTATIONS["system_check"]
    IMPLEMENTATIONS["system_check"] = Pauser()
    try:
        run_id = _new_run("system_check")
        assert executor.execute_run(run_id, llm=make_llm([])) == "waiting_approval"
    finally:
        IMPLEMENTATIONS["system_check"] = original

    run = _load(run_id)
    assert run.finished_at is None  # still open, waiting for a human
    with SessionLocal() as db:
        approval = db.query(Approval).filter_by(run_id=run.id).one()
    assert approval.reason == "low confidence"


def test_unimplemented_automation_fails_cleanly(client):
    from app.models import Automation
    with SessionLocal() as db:  # in the database, but with no code behind it
        if not db.query(Automation).filter_by(slug="not_built").one_or_none():
            db.add(Automation(slug="not_built", name="Not built", description="", trigger="manual", graph={"nodes": [], "edges": []}))
            db.commit()
    run_id = _new_run("not_built")
    assert executor.execute_run(run_id, llm=make_llm([])) == "failed"
    assert "no implementation" in _load(run_id).error


def test_run_is_not_executed_twice(client):
    llm = make_llm(["pong", '{"status": "ok", "model_says": "x"}'])
    run_id = _new_run("system_check")
    executor.execute_run(run_id, llm=llm)
    assert executor.execute_run(run_id, llm=llm) == "succeeded"  # second delivery is a no-op
    assert len(_load(run_id).steps) == 3


def test_trigger_endpoint_returns_202_and_unknown_slug_404(client, monkeypatch):
    llm = make_llm(["pong", '{"status": "ok", "model_says": "x"}'])
    monkeypatch.setattr(executor, "get_llm", lambda: llm)
    resp = client.post("/api/automations/system_check/runs", json={"input": {}})
    assert resp.status_code == 202 and resp.json()["dispatched_via"] == "background"
    # TestClient runs background tasks before returning, so the run is already done
    assert client.get(f"/api/runs/{resp.json()['id']}").json()["status"] == "succeeded"
    assert client.post("/api/automations/nope/runs", json={}).status_code == 404


def test_root_redirects_to_docs(client):
    assert client.get("/", follow_redirects=False).headers["location"] == "/docs"


class FakeJsonRejected(Exception):
    """What Groq raises when JSON mode output is invalid, e.g. cut off."""
    status_code = 400
    body = {"error": {"code": "json_validate_failed", "failed_generation": '{"intent": "pri'}}


def test_provider_json_rejection_is_repaired_not_fatal():
    llm = make_llm([FakeJsonRejected("Failed to validate JSON"), '{"intent": "pricing", "confidence": 0.9}'])
    result = llm.complete_json([{"role": "user", "content": "x"}], Intent)
    assert result.parsed.intent == "pricing" and result.repairs == 1
    assert "cut off" in llm.sdk.calls[1]["messages"][-1]["content"]


def test_ordinary_bad_request_still_fails_fast():
    llm = make_llm([FakeStatusError(400), "never reached"])
    with pytest.raises(FakeStatusError):
        llm.complete_json([{"role": "user", "content": "x"}], Intent)
    assert len(llm.sdk.calls) == 1
