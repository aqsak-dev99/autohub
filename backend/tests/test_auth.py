"""Login: owner password, demo visitors, machine key, and what each may do."""
import pytest
from fastapi.testclient import TestClient

import app.api.leads as leads_api
from app.auth import COOKIE, make_token, read_token
from app.config import get_settings
from app.main import app
from tests.test_phase2 import QUALIFY_HOT, TRANSLATION, classify, draft, judge, run_lead


@pytest.fixture
def secured(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "admin_password", "owner-pass")
    monkeypatch.setattr(s, "secret_key", "test-secret")
    monkeypatch.setattr(s, "demo_mode", True)
    monkeypatch.setattr(s, "inbound_api_key", "machine-key")
    monkeypatch.setattr(leads_api, "dispatch", lambda run_id, background: "test")
    leads_api._try_hits.clear()
    with TestClient(app) as c:
        yield c


def test_everything_needs_a_login_except_health_auth_and_form(secured):
    assert secured.get("/api/leads").status_code == 401
    assert secured.get("/api/stats/overview").status_code == 401
    assert secured.get("/health").status_code == 200
    assert secured.get("/api/auth/me").json() == {"role": None, "login_required": True, "demo_available": True}


def test_owner_login(secured):
    assert secured.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
    resp = secured.post("/api/auth/login", json={"password": "owner-pass"})
    assert resp.status_code == 200 and COOKIE in resp.cookies
    assert secured.get("/api/leads").status_code == 200
    assert secured.get("/api/auth/me").json()["role"] == "owner"
    rules = secured.get("/api/rules").json()
    assert secured.put("/api/rules", json=rules).status_code == 200
    secured.post("/api/auth/logout")
    assert secured.get("/api/leads").status_code == 401


def test_demo_visitor_can_look_and_try_but_not_change(secured):
    assert secured.post("/api/auth/demo").json()["role"] == "viewer"
    assert secured.get("/api/leads").status_code == 200
    rules = secured.get("/api/rules").json()
    assert secured.post("/api/rules/preview", json=rules).status_code == 200  # read-only "what if" is fine
    assert secured.put("/api/rules", json=rules).status_code == 403
    assert secured.post("/api/test-message", json={"message": "Salam, ads ka rate?"}).status_code == 202


def test_demo_visitor_approves_only_their_own_test_message(secured):
    # someone else's held reply
    run_lead([classify(language="urdu"), QUALIFY_HOT, draft(), judge(), TRANSLATION])
    # a held reply to a test message
    test_run, _, _ = run_lead([classify(language="urdu"), QUALIFY_HOT, draft(), judge(), TRANSLATION],
                              {"channel": "web_chat", "contact": "dashboard-test", "message": "سلام"})
    secured.post("/api/auth/demo")
    pending = secured.get("/api/approvals").json()
    theirs = next(a for a in pending if a["run_id"] == str(test_run))
    other = next(a for a in pending if a["payload"]["contact"] != "dashboard-test")
    assert secured.post(f"/api/approvals/{other['id']}/decision", json={"action": "approve"}).status_code == 403
    assert secured.post(f"/api/approvals/{theirs['id']}/decision", json={"action": "reject"}).status_code == 200


def test_machine_key_works_like_the_owner(secured):
    assert secured.get("/api/leads", headers={"X-AutoHub-Key": "machine-key"}).status_code == 200
    assert secured.get("/api/leads", headers={"X-AutoHub-Key": "nope"}).status_code == 401


def test_tokens_are_signed_and_expire(secured, monkeypatch):
    s = get_settings()
    token = make_token("owner", s)
    assert read_token(token, s) == "owner"
    assert read_token(token.replace("owner", "viewer", 1), s) is None  # tampered
    assert read_token("garbage", s) is None
    monkeypatch.setattr("app.auth.time.time", lambda: 10**12)
    assert read_token(token, s) is None  # expired
    monkeypatch.undo()
    monkeypatch.setattr(s, "demo_mode", False)
    assert read_token(make_token("viewer", s), s) is None  # demo switched off


def test_try_it_limits(secured, monkeypatch):
    monkeypatch.setattr(get_settings(), "try_it_per_hour", 2)
    secured.post("/api/auth/demo")
    for _ in range(2):
        assert secured.post("/api/test-message", json={"message": "hello there"}).status_code == 202
    assert secured.post("/api/test-message", json={"message": "hello there"}).status_code == 429
    leads_api._try_hits.clear()
    monkeypatch.setattr(get_settings(), "try_it_per_day", 0)
    assert secured.post("/api/test-message", json={"message": "hello there"}).status_code == 429


def test_public_form_is_off_in_production_until_origins_are_set(secured, monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "production")
    body = {"name": "Zainab", "email": "z@bakery.pk", "message": "How much for Instagram posts?"}
    assert secured.post("/api/forms/contact", json=body).status_code == 403
