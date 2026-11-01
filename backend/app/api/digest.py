"""Preview the daily digest without the AI or sending anything: the numbers, and today's
tasks in code's own order. Handy for the dashboard and for checking the numbers."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.automations.daily_digest import collect_stats, format_digest, pick_priorities, todo_candidates
from app.db import get_db

router = APIRouter(prefix="/api/digest", tags=["digest"])


@router.get("/preview")
def preview(hours: int = Query(24, ge=1, le=168), db: Session = Depends(get_db)):
    stats = collect_stats(db, hours)
    todo = pick_priorities(todo_candidates(db), None)
    return {"stats": stats, "todo": todo, "text": format_digest(stats, todo, datetime.now(timezone.utc))}
