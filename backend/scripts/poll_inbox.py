"""Check the AutoHub inbox once, by hand (n8n normally does this every minute).

    docker compose exec api python scripts/poll_inbox.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import BackgroundTasks  # noqa: E402

import app.automations  # noqa: E402,F401
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.email_inbox import poll_inbox  # noqa: E402

if __name__ == "__main__":
    background = BackgroundTasks()
    with SessionLocal() as db:
        result = poll_inbox(db, background, get_settings())
    print(json.dumps(result.__dict__, indent=2))
    if background.tasks:
        print("(Redis unavailable: runs were queued as background tasks and won't run from this script)")
