"""Read endpoints the dashboard needs from day one. Write/trigger endpoints
arrive with each automation in Phases 2–4."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Automation, Run
from app.schemas import AutomationDetail, AutomationOut, RunDetail, RunOut

router = APIRouter(prefix="/api", tags=["automations"])


@router.get("/automations", response_model=list[AutomationOut])
def list_automations(db: Session = Depends(get_db)):
    return db.scalars(select(Automation).order_by(Automation.id)).all()


@router.get("/automations/{slug}", response_model=AutomationDetail)
def get_automation(slug: str, db: Session = Depends(get_db)):
    automation = db.scalars(select(Automation).where(Automation.slug == slug)).one_or_none()
    if automation is None:
        raise HTTPException(404, f"Automation '{slug}' not found")
    return automation


@router.get("/runs", response_model=list[RunOut])
def list_runs(
    automation: str | None = Query(None, description="Filter by automation slug"),
    status: str | None = None,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    stmt = select(Run).order_by(Run.created_at.desc()).limit(limit)
    if automation:
        stmt = stmt.join(Automation).where(Automation.slug == automation)
    if status:
        stmt = stmt.where(Run.status == status)
    return db.scalars(stmt).all()


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: uuid.UUID, db: Session = Depends(get_db)):
    run = db.scalars(
        select(Run).options(selectinload(Run.steps)).where(Run.id == run_id)
    ).one_or_none()
    if run is None:
        raise HTTPException(404, "Run not found")
    return run
