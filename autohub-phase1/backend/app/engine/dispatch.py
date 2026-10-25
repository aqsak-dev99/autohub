"""Hands a run to the Redis worker, with a fallback.

Why a queue at all: LLM calls take seconds. Running them inside the request
would make webhooks (Twilio, n8n) time out. The API answers instantly with
the run id; the worker does the slow part.

Fallback: if Redis is down, the run executes in a FastAPI background task
instead of being lost. Slower, but the hub degrades instead of breaking.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import BackgroundTasks

from app.config import get_settings
from app.engine.executor import execute_run

log = logging.getLogger("autohub.dispatch")
QUEUE_NAME = "autohub"


def dispatch(run_id: uuid.UUID, background: BackgroundTasks) -> str:
    """Returns how the run was dispatched: 'queue' or 'background'."""
    settings = get_settings()
    if settings.run_mode == "queue":
        try:
            from redis import Redis
            from rq import Queue

            conn = Redis.from_url(settings.redis_url, socket_connect_timeout=1)
            Queue(QUEUE_NAME, connection=conn).enqueue(
                "app.engine.executor.execute_run", str(run_id), job_timeout=300
            )
            return "queue"
        except Exception as exc:
            log.warning("Redis unavailable (%s); running %s in background instead", exc, run_id)

    background.add_task(execute_run, run_id)
    return "background"
