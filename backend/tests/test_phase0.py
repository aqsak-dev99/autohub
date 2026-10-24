"""Phase 0 smoke tests. Run with SQLite so they need no Docker:
    cd backend && DATABASE_URL=sqlite:///./test.db pytest -q
"""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Automation, Run, RunStatus, RunStep, StepStatus  # noqa: E402


def test_health_reports_database_ok():
    with TestClient(app) as client:
        body = client.get("/health").json()
    assert body["database"] == "ok"
    assert body["status"] in {"ok", "degraded"}


def test_three_automations_seeded_with_graphs():
    with TestClient(app) as client:
        slugs = [a["slug"] for a in client.get("/api/automations").json()]
        assert slugs == ["lead_handler", "doc_extractor", "daily_digest"]

        graph = client.get("/api/automations/lead_handler").json()["graph"]
        node_ids = {n["id"] for n in graph["nodes"]}
        # every edge must point at real nodes, or React Flow renders a broken graph
        for edge in graph["edges"]:
            assert edge["source"] in node_ids and edge["target"] in node_ids


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
