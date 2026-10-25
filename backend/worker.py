"""Background worker: pulls runs off the Redis queue and executes them.

Started by docker-compose as its own container. It imports the automations
once at startup, so after changing automation code: `docker compose restart worker`.
"""
import logging

from redis import Redis
from rq import Queue, Worker

import app.automations  # noqa: F401  (registers implementations in this process)
from app.config import get_settings
from app.engine.dispatch import QUEUE_NAME

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

if __name__ == "__main__":
    conn = Redis.from_url(get_settings().redis_url)
    Worker([Queue(QUEUE_NAME, connection=conn)], connection=conn).work(with_scheduler=False)
