"""Creates runs and executes them. The Redis worker calls `execute_run` and `resume_run`.

Run lifecycle:  queued → running → succeeded
                                 → failed            (any unhandled error)
                                 → waiting_approval  (automation raised NeedsApproval)
                                        → running → succeeded / failed   (after the human decides)
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
from app.models import Approval, ApprovalStatus, Automation, Run, RunStatus

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


def _finish(db: Session, run: Run, work, on_failure=None) -> str:
    """Run `work()` and record its outcome on the run. Shared by execute and resume."""
    try:
        result = work()
        run.output = {**(run.output or {}), **(_jsonable(result) or {})}
        run.status = RunStatus.succeeded
    except NeedsApproval as pause:
        db.add(Approval(run_id=run.id, kind=pause.kind, reason=pause.reason, payload=_jsonable(pause.payload)))
        run.output = _jsonable(pause.output)
        run.status = RunStatus.waiting_approval
    except Exception as exc:
        log.exception("run %s failed", run.id)
        run.status = RunStatus.failed
        run.error = f"{type(exc).__name__}: {exc}"[:2000]
        if on_failure is not None:
            try:
                on_failure(exc)
            except Exception:  # tidy-up must never hide the original error
                log.exception("on_failure hook for run %s failed", run.id)

    if run.status != RunStatus.waiting_approval:
        run.finished_at = datetime.now(timezone.utc)
    db.commit()
    return run.status.value


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

        def work():
            if impl is None:
                raise NotImplementedError(f"'{run.automation.slug}' has no implementation yet")
            return impl.run(ctx, run.input or {})

        return _finish(db, run, work, on_failure=(lambda exc: impl.on_failure(ctx, exc)) if impl else None)


def resume_run(run_id: str | uuid.UUID, approval_id: int, llm: LLMClient | None = None) -> str:
    """Continue a paused run after its approval was decided. Same never-raise contract."""
    run_id = uuid.UUID(str(run_id))
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        approval = db.get(Approval, approval_id)
        if run is None or approval is None or approval.run_id != run.id:
            log.error("resume: run %s / approval %s not found", run_id, approval_id)
            return "missing"
        if run.status != RunStatus.waiting_approval:
            log.warning("resume: run %s is %s, not waiting", run_id, run.status)
            return run.status.value
        if approval.status == ApprovalStatus.pending:
            return "not_decided"

        run.status = RunStatus.running
        db.commit()

        impl = get_implementation(run.automation.slug)
        ctx = RunContext(db, run, llm or get_llm())
        return _finish(db, run, lambda: impl.resume(ctx, run.input or {}, approval),
                       on_failure=lambda exc: impl.on_failure(ctx, exc))


def reset_for_retry(db: Session, run: Run) -> None:
    """Put a failed run back in the queue. Its old steps are cleared; the error is kept in the output."""
    history = list((run.output or {}).get("previous_errors", []))
    if run.error:
        history.append(run.error)
    run.steps.clear()
    run.status = RunStatus.queued
    run.error = None
    run.output = {"previous_errors": history}
    run.total_tokens = 0
    run.total_cost_usd = 0.0
    run.started_at = None
    run.finished_at = None
    db.commit()
