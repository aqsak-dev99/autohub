"""Phase 2 tests: the Lead Handler, approvals and lead rules, with a scripted fake LLM."""
import uuid

import pytest
from fastapi.testclient import TestClient

import app.engine.executor as executor
from app.automations import lead_rules as rules
from app.config import get_settings
from app.db import SessionLocal
from app.knowledge import get_kb
from app.main import app
from app.models import Approval, ApprovalStatus, Lead, Run, StepStatus
from tests.fakes import make_llm

ENGLISH_LEAD = {
    "channel": "web_form", "contact": "ayesha@example.com", "name": "Ayesha",
    "message": "Hi, we run a skincare brand online and want Instagram and Meta ads. Budget is around Rs 300,000 "
               "a month and we'd like to start within two weeks. Can we get on a call?",
}


def classify(intent="new_business", language="english", confidence=0.95, unoffered=False, query="social media ads cost"):
    return {"intent": intent, "language": language, "search_query": query, "asks_price": True,
            "wants_unoffered_service": unoffered, "confidence": confidence}


QUALIFY_HOT = {"services": ["social-media", "paid-advertising"], "business_type": "skincare brand",
               "monthly_budget_pkr": 300000, "timeline": "within two weeks", "urgency": "high", "wants_call": True}

GOOD_REPLY = ("Hi Ayesha! Thanks for reaching out. We run social media and paid advertising for brands like yours. "
              "Most clients spend between Rs 150,000 and Rs 400,000 a month with us, plus their ad budget, and we "
              "quote a fixed fee after the audit. Would a 15-minute call tomorrow work? Team flowpath")


def draft(reply=GOOD_REPLY):
    return {"reply": reply, "used_passage_ids": ["faq-0", "service-social-media"]}


def judge(unsupported=0, language_matches=True, extra=None):
    """A judge verdict: one supported fact, one courtesy, plus `unsupported` unsupported commitments."""
    claims = [{"text": "Most clients spend Rs 150,000 to Rs 400,000 a month", "kind": "fact_about_flowpath",
               "supported": True},
              {"text": "Would a 15-minute call work?", "kind": "courtesy", "supported": True}]
    claims += [{"text": f"made-up promise {i}", "kind": "commitment", "supported": False} for i in range(unsupported)]
    return {"claims": claims + (extra or []), "language_matches": language_matches}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def run_lead(script, payload=None):
    llm = make_llm(script)
    with SessionLocal() as db:
        run_id = executor.create_run(db, "lead_handler", payload or ENGLISH_LEAD).id
    status = executor.execute_run(run_id, llm=llm)
    return run_id, status, llm


def load(run_id):
    with SessionLocal() as db:
        run = db.get(Run, uuid.UUID(str(run_id)))
        steps = [(s.node_id, s.status) for s in run.steps]
        lead = db.query(Lead).filter_by(run_id=run.id).one()
        approval = db.query(Approval).filter_by(run_id=run.id).one_or_none()
        db.expunge_all()
        return run, steps, lead, approval


# ---------- full runs ----------

