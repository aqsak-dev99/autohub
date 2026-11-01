"""Database engine + session handling.

`get_db` is a FastAPI dependency: each request gets its own session,
which is always closed afterwards, even if the request crashes.
"""
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

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
    """Create tables. pgvector extension is enabled first on Postgres (used for RAG in Phase 2)."""
    from app import models  # noqa: F401  (import registers the tables on Base)

    if settings.is_postgres:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)
    if settings.is_postgres:
        with engine.begin() as conn:
            for statement in SCHEMA_PATCHES:
                conn.execute(text(statement))


# create_all never changes a table that already exists. Until Alembic arrives (before deploy),
# column changes to existing tables go here. Each must be safe to run on every start.
SCHEMA_PATCHES = [
    # room for long message ids (widened from 64 when longer provider ids appeared)
    "ALTER TABLE inbound_messages ALTER COLUMN external_id TYPE varchar(128)",
]
