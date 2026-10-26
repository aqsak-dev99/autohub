"""Step tracing: the heart of the run engine.

`ctx.step("classify", input)` is a context manager. On enter it writes a
RunStep row with status `running` (so the dashboard sees live progress).
On exit it records output, duration, tokens and cost, or the error if the
block raised, then rolls the totals up onto the Run.

LLM calls go through the step handle (`s.llm_json(...)`), so token usage
lands on the step that spent it, with no bookkeeping in automation code.
"""
from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.engine.base import NeedsApproval
from app.llm.client import LLMClient, LLMResult
from app.models import Run, RunStep, StepStatus


def _jsonable(value: Any) -> Any:
    """Steps store JSON. Pydantic models and odd types are converted safely."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


class StepHandle:
    """What `with ctx.step(...) as s` gives you."""

    def __init__(self, step: RunStep, llm: LLMClient):
        self._step = step
        self._llm = llm
        self.output: Any = None
        self.skipped = False

    def _record(self, result: LLMResult) -> LLMResult:
        s = self._step
        s.model = result.model
        s.prompt_tokens += result.prompt_tokens
        s.completion_tokens += result.completion_tokens
        s.cost_usd = round(s.cost_usd + result.cost_usd, 8)
        s.attempts = max(s.attempts, result.attempts)
        return result

    def llm(self, messages: list[dict], **kwargs) -> LLMResult:
        return self._record(self._llm.complete(messages, **kwargs))

    def llm_json(self, messages: list[dict], schema: type[BaseModel], **kwargs) -> LLMResult:
        return self._record(self._llm.complete_json(messages, schema, **kwargs))

    def skip(self, reason: str) -> None:
        """Mark a branch that didn't run (e.g. 'auto-send' when the reply went to approval)."""
        self.skipped = True
        self.output = {"skipped": reason}


class RunContext:
    def __init__(self, db: Session, run: Run, llm: LLMClient):
        self.db = db
        self.run = run
        self.llm = llm
        self._position = len(run.steps)

    @contextmanager
    def step(self, node_id: str, input: Any = None) -> Iterator[StepHandle]:
        step = RunStep(
            run_id=self.run.id,
            node_id=node_id,
            position=self._position,
            status=StepStatus.running,
            input=_jsonable(input),
        )
        self._position += 1
        self.db.add(step)
        self.db.commit()  # visible immediately, so the dashboard can show "running"

        handle = StepHandle(step, self.llm)
        started = time.perf_counter()
        try:
            yield handle
            step.status = StepStatus.skipped if handle.skipped else StepStatus.succeeded
            step.output = _jsonable(handle.output)
        except NeedsApproval:
            # pausing for a human is a normal outcome of this step, not a failure
            step.status = StepStatus.waiting
            step.output = _jsonable(handle.output)
            raise
        except Exception as exc:
            step.status = StepStatus.failed
            step.error = f"{type(exc).__name__}: {exc}"[:2000]
            raise
        finally:
            step.duration_ms = int((time.perf_counter() - started) * 1000)
            # a waiting step isn't finished: finish_waiting_step closes it after the human decides
            step.finished_at = None if step.status == StepStatus.waiting else datetime.now(timezone.utc)
            self.run.total_tokens += step.prompt_tokens + step.completion_tokens
            self.run.total_cost_usd = round(self.run.total_cost_usd + step.cost_usd, 8)
            self.db.commit()

    def finish_waiting_step(self, node_id: str, output: Any) -> None:
        """Close the step a run paused on, once the human has decided.

        Its duration becomes the human's response time, which the dashboard
        shows separately from system latency.
        """
        step = next((s for s in self.run.steps if s.node_id == node_id and s.status == StepStatus.waiting), None)
        if step is None:
            return
        now = datetime.now(timezone.utc)
        started = step.started_at if step.started_at.tzinfo else step.started_at.replace(tzinfo=timezone.utc)
        step.status = StepStatus.succeeded
        step.output = {**(step.output or {}), **_jsonable(output)}
        step.finished_at = now
        step.duration_ms = int((now - started).total_seconds() * 1000)
        self.db.commit()
