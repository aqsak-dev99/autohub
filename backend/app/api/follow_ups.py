"""The Follow-up Nudge's trigger. n8n calls the scan once a day; the dashboard can preview it."""
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.api.leads import require_inbound_key
from app.auth import require_owner
from app.automations.follow_up import days_between, due_leads_query
from app.config import get_settings
from app.db import get_db
from app.intake import start_once

router = APIRouter(prefix="/api/follow-ups", tags=["follow-ups"])

MAX_PER_SCAN = 20  # a soft cap, so a backlog doesn't send a burst of emails at once


@router.get("/due")
def due(db: Session = Depends(get_db)):
    """Which leads would get a follow-up if the scan ran now (nothing is started)."""
    now = datetime.now(timezone.utc)
    leads = db.scalars(due_leads_query(db, get_settings(), now)).all()
    return [{"lead_id": lead.id, "name": lead.name, "contact": lead.contact, "temperature": lead.temperature,
             "language": lead.language, "days_quiet": days_between(lead.replied_at, now)} for lead in leads]


@router.post("/scan", dependencies=[Depends(require_inbound_key), Depends(require_owner)])
def scan(background: BackgroundTasks, db: Session = Depends(get_db)):
    """Start one Follow-up Nudge run per quiet lead. Safe to call twice: each lead is claimed once."""
    leads = db.scalars(due_leads_query(db, get_settings()).limit(MAX_PER_SCAN)).all()
    started = [lead.id for lead in leads
               if start_once(db, background, slug="follow_up", provider="follow_up",
                             external_id=f"follow_up:{lead.id}", payload={"lead_id": lead.id})]
    return {"due": len(leads), "started": len(started), "lead_ids": started}
