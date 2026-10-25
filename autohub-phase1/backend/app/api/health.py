"""Health check: reports each dependency separately, so when something breaks
on Render you can see *which* part is down instead of a bare 500."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.schemas import HealthOut

router = APIRouter(tags=["health"])


def _check_redis(url: str) -> str:
    try:
        import redis

        redis.Redis.from_url(url, socket_connect_timeout=1).ping()
        return "ok"
    except Exception:
        return "unavailable"


@router.get("/health", response_model=HealthOut)
def health(db: Session = Depends(get_db)) -> HealthOut:
    settings = get_settings()
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "unavailable"

    redis_status = _check_redis(settings.redis_url)
    # Redis only powers background jobs, so the API is "degraded", not "down", without it
    overall = "ok" if database == "ok" and redis_status == "ok" else (
        "degraded" if database == "ok" else "down"
    )
    return HealthOut(status=overall, database=database, redis=redis_status, env=settings.app_env)
