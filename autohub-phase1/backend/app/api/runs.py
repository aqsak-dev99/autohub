"""Trigger a run of any automation. Returns 202 immediately with the run id;
poll GET /api/runs/{id} (or watch the dashboard) to see it progress."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.engine.dispatch import dispatch
from app.engine.executor import AutomationNotFound, create_run
from app.schemas import RunOut

router = APIRouter(prefix="/api", tags=["runs"])


class TriggerIn(BaseModel):
    input: dict = {}


class TriggerOut(RunOut):
    dispatched_via: str


@router.post("/automations/{slug}/runs", response_model=TriggerOut, status_code=202)
def trigger_run(
    slug: str,
    body: TriggerIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        run = create_run(db, slug, body.input)
    except AutomationNotFound:
        raise HTTPException(404, f"Automation '{slug}' not found or disabled")
    via = dispatch(run.id, background)
    return TriggerOut(**RunOut.model_validate(run).model_dump(), dispatched_via=via)
