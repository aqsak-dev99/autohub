"""Creates runs and executes them. `execute_run` is what the Redis worker calls.

Run lifecycle:  queued → running → succeeded
                                 → failed            (any unhandled error)
                                 → waiting_approval  (automation raised NeedsApproval)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.engine.base import NeedsApproval, get_implementation
from app.engine.context import RunContext, _jsonable
from app.llm.client import LLMClient, get_llm
from app.models import Approval, Automation, Run, RunStatus

log = logging.getLogger("autohub.engine")


class AutomationNotFound(Exception):
    pass


def create_run(db: Session, slug: str, payload: dict) -> Run:
    automation = db.scalars(select(Automation).where(Automation.slug == slug)).one_or_none()
    if automation is None or not automation.enabled:
        raise AutomationNotFound(slug)
    run = Run(automation_id=automation.id, status=RunStatus.queued, input=payload)
    db.add(run)
    db.commit()
    return run


def execute_run(run_id: str | uuid.UUID, llm: LLMClient | None = None) -> str:
    """Run one automation end to end. Never raises: every outcome is saved on the Run."""
    run_id = uuid.UUID(str(run_id))
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        if run is None:
            log.error("run %s not found", run_id)
            return "missing"
        if run.status != RunStatus.queued:
            # protects against the same job being delivered twice
            log.warning("run %s already %s, skipping", run_id, run.status)
            return run.status.value

        run.status = RunStatus.running
        run.started_at = datetime.now(timezone.utc)
        db.commit()

        impl = get_implementation(run.automation.slug)
        ctx = RunContext(db, run, llm or get_llm())
        try:
            if impl is None:
                raise NotImplementedError(f"'{run.automation.slug}' has no implementation yet")
            run.output = _jsonable(impl.run(ctx, run.input or {}))
            run.status = RunStatus.succeeded
        except NeedsApproval as pause:
            db.add(Approval(run_id=run.id, kind=pause.kind, reason=pause.reason,
                            payload=_jsonable(pause.payload)))
            run.output = _jsonable(pause.output)
            run.status = RunStatus.waiting_approval
        except Exception as exc:
            log.exception("run %s failed", run_id)
            run.status = RunStatus.failed
            run.error = f"{type(exc).__name__}: {exc}"[:2000]

        if run.status != RunStatus.waiting_approval:
            run.finished_at = datetime.now(timezone.utc)
        db.commit()
        return run.status.value
