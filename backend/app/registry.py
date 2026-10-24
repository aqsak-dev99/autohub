"""The three automations AutoHub ships with, seeded into the DB on startup.

Each `graph` is in React Flow's own shape ({nodes, edges}), so the dashboard
can render it directly. Node ids here are the same ids the run engine logs
in RunStep.node_id, which is how a live run lights up the right node.
"""
from sqlalchemy.orm import Session

from app.models import Automation


def _node(id: str, label: str, x: int, y: int, kind: str = "step") -> dict:
    return {"id": id, "type": kind, "position": {"x": x, "y": y}, "data": {"label": label}}


def _edge(src: str, dst: str, label: str | None = None) -> dict:
    e = {"id": f"{src}-{dst}", "source": src, "target": dst}
    if label:
        e["label"] = label
    return e


AUTOMATIONS: list[dict] = [
    {
        "slug": "lead_handler",
        "name": "Lead Handler",
        "description": "Classifies an incoming WhatsApp/email inquiry, answers from the knowledge base, "
                       "and auto-sends or queues the reply for approval based on confidence.",
        "trigger": "webhook",
        "graph": {
            "nodes": [
                _node("intake", "Message received", 0, 0, "trigger"),
                _node("classify", "Classify intent", 0, 100),
                _node("retrieve", "Search knowledge base", 0, 200),
                _node("draft", "Draft reply", 0, 300),
                _node("score", "Score confidence", 0, 400, "decision"),
                _node("send", "Auto-send reply", -160, 520),
                _node("approval", "Human approval", 160, 520, "human"),
                _node("save_lead", "Save lead", 0, 640),
            ],
            "edges": [
                _edge("intake", "classify"), _edge("classify", "retrieve"),
                _edge("retrieve", "draft"), _edge("draft", "score"),
                _edge("score", "send", "high"), _edge("score", "approval", "low"),
                _edge("send", "save_lead"), _edge("approval", "save_lead"),
            ],
        },
    },
    {
        "slug": "doc_extractor",
        "name": "Document Extractor",
        "description": "Extracts structured fields from an uploaded invoice or receipt, validates them, "
                       "self-corrects once, then escalates to a human if still invalid.",
        "trigger": "upload",
        "graph": {
            "nodes": [
                _node("upload", "File uploaded", 0, 0, "trigger"),
                _node("extract", "Vision extraction", 0, 100),
                _node("validate", "Validate fields", 0, 200, "decision"),
                _node("repair", "Self-correct with errors", 180, 200),
                _node("approval", "Human review", 0, 320, "human"),
                _node("save_doc", "Save document", -180, 320),
            ],
            "edges": [
                _edge("upload", "extract"), _edge("extract", "validate"),
                _edge("validate", "save_doc", "valid"), _edge("validate", "repair", "invalid"),
                _edge("repair", "validate", "retry"), _edge("validate", "approval", "still invalid"),
                _edge("approval", "save_doc"),
            ],
        },
    },
    {
        "slug": "daily_digest",
        "name": "Daily Digest",
        "description": "n8n-scheduled morning summary of yesterday's leads, documents and pending approvals.",
        "trigger": "schedule",
        "graph": {
            "nodes": [
                _node("schedule", "n8n schedule (9am)", 0, 0, "trigger"),
                _node("collect", "Collect stats", 0, 100),
                _node("summarize", "Summarize with AI", 0, 200),
                _node("deliver", "Send via email/WhatsApp", 0, 300),
            ],
            "edges": [
                _edge("schedule", "collect"), _edge("collect", "summarize"), _edge("summarize", "deliver"),
            ],
        },
    },
]


def seed_automations(db: Session) -> None:
    """Insert missing automations and refresh existing ones (idempotent: safe on every boot)."""
    for spec in AUTOMATIONS:
        row = db.query(Automation).filter_by(slug=spec["slug"]).one_or_none()
        if row is None:
            db.add(Automation(**spec))
        else:
            for key, value in spec.items():
                setattr(row, key, value)
    db.commit()
