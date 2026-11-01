"""Trigger a run of any automation. Returns 202 immediately with the run id;
poll GET /api/runs/{id} (or watch the dashboard) to see it progress."""
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.auth import require_owner
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.engine.dispatch import dispatch
from app.engine.executor import AutomationNotFound, RetryRefused, create_run, reset_for_retry
from app.models import Run, RunStatus
from app.schemas import RunOut

router = APIRouter(prefix="/api", tags=["runs"])


class TriggerIn(BaseModel):
    input: dict = {}


class TriggerOut(RunOut):
    dispatched_via: str


@router.post("/automations/{slug}/runs", response_model=TriggerOut, status_code=202,
             dependencies=[Depends(require_owner)])
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


@router.post("/runs/{run_id}/retry", response_model=TriggerOut, status_code=202,
             dependencies=[Depends(require_owner)])
def retry_run(run_id: uuid.UUID, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Run a failed run again with the same input, e.g. after a rate limit."""
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    if run.status != RunStatus.failed:
        raise HTTPException(409, f"Only failed runs can be retried (this one is {run.status.value})")
    try:
        reset_for_retry(db, run)
    except RetryRefused as exc:
        raise HTTPException(409, str(exc))
    via = dispatch(run.id, background)
    return TriggerOut(**RunOut.model_validate(run).model_dump(), dispatched_via=via)