def test_confident_grounded_reply_is_auto_sent(client):
    run_id, status, llm = run_lead([classify(), QUALIFY_HOT, draft(), judge()])
    assert status == "succeeded"
    run, steps, lead, approval = load(run_id)
    assert [n for n, _ in steps] == ["intake", "classify", "retrieve", "qualify", "draft", "score", "send", "save_lead"]
    assert all(s == StepStatus.succeeded for _, s in steps)
    assert approval is None
    assert (lead.status, lead.replied, lead.temperature, lead.score) == ("replied", True, "hot", 100)
    assert lead.budget_band == "150k_400k" and lead.language == "english"
    # the customer-facing draft uses the stronger model, the rest the cheap one
    models = [call["model"] for call in llm.sdk.calls]
    assert models == ["openai/gpt-oss-20b", "openai/gpt-oss-20b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]


def test_low_confidence_pauses_then_approve_sends(client, monkeypatch):
    run_id, status, _ = run_lead([classify(), QUALIFY_HOT, draft(), judge(unsupported=1)])
    assert status == "waiting_approval"
    run, steps, lead, approval = load(run_id)
    assert steps[-1] == ("approval", StepStatus.waiting)
    assert lead.status == "awaiting_approval" and not lead.replied
    assert "confidence 0.50 < 0.80" in approval.reason
    assert approval.payload["passages"] and approval.payload["qualification"]["budget_band"] == "150k_400k"

    monkeypatch.setattr(executor, "get_llm", lambda: make_llm([]))  # resume makes no LLM calls
    resp = client.post(f"/api/approvals/{approval.id}/decision", json={"action": "approve"})
    assert resp.status_code == 200 and resp.json()["status"] == "approved"

    run, steps, lead, approval = load(run_id)
    assert run.status.value == "succeeded" and run.finished_at is not None
    assert [n for n, _ in steps][-3:] == ["approval", "send", "save_lead"]
    assert steps[-3][1] == StepStatus.succeeded
    assert lead.status == "replied" and lead.reply == GOOD_REPLY
    assert approval.final_payload["similarity"] == 1.0


def test_edit_is_sent_and_similarity_recorded(client, monkeypatch):
    run_id, _, _ = run_lead([classify(), QUALIFY_HOT, draft(), judge(unsupported=1)])
    approval_id = load(run_id)[3].id
    monkeypatch.setattr(executor, "get_llm", lambda: make_llm([]))
    edited = GOOD_REPLY.replace("tomorrow", "on Thursday at 3 pm")
    client.post(f"/api/approvals/{approval_id}/decision", json={"action": "edit", "reply": edited})

    _, _, lead, approval = load(run_id)
    assert approval.status == ApprovalStatus.edited
    assert 0.8 < approval.final_payload["similarity"] < 1.0
    assert lead.reply == edited


def test_reject_saves_without_sending(client, monkeypatch):
    run_id, _, _ = run_lead([classify(), QUALIFY_HOT, draft(), judge(unsupported=1)])
    approval_id = load(run_id)[3].id
    monkeypatch.setattr(executor, "get_llm", lambda: make_llm([]))
    client.post(f"/api/approvals/{approval_id}/decision", json={"action": "reject", "note": "spam-ish"})

    run, steps, lead, _ = load(run_id)
    assert run.status.value == "succeeded"
    assert "send" not in [n for n, _ in steps]
    assert (lead.status, lead.replied) == ("rejected", False)


def test_second_decision_is_refused(client, monkeypatch):
    run_id, _, _ = run_lead([classify(), QUALIFY_HOT, draft(), judge(unsupported=1)])
    approval_id = load(run_id)[3].id
    monkeypatch.setattr(executor, "get_llm", lambda: make_llm([]))
    assert client.post(f"/api/approvals/{approval_id}/decision", json={"action": "approve"}).status_code == 200
    assert client.post(f"/api/approvals/{approval_id}/decision", json={"action": "approve"}).status_code == 409


def test_edit_without_text_is_rejected(client):
    run_id, _, _ = run_lead([classify(), QUALIFY_HOT, draft(), judge(unsupported=1)])
    approval_id = load(run_id)[3].id
    assert client.post(f"/api/approvals/{approval_id}/decision", json={"action": "edit"}).status_code == 422


def test_arabic_reply_is_always_reviewed(client):
    run_id, status, _ = run_lead([classify(language="arabic"), QUALIFY_HOT, draft(), judge()])
    assert status == "waiting_approval"
    assert "Arabic replies are reviewed" in load(run_id)[3].reason


def test_invented_price_is_caught(client):
    reply = "Hi Ayesha! Our social media package is Rs 50,000 a month. Team flowpath"
    run_id, status, _ = run_lead([classify(), QUALIFY_HOT, draft(reply), judge()])
    assert status == "waiting_approval"
    assert "price not in knowledge base: Rs 50,000" in load(run_id)[3].reason


def test_unoffered_service_goes_to_review(client):
    run_id, status, _ = run_lead([classify(unoffered=True), QUALIFY_HOT, draft(), judge()])
    assert status == "waiting_approval"
    assert "service flowpath doesn't offer" in load(run_id)[3].reason


def test_spam_stops_after_classify(client):
    payload = {"channel": "whatsapp", "contact": "+920000000000", "message": "You won a free iPhone! bit.ly/x"}
    run_id, status, llm = run_lead([classify(intent="spam", confidence=0.97)], payload)
    assert status == "succeeded" and len(llm.sdk.calls) == 1
    _, steps, lead, _ = load(run_id)
    assert [n for n, _ in steps] == ["intake", "classify", "save_lead"]
    assert lead.status == "spam" and not lead.replied


def test_job_applicant_skips_qualification(client):
    payload = {"channel": "whatsapp", "contact": "+921111111111",
               "message": "Kya aap ke paas video editor ki job hai? Main 2 saal se Reels edit kar raha hoon"}
    reply = "Shukriya! Hum Video editor hire kar rahe hain. Apni CV hello@flowpath.example par bhejein. Team flowpath"
    run_id, status, llm = run_lead([classify(intent="job_applicant", language="roman_urdu"), draft(reply), judge()],
                                   payload)
    assert status == "succeeded" and len(llm.sdk.calls) == 3  # no qualify call
    _, steps, lead, _ = load(run_id)
    assert dict(steps)["qualify"] == StepStatus.skipped
    assert lead.temperature == "not_a_lead" and lead.status == "replied"


def test_invalid_payload_fails_at_intake(client):
    run_id, status, _ = run_lead([], {"channel": "fax", "contact": "x", "message": "hi"})
    assert status == "failed"
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        assert run.steps[0].node_id == "intake" and run.steps[0].status == StepStatus.failed


# ---------- API ----------

def test_inbound_endpoint_runs_the_lead_handler(client, monkeypatch):
    monkeypatch.setattr(executor, "get_llm", lambda: make_llm([classify(), QUALIFY_HOT, draft(), judge()]))
    resp = client.post("/api/leads/inbound", json=ENGLISH_LEAD)
    assert resp.status_code == 202
    run = client.get(f"/api/runs/{resp.json()['run_id']}").json()
    assert run["status"] == "succeeded"
    hot = client.get("/api/leads", params={"temperature": "hot"}).json()
    assert any(lead["run_id"] == resp.json()["run_id"] for lead in hot)


def test_inbound_endpoint_validates_and_checks_key(client, monkeypatch):
    assert client.post("/api/leads/inbound", json={**ENGLISH_LEAD, "channel": "fax"}).status_code == 422
    monkeypatch.setattr(get_settings(), "inbound_api_key", "s3cret")
    assert client.post("/api/leads/inbound", json=ENGLISH_LEAD).status_code == 401
    assert client.post("/api/leads/inbound", json=ENGLISH_LEAD,
                       headers={"X-AutoHub-Key": "wrong"}).status_code == 401


def test_knowledge_search_endpoint(client):
    body = client.get("/api/knowledge/search", params={"q": "how much does it cost"}).json()
    assert body["hits"][0]["id"] == "faq-0" and body["kb_version"] == get_kb().version


# ---------- rules ----------

@pytest.mark.parametrize("text,expected", [
    ("between Rs 150,000 and Rs 400,000", {150_000, 400_000}),
    ("fee 1.5 lakh monthly", {150_000}),
    ("Rs 1,50,000", {150_000}),
    ("we charge 50k", {50_000}),
    ("۱۵۰٬۰۰۰ روپے", {150_000}),
    ("since 2019, a 15 minute call", set()),
])
def test_money_amounts(text, expected):
    assert rules.money_amounts(text) == expected


def test_lead_score_is_explained():
    score, temp, reasons = rules.score_lead("new_business", ["seo"], "under_150k", "low", None, False)
    assert (score, temp) == (45, "warm")
    assert reasons == ["+30 wants to work with flowpath", "+10 interested in 1 service(s)",
                       "+5 budget Under Rs 150,000 a month"]


def test_budget_bands_follow_flowpath_form():
    assert [rules.budget_band(v) for v in (None, 100_000, 150_000, 999_999, 2_000_000)] == \
        ["unknown", "under_150k", "150k_400k", "400k_1m", "over_1m"]


# ---------- fixes from the first real run ----------

def test_rate_limit_waits_for_the_hint_and_gets_more_attempts(monkeypatch):
    import tenacity.nap

    from tests.fakes import FakeStatusError

    waits = []
    monkeypatch.setattr(tenacity.nap.time, "sleep", waits.append)

    class RateLimited(FakeStatusError):
        def __init__(self):
            super().__init__(429)
            self.args = ("Rate limit reached. Please try again in 7.5s.",)

    # 5 rate limits then success: more than LLM_MAX_RETRIES (3), within LLM_RATE_LIMIT_RETRIES (6)
    llm = make_llm([RateLimited() for _ in range(5)] + ["ok"])
    result = llm.complete([{"role": "user", "content": "x"}])
    assert result.content == "ok" and result.attempts == 6
    assert all(w >= 7.5 for w in waits)  # never retried sooner than Groq asked


def test_restating_the_customers_budget_is_not_an_invented_price(client):
    reply = "Hi Ayesha! You mentioned a budget of around Rs 300,000 a month. The audit confirms scope. Team flowpath"
    run_id, status, _ = run_lead([classify(), QUALIFY_HOT, draft(reply), judge()])
    assert status == "succeeded"


def test_failed_run_marks_lead_failed_and_can_be_retried(client, monkeypatch):
    from tests.fakes import FakeStatusError

    run_id, status, _ = run_lead([FakeStatusError(400)])
    assert status == "failed"
    with SessionLocal() as db:
        lead = db.query(Lead).filter_by(run_id=run_id).one()
        assert lead.status == "failed"

    monkeypatch.setattr(executor, "get_llm", lambda: make_llm([classify(), QUALIFY_HOT, draft(), judge()]))
    resp = client.post(f"/api/runs/{run_id}/retry")
    assert resp.status_code == 202
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "succeeded" and "400" in run["output"]["previous_errors"][0]
    assert [s["node_id"] for s in run["steps"]][0] == "intake" and len(run["steps"]) == 8
    with SessionLocal() as db:
        leads = db.query(Lead).filter_by(run_id=run_id).all()
        assert len(leads) == 1 and leads[0].status == "replied"  # same lead, not a duplicate
    assert client.post(f"/api/runs/{run_id}/retry").status_code == 409  # only failed runs


def test_review_reason_labels_read_naturally(client):
    run_id, _, _ = run_lead([classify(language="urdu"), QUALIFY_HOT, draft(), judge()])
    assert load(run_id)[3].reason == "Urdu-script replies are reviewed until evals verify accuracy"


def test_services_and_pricing_passages_are_always_given_to_the_draft(client):
    # a message that matches nothing about services or pricing in the knowledge base
    payload = {"channel": "web_chat", "contact": "x@example.com", "message": "Can you build a mobile app for our gym?"}
    run_id, _, llm = run_lead([classify(unoffered=True, query="mobile app gym"), QUALIFY_HOT, draft(), judge()],
                              payload)
    draft_prompt = llm.sdk.calls[2]["messages"][-1]["content"]
    judge_prompt = llm.sdk.calls[3]["messages"][-1]["content"]
    for pid in ("[services-overview]", "[faq-0]", "[process]"):
        assert pid in draft_prompt and pid in judge_prompt  # the judge checks against the same passages
    with SessionLocal() as db:
        retrieve = next(s for s in db.get(Run, run_id).steps if s.node_id == "retrieve")
        assert {p["id"] for p in retrieve.output["passages"] if p["pinned"]} <= {"services-overview", "faq-0", "process"}


def test_judge_noise_on_courtesy_and_restatements_is_ignored(client):
    # seen in a real run: the judge marked a call offer and the customer's own budget as "unsupported"
    noise = [{"text": "Shall we book a 15-minute call?", "kind": "courtesy", "supported": False},
             {"text": "You mentioned Rs 300,000 a month", "kind": "restates_customer", "supported": False}]
    run_id, status, _ = run_lead([classify(), QUALIFY_HOT, draft(), judge(extra=noise)])
    assert status == "succeeded"
    with SessionLocal() as db:
        score = next(s for s in db.get(Run, run_id).steps if s.node_id == "score")
        assert score.output["confidence"] == 1.0 and score.output["route"] == "auto"


def test_confidence_is_share_of_supported_claims(client):
    run_id, status, _ = run_lead([classify(), QUALIFY_HOT, draft(), judge(unsupported=3)])
    assert status == "waiting_approval"
    approval = load(run_id)[3]
    assert "confidence 0.25 < 0.80" in approval.reason  # 1 of 4 claims needing support is supported
    assert approval.reason.count("made-up promise") == 3


def test_judge_uses_more_reasoning_than_other_steps(client):
    _, _, llm = run_lead([classify(), QUALIFY_HOT, draft(), judge()])
    assert [c["reasoning_effort"] for c in llm.sdk.calls] == ["low", "low", "low", "medium"]
