"""Migrations: the schema Alembic builds must match the models exactly."""
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app import models  # noqa: F401
from app.db import Base, engine, init_db


def test_migrations_match_the_models():
    init_db()
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    # a difference means someone changed models.py without adding a migration
    assert diff == [], diff
