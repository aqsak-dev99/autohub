"""The automations AutoHub ships with, seeded into the DB on startup.

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
        "description": "Qualifies an incoming email or website lead for flowpath, drafts a grounded reply "
                       "in the customer's language, and auto-sends it or queues it for human approval.",
        "trigger": "webhook",
        "graph": {
            "nodes": [
                _node("intake", "Message received", 0, 0, "trigger"),
                _node("classify", "Classify intent + language", 0, 100),
                _node("retrieve", "Search knowledge base", 0, 200),
                _node("qualify", "Qualify + score lead", 0, 300),
                _node("draft", "Draft reply", 0, 400),
                _node("score", "Fact-check + route", 0, 500, "decision"),
                _node("revise", "Remove unsupported claims", 240, 560),
                _node("translate", "Translate for the owner", 240, 680),
                _node("approval", "Human approval", 240, 800, "human"),
                _node("send", "Send reply", -120, 800),
                _node("save_lead", "Save lead", 0, 920),
            ],
            "edges": [
                _edge("intake", "classify"), _edge("classify", "retrieve"),
                _edge("classify", "save_lead", "spam"),
                _edge("retrieve", "qualify"), _edge("qualify", "draft"), _edge("draft", "score"),
                _edge("score", "send", "auto"), _edge("score", "revise", "unsupported"),
                _edge("score", "translate", "review"), _edge("score", "approval", "review"),
                _edge("revise", "send", "fixed"), _edge("revise", "translate", "review"),
                _edge("revise", "approval", "review"), _edge("translate", "approval"),
                _edge("approval", "send", "approved"), _edge("approval", "save_lead", "rejected"),
                _edge("send", "save_lead"),
            ],
        },
    },
    {
        "slug": "follow_up",
        "name": "Follow-up Nudge",
        "description": "Every morning, finds hot and warm leads who went quiet after our reply and drafts one "
                       "gentle follow-up in their language, fact-checked and routed by the same rules as replies.",
        "trigger": "schedule",
        "graph": {
            "nodes": [
                _node("pick", "Quiet lead found", 0, 0, "trigger"),
                _node("retrieve", "Search knowledge base", 0, 100),
                _node("draft", "Draft follow-up", 0, 200),
                _node("score", "Fact-check + route", 0, 300, "decision"),
                _node("translate", "Translate for the owner", 240, 380),
                _node("approval", "Human approval", 240, 500, "human"),
                _node("send", "Send follow-up", -120, 500),
                _node("save", "Mark followed up", 0, 620),
            ],
            "edges": [
                _edge("pick", "retrieve"), _edge("retrieve", "draft"), _edge("draft", "score"),
                _edge("score", "send", "auto"), _edge("score", "translate", "review"),
                _edge("score", "approval", "review"), _edge("translate", "approval"),
                _edge("approval", "send", "approved"), _edge("approval", "save", "skipped"),
                _edge("send", "save"),
            ],
        },
    },
    {
        "slug": "daily_digest",
        "name": "Daily Digest",
        "description": "n8n-scheduled morning email: today's top three tasks, then new and hot leads, replies "
                       "and follow-ups waiting, failed runs and AI cost. Code builds every number and every task; "
                       "the AI only puts the tasks in order and says why.",
        "trigger": "schedule",
        "graph": {
            "nodes": [
                _node("schedule", "n8n schedule (9am)", 0, 0, "trigger"),
                _node("collect", "Collect stats + tasks", 0, 100),
                _node("summarize", "Prioritize with AI", 0, 200),
                _node("deliver", "Send by email", 0, 300),
            ],
            "edges": [
                _edge("schedule", "collect"), _edge("collect", "summarize"), _edge("summarize", "deliver"),
            ],
        },
    },
    {
        "slug": "system_check",
        "name": "System Check",
        "description": "Verifies the hub end to end: configured Groq models exist, a plain completion "
                       "works, and structured JSON output validates.",
        "trigger": "manual",
        "graph": {
            "nodes": [
                _node("models", "Check models available", 0, 0, "trigger"),
                _node("llm_text", "Plain completion", 0, 100),
                _node("llm_json", "Structured JSON output", 0, 200),
            ],
            "edges": [_edge("models", "llm_text"), _edge("llm_text", "llm_json")],
        },
    },
]


def seed_automations(db: Session) -> None:
    """Insert missing automations, refresh existing ones, and drop retired ones (idempotent: safe on every boot).

    A retired automation (e.g. the Document Extractor, never built) is deleted if it has no runs,
    otherwise disabled so its history stays readable."""
    current = {spec["slug"] for spec in AUTOMATIONS}
    for row in db.query(Automation).filter(Automation.slug.notin_(current)).all():
        if row.runs:
            row.enabled = False
        else:
            db.delete(row)
    for spec in AUTOMATIONS:
        row = db.query(Automation).filter_by(slug=spec["slug"]).one_or_none()
        if row is None:
            db.add(Automation(**spec))
        else:
            for key, value in spec.items():
                setattr(row, key, value)
    db.commit()
