"""Database engine + session handling.

`get_db` is a FastAPI dependency: each request gets its own session,
which is always closed afterwards, even if the request crashes.
"""
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()
_BACKEND_DIR = Path(__file__).resolve().parent.parent  # where alembic.ini lives

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # drop dead connections (Render restarts DBs sometimes)
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Bring the database schema up to date with Alembic migrations (safe on every start).

    A database created before migrations existed (by the old create_all) is "stamped" as the
    first migration once, after creating anything it's missing, and then upgraded like any other.
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    from app import models  # noqa: F401  (import registers the tables on Base)

    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        tables = set(inspect(conn).get_table_names())
        if "alembic_version" not in tables and "runs" in tables:
            Base.metadata.create_all(bind=conn)
            command.stamp(config, "0001")
        command.upgrade(config, "head")
