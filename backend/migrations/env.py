"""Alembic environment: migrations run against the app's own engine and models.

Run by init_db() on every start (upgrade to head), or by hand:
    alembic revision --autogenerate -m "what changed"   # after editing models.py
    alembic upgrade head
"""
from alembic import context

from app import models  # noqa: F401  (registers every table on Base.metadata)
from app.db import Base, engine

target_metadata = Base.metadata


def run() -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:  # called from init_db with an open connection
        _migrate(connection)
        return
    with engine.connect() as conn:
        _migrate(conn)
        conn.commit()


def _migrate(connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata,
        render_as_batch=True,  # lets SQLite (tests, demo) alter tables too
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


run()
