"""Phase 5 tests: the numbers behind the dashboard."""
import pytest
from fastapi.testclient import TestClient

import app.engine.executor as executor
from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from tests.fakes import make_llm
from tests.test_phase2 import ENGLISH_LEAD, QUALIFY_HOT, classify, draft, judge


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def run_lead(script):
    with SessionLocal() as db:
        run_id = executor.create_run(db, "lead_handler", ENGLISH_LEAD).id
    executor.execute_run(run_id, llm=make_llm(script))
    return run_id


def test_overview_counts_runs_leads_and_series(client):
    before = client.get("/api/stats/overview").json()
    run_lead([classify(), QUALIFY_HOT, draft(), judge()])              # auto-sent
    run_lead([classify(), QUALIFY_HOT, draft(), judge(unsupported=1)])  # waits for review
    after = client.get("/api/stats/overview").json()
    assert after["runs"] == before["runs"] + 2
    assert after["leads"] == before["leads"] + 2 and after["hot_leads"] >= 2
    assert after["pending_approvals"] == before["pending_approvals"] + 1
    assert len(after["series"]) == 7 and after["series"][-1]["runs"] >= 2
    assert 0 <= after["success_rate"] <= 1 and after["median_run_seconds"] is not None
    assert after["hot"][0]["name"] and after["hot"][0]["run_id"]


def test_edit_rate_counts_human_changes(client, monkeypatch):
    monkeypatch.setattr(executor, "get_llm", lambda: make_llm([]))
    run_id = run_lead([classify(), QUALIFY_HOT, draft(), judge(unsupported=1)])
    approval = next(a for a in client.get("/api/approvals").json() if a["run_id"] == str(run_id))
    client.post(f"/api/approvals/{approval['id']}/decision", json={"action": "edit", "reply": "A different reply."})
    assert client.get("/api/stats/overview").json()["edit_rate"] > 0


def test_node_stats_for_heatmap(client):
    run_lead([classify(), QUALIFY_HOT, draft(), judge()])
    body = client.get("/api/stats/automations/lead_handler/nodes").json()
    nodes = body["nodes"]
    assert body["runs"] >= 1
    assert nodes["draft"]["avg_tokens"] == 120 and nodes["draft"]["avg_cost_usd"] > 0
    assert nodes["intake"]["share_of_runs"] == 1.0
    assert nodes["approval"]["human"] is True if "approval" in nodes else True
    assert client.get("/api/stats/automations/nope/nodes").status_code == 404


def test_runs_have_readable_labels(client):
    run_lead([classify(), QUALIFY_HOT, draft(), judge()])
    runs = client.get("/api/runs", params={"automation": "lead_handler", "limit": 1}).json()
    assert runs[0]["label"] == "Ayesha · web_form"


# ---------- rules page ----------

def test_rules_default_to_env_then_save(client):
    rules = client.get("/api/rules").json()
    assert rules["auto_send_confidence"] == 0.8 and rules["review_languages"] == ["urdu", "arabic"]
    changed = {**rules, "review_languages": ["arabic", "urdu", "roman_urdu"], "review_existing_client": False}
    saved = client.put("/api/rules", json=changed).json()
    assert saved["review_languages"] == ["roman_urdu", "urdu", "arabic"]  # stable order
    assert client.get("/api/rules").json()["review_existing_client"] is False
    client.put("/api/rules", json=rules)  # restore for other tests
    assert client.put("/api/rules", json={**rules, "review_languages": ["klingon"]}).status_code == 422


def test_saved_rules_change_routing_and_preview_replays_them(client):
    from app.automations.lead_rules import replay_route
    from app.rules_store import LeadRules

    classify_out = {"language": "urdu", "intent": "new_business", "wants_unoffered_service": False}
    score_out = {"confidence": 1.0, "language_matches": True, "price_issues": [],
                 "claims": [{"text": "We offer SEO", "kind": "fact_about_flowpath", "supported": True}]}
    strict = LeadRules(auto_send_confidence=0.8, review_languages=["urdu"])
    relaxed = LeadRules(auto_send_confidence=0.8, review_languages=[])
    assert replay_route(classify_out, score_out, strict) and not replay_route(classify_out, score_out, relaxed)

    unsupported = {**score_out, "claims": [{"text": "Results in 2 weeks", "kind": "commitment", "supported": False}]}
    assert replay_route(classify_out, unsupported, relaxed)  # made-up promises are never a switch

    preview = client.post("/api/rules/preview", json=relaxed.model_dump()).json()
    assert preview["review_with_rules"] <= preview["review_now"]
    assert {"replies", "would_send_on_its_own", "would_ask_you"} <= set(preview)


def test_live_endpoint_shape(client):
    body = client.get("/api/stats/live").json()
    assert isinstance(body["active"], list)
    assert {"received", "sent_on_its_own", "asked_you", "spam"} <= set(body["today"])


def test_test_message_and_conversation(client, monkeypatch):
    monkeypatch.setattr("app.api.leads.dispatch", lambda run_id, background: "test")
    monkeypatch.setattr(get_settings(), "inbound_api_key", "secret")  # the dashboard route doesn't need it
    resp = client.post("/api/test-message", json={"message": "Salam, ads ka kitna kharcha hai?"})
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    body = client.get(f"/api/conversations/{run_id}").json()
    assert body == {"lead": None, "approval": None}  # nothing yet: the run hasn't executed
