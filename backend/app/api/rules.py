"""The Rules page: when may the Lead Handler reply without asking the owner?

GET/PUT the rules, and POST /preview to see what last week would have looked like
under a proposed set, by replaying the routing on what each run recorded. The replay
is pure code over saved facts, so it costs nothing and runs instantly.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.automations.lead_rules import replay_route
from app.auth import require_owner
from app.config import get_settings
from app.db import get_db
from app.models import Automation, Lead, Run, RunStep
from app.rules_store import LeadRules, get_rules, save_rules

router = APIRouter(prefix="/api/rules", tags=["rules"])


@router.get("", response_model=LeadRules)
def read_rules(db: Session = Depends(get_db)):
    return get_rules(db, get_settings())


@router.put("", response_model=LeadRules, dependencies=[Depends(require_owner)])
def update_rules(body: LeadRules, db: Session = Depends(get_db)):
    return save_rules(db, body)


@router.post("/preview")
def preview_rules(body: LeadRules, days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)):
    current = get_rules(db, get_settings())
    since = datetime.now(timezone.utc) - timedelta(days=days)
    automation = db.scalar(select(Automation).where(Automation.slug == "lead_handler"))
    rows = db.execute(
        select(RunStep.run_id, RunStep.node_id, RunStep.output).join(Run)
        .where(Run.automation_id == automation.id, Run.created_at >= since,
               RunStep.node_id.in_(["classify", "score", "revise"]))
    ).all() if automation else []

    facts: dict = {}
    for run_id, node_id, output in rows:
        facts.setdefault(run_id, {})[node_id] = output or {}
    names = {lead.run_id: lead.name or lead.contact
             for lead in db.scalars(select(Lead).where(Lead.run_id.in_(list(facts)))).all()} if facts else {}

    replies = review_now = review_new = 0
    to_auto, to_review = [], []
    for run_id, f in facts.items():
        if "score" not in f:  # spam, or failed before a reply was written
            continue
        # after an automatic fix, the decision was made on the fixed reply
        decided = f["revise"] if f.get("revise", {}).get("claims") is not None else f["score"]
        replies += 1
        before = bool(replay_route(f.get("classify", {}), decided, current))
        after = replay_route(f.get("classify", {}), decided, body)
        review_now += before
        review_new += bool(after)
        who = {"name": names.get(run_id, "Customer"), "language": f.get("classify", {}).get("language"),
               "run_id": str(run_id)}
        if before and not after:
            to_auto.append(who)
        elif after and not before:
            to_review.append({**who, "reasons": after})

    return {"days": days, "replies": replies, "review_now": review_now, "review_with_rules": review_new,
            "would_send_on_its_own": to_auto, "would_ask_you": to_review}
