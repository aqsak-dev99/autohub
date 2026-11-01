"""Hands work to the Redis worker, with a fallback.

Why a queue at all: LLM calls take seconds. Running them inside the request
would make callers (the website form, n8n, the inbox poll) time out. The API answers
instantly; the worker does the slow part.

Fallback: if Redis is down, the job runs in a FastAPI background task
instead of being lost. Slower, but the hub degrades instead of breaking.
"""
from __future__ import annotations

import importlib
import logging
import uuid

from fastapi import BackgroundTasks

from app.config import get_settings

log = logging.getLogger("autohub.dispatch")
QUEUE_NAME = "autohub"


def _enqueue_or_background(func_path: str, args: tuple, background: BackgroundTasks) -> str:
    settings = get_settings()
    if settings.run_mode == "queue":
        try:
            from redis import Redis
            from rq import Queue

            conn = Redis.from_url(settings.redis_url, socket_connect_timeout=1)
            Queue(QUEUE_NAME, connection=conn).enqueue(func_path, *args, job_timeout=300)
            return "queue"
        except Exception as exc:
            log.warning("Redis unavailable (%s); running %s in background instead", exc, func_path)

    module_name, func_name = func_path.rsplit(".", 1)
    background.add_task(getattr(importlib.import_module(module_name), func_name), *args)
    return "background"


def dispatch(run_id: uuid.UUID, background: BackgroundTasks) -> str:
    """Start a new run. Returns 'queue' or 'background'."""
    return _enqueue_or_background("app.engine.executor.execute_run", (str(run_id),), background)


def dispatch_resume(run_id: uuid.UUID, approval_id: int, background: BackgroundTasks) -> str:
    """Continue a run after a human decision."""
    return _enqueue_or_background("app.engine.executor.resume_run", (str(run_id), approval_id), background)
