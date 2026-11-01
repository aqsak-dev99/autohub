"""Creates runs and executes them. The Redis worker calls `execute_run` and `resume_run`.

Run lifecycle:  queued → running → succeeded
                                 → failed            (any unhandled error)
                                 → waiting_approval  (automation raised NeedsApproval)
                                        → running → succeeded / failed   (after the human decides)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.engine.base import NeedsApproval, get_implementation
from app.engine.context import RunContext, _jsonable
from app.llm.client import LLMClient, get_llm
from app.models import Approval, ApprovalStatus, Automation, Run, RunStatus, StepStatus

log = logging.getLogger("autohub.engine")


class AutomationNotFound(Exception):
    pass


class RetryRefused(Exception):
    """The run already did something that can't be undone (e.g. sent the reply)."""


def create_run(db: Session, slug: str, payload: dict) -> Run:
    automation = db.scalars(select(Automation).where(Automation.slug == slug)).one_or_none()
    if automation is None or not automation.enabled:
        raise AutomationNotFound(slug)
    run = Run(automation_id=automation.id, status=RunStatus.queued, input=payload)
    db.add(run)
    db.commit()
    return run


def claim(db: Session, model, row_id, from_status, **values) -> bool:
    """Move a row out of `from_status` in one conditional UPDATE, and say whether *we* did it.

    Reading the status and then writing it is two steps, so two workers (or two clicks) can both
    read "queued" and both carry on. `UPDATE ... WHERE id = ? AND status = ?` is one step: the
    database lets exactly one caller change the row, and the rest see 0 rows affected.
    """
    result = db.execute(update(model).where(model.id == row_id, model.status == from_status).values(**values)
                        .execution_options(synchronize_session=False))
    db.commit()
    return result.rowcount == 1


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
        # claim the run first: if the same job is delivered twice, only one delivery gets past this
        if not claim(db, Run, run_id, RunStatus.queued, status=RunStatus.running,
                     started_at=datetime.now(timezone.utc)):
            run = db.get(Run, run_id)
            if run is None:
                log.error("run %s not found", run_id)
                return "missing"
            log.warning("run %s already %s, skipping", run_id, run.status)
            return run.status.value
        run = db.get(Run, run_id)

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
        if approval.status == ApprovalStatus.pending:
            return "not_decided"
        # same claim as execute_run: a resume delivered twice must not send the reply twice
        if not claim(db, Run, run_id, RunStatus.waiting_approval, status=RunStatus.running):
            db.refresh(run)
            log.warning("resume: run %s is %s, not waiting", run_id, run.status)
            return run.status.value
        db.refresh(run)

        impl = get_implementation(run.automation.slug)
        ctx = RunContext(db, run, llm or get_llm())
        return _finish(db, run, lambda: impl.resume(ctx, run.input or {}, approval),
                       on_failure=lambda exc: impl.on_failure(ctx, exc))


def reset_for_retry(db: Session, run: Run) -> None:
    """Put a failed run back in the queue, keeping a record of the attempt that failed.

    Refused when the run already got past an irreversible step: if the reply was sent and only
    saving the lead failed, starting again would email the customer a second time.
    """
    impl = get_implementation(run.automation.slug)
    done = {s.node_id for s in run.steps if s.status == StepStatus.succeeded}
    already = sorted(done & (impl.irreversible_steps if impl else frozenset()))
    if already:
        raise RetryRefused(f"This run already completed '{already[0]}', so running it again would repeat it. "
                           "Fix the problem by hand instead.")

    output = run.output or {}
    attempts = list(output.get("previous_attempts", []))
    attempts.append({
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "cost_usd": run.total_cost_usd,
        "steps": [{"node_id": s.node_id, "status": s.status.value, "error": s.error, "attempts": s.attempts,
                   "model": s.model, "duration_ms": s.duration_ms, "cost_usd": s.cost_usd} for s in run.steps],
    })
    # the steps table holds the current attempt (what the run graph shows); earlier ones live in the output
    run.steps.clear()
    run.status = RunStatus.queued
    run.error = None
    run.output = {"previous_errors": [a["error"] for a in attempts if a["error"]], "previous_attempts": attempts}
    run.total_tokens = 0
    run.total_cost_usd = 0.0
    run.started_at = None
    run.finished_at = None
    db.commit()


INTERRUPTED = "Interrupted: the server stopped while this run was in progress"


def recover_interrupted(db: Session, older_than_minutes: int = 10) -> int:
    """Mark runs stuck in `running` as failed. Called on startup.

    A run executes inside one process. If that process dies mid-run (a deploy, a crash, the free
    plan putting the server to sleep), nothing would ever finish it: the run would say "running"
    forever and its lead would sit half done. Runs started recently are left alone, in case a
    separate worker is still busy with them; jobs time out after 5 minutes, so 10 is safe.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
    if db.bind.dialect.name == "sqlite":
        cutoff = cutoff.replace(tzinfo=None)  # SQLite stores naive timestamps
    stuck = db.scalars(select(Run).where(Run.status == RunStatus.running, Run.started_at < cutoff)).all()
    now = datetime.now(timezone.utc)
    for run in stuck:
        for step in run.steps:
            if step.status == StepStatus.running:
                step.status, step.error, step.finished_at = StepStatus.failed, INTERRUPTED, now
        run.status, run.error, run.finished_at = RunStatus.failed, INTERRUPTED, now
        impl = get_implementation(run.automation.slug)
        if impl is not None:
            try:
                impl.on_failure(RunContext(db, run, get_llm()), RuntimeError(INTERRUPTED))
            except Exception:
                log.exception("on_failure hook for interrupted run %s failed", run.id)
        log.warning("run %s was interrupted; marked failed", run.id)
    db.commit()
    return len(stuck)
