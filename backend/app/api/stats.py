"""Numbers for the dashboard: the overview KPIs and the per-node heatmap.

Everything is computed from runs, steps, leads and approvals already in the
database, so the dashboard needs no extra tracking code.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Approval, ApprovalStatus, Automation, Lead, Run, RunStatus, RunStep, StepStatus

router = APIRouter(prefix="/api/stats", tags=["stats"])

HUMAN_NODES = {"approval"}  # their duration is a person's response time, not system latency


def _since(db: Session, days: float) -> datetime:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    return since.replace(tzinfo=None) if db.bind.dialect.name == "sqlite" else since


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@router.get("/overview")
def overview(days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)):
    since = _since(db, days)
    runs = db.scalars(select(Run).where(Run.created_at >= since)).all()
    leads = db.scalars(select(Lead).where(Lead.created_at >= since)).all()
    decided = db.scalars(select(Approval).where(Approval.decided_at.is_not(None), Approval.created_at >= since)).all()
    reviewed_runs = set(db.scalars(select(Approval.run_id).where(Approval.created_at >= since)).all())
    pending_count = len(db.scalars(select(Approval.id).where(Approval.status == ApprovalStatus.pending)).all())

    finished = [r for r in runs if r.status in (RunStatus.succeeded, RunStatus.failed)]
    succeeded = [r for r in runs if r.status == RunStatus.succeeded]
    durations = [(_aware(r.finished_at) - _aware(r.started_at)).total_seconds()
                 for r in succeeded if r.finished_at and r.started_at]
    replied = [lead for lead in leads if lead.status == "replied"]
    approved = [a for a in decided if a.status in (ApprovalStatus.approved, ApprovalStatus.edited)]

    # one bar per day, oldest first, in UTC
    today = datetime.now(timezone.utc).date()
    series = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        day_runs = [r for r in runs if _aware(r.created_at).date() == day]
        series.append({"date": day.isoformat(), "runs": len(day_runs),
                       "failed": sum(1 for r in day_runs if r.status == RunStatus.failed),
                       "cost_usd": round(sum(r.total_cost_usd for r in day_runs), 6)})

    # one row per person: someone who messages twice shows once, with their best-scoring lead
    hot, seen = [], set()
    for lead in sorted((lead for lead in leads if lead.temperature == "hot"),
                       key=lambda lead: (-(lead.score or 0), -_aware(lead.created_at).timestamp())):
        if (lead.channel, lead.contact) in seen:
            continue
        seen.add((lead.channel, lead.contact))
        hot.append(lead)
    hot = hot[:5]
    return {
        "days": days,
        "runs": len(runs),
        "succeeded": len(succeeded),
        "failed": sum(1 for r in runs if r.status == RunStatus.failed),
        "waiting": sum(1 for r in runs if r.status == RunStatus.waiting_approval),
        "success_rate": round(len(succeeded) / len(finished), 4) if finished else None,
        "median_run_seconds": round(statistics.median(durations), 2) if durations else None,
        "cost_usd": round(sum(r.total_cost_usd for r in runs), 6),
        "tokens": sum(r.total_tokens for r in runs),
        "leads": len(leads),
        "hot_leads": sum(1 for lead in leads if lead.temperature == "hot"),
        "auto_sent_rate": round(sum(1 for lead in replied if lead.run_id not in reviewed_runs) / len(replied), 4)
        if replied else None,
        # share of approved replies a person changed before sending: the AI quality signal
        "edit_rate": round(sum(1 for a in approved if a.status == ApprovalStatus.edited) / len(approved), 4)
        if approved else None,
        "pending_approvals": pending_count,
        "series": series,
        "hot": [{"id": lead.id, "name": lead.name or lead.contact, "channel": lead.channel, "score": lead.score,
                 "services": lead.services or [], "budget_band": lead.budget_band, "status": lead.status,
                 "run_id": str(lead.run_id) if lead.run_id else None} for lead in hot],
    }


@router.get("/automations/{slug}/nodes")
def node_stats(slug: str, days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)):
    """Per-node averages for the heatmap: latency, cost, failure rate, how often it runs."""
    automation = db.scalars(select(Automation).where(Automation.slug == slug)).one_or_none()
    if automation is None:
        raise HTTPException(404, f"Automation '{slug}' not found")
    since = _since(db, days)
    steps = db.execute(
        select(RunStep).join(Run).where(Run.automation_id == automation.id, Run.created_at >= since)
    ).scalars().all()
    # runs still queued haven't reached any step yet, so they'd wrongly lower every share
    total_runs = len(db.scalars(select(Run.id).where(Run.automation_id == automation.id, Run.created_at >= since,
                                                      Run.status != RunStatus.queued)).all())

    by_node: dict[str, list[RunStep]] = {}
    for step in steps:
        by_node.setdefault(step.node_id, []).append(step)

    nodes = {}
    for node_id, items in by_node.items():
        ran = [s for s in items if s.status in (StepStatus.succeeded, StepStatus.failed)]
        finished = ran
        nodes[node_id] = {
            "count": len(items),
            "share_of_runs": round(len(items) / total_runs, 4) if total_runs else 0,
            "avg_ms": round(statistics.mean(s.duration_ms for s in ran)) if ran else None,
            "avg_cost_usd": round(statistics.mean(s.cost_usd for s in ran), 8) if ran else None,
            "failure_rate": round(sum(1 for s in finished if s.status == StepStatus.failed) / len(finished), 4)
            if finished else None,
            "avg_tokens": round(statistics.mean(s.prompt_tokens + s.completion_tokens for s in ran)) if ran else None,
            "human": node_id in HUMAN_NODES,
        }
    return {"automation": slug, "days": days, "runs": total_runs, "nodes": nodes}


@router.get("/live")
def live(db: Session = Depends(get_db)):
    """What the Lead Handler is doing right now, for the home screen's live flow.

    `active`: messages in progress and the step each one is on. `today`: what happened
    since midnight UTC, split by how each reply left (on its own / after asking the owner)."""
    automation = db.scalar(select(Automation).where(Automation.slug == "lead_handler"))
    if automation is None:
        raise HTTPException(404, "lead_handler is not registered")
    recent = _since(db, 1 / 24)  # a run stuck longer than an hour isn't "live", it's a failure to look at
    runs = db.scalars(select(Run).where(Run.automation_id == automation.id, Run.created_at >= recent,
                                        Run.status.in_([RunStatus.queued, RunStatus.running]))).all()
    active = []
    for run in runs:
        last = max(run.steps, key=lambda s: s.position, default=None)
        payload = run.input or {}
        active.append({"run_id": str(run.id), "name": payload.get("name") or "Someone",
                       "channel": payload.get("channel"), "node_id": last.node_id if last else "intake",
                       "status": run.status.value})

    midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if db.bind.dialect.name == "sqlite":
        midnight = midnight.replace(tzinfo=None)
    leads = db.scalars(select(Lead).where(Lead.created_at >= midnight)).all()
    held_runs = set(db.scalars(select(Approval.run_id).where(Approval.created_at >= midnight)).all())
    replied = [lead for lead in leads if lead.status == "replied"]
    return {
        "active": active,
        "today": {
            "received": len(leads),
            "sent_on_its_own": sum(1 for lead in replied if lead.run_id not in held_runs),
            "asked_you": len(held_runs),
            "spam": sum(1 for lead in leads if lead.status == "spam"),
        },
    }
