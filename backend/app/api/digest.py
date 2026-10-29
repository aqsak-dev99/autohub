"""Preview the daily digest without the LLM line or sending anything: handy for
the dashboard and for checking the numbers."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.automations.daily_digest import collect_stats, format_digest
from app.db import get_db

router = APIRouter(prefix="/api/digest", tags=["digest"])


@router.get("/preview")
def preview(hours: int = Query(24, ge=1, le=168), db: Session = Depends(get_db)):
    stats = collect_stats(db, hours)
    return {"stats": stats, "text": format_digest(stats, None, datetime.now(timezone.utc))}
