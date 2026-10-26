"""Phase 0 smoke tests. conftest.py points them at SQLite, so they need no Docker:
    cd backend && pytest -q
"""
import uuid

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Automation, Run, RunStatus, RunStep, StepStatus


def test_health_reports_database_ok():
    with TestClient(app) as client:
        body = client.get("/health").json()
    assert body["database"] == "ok"
    assert body["status"] in {"ok", "degraded"}


def test_automations_seeded_with_valid_graphs():
    with TestClient(app) as client:
        slugs = [a["slug"] for a in client.get("/api/automations").json()]
        assert slugs == ["lead_handler", "doc_extractor", "daily_digest", "system_check"]

        for slug in slugs:
            graph = client.get(f"/api/automations/{slug}").json()["graph"]
            node_ids = {n["id"] for n in graph["nodes"]}
            # every edge must point at real nodes, or React Flow renders a broken graph
            for edge in graph["edges"]:
                assert edge["source"] in node_ids and edge["target"] in node_ids, (slug, edge)


def test_run_with_steps_round_trip():
    with TestClient(app) as client:
        with SessionLocal() as db:
            automation = db.query(Automation).filter_by(slug="lead_handler").one()
            run = Run(automation_id=automation.id, status=RunStatus.succeeded, input={"msg": "hi"})
            run.steps = [
                RunStep(node_id="intake", position=0, status=StepStatus.succeeded),
                RunStep(node_id="classify", position=1, status=StepStatus.succeeded,
                        model="llama-3.3-70b-versatile", prompt_tokens=120, completion_tokens=8),
            ]
            db.add(run)
            db.commit()
            run_id = run.id

        body = client.get(f"/api/runs/{run_id}").json()
        assert [s["node_id"] for s in body["steps"]] == ["intake", "classify"]
        assert client.get(f"/api/runs/{uuid.uuid4()}").status_code == 404
