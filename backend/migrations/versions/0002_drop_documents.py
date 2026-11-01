"""drop the retired documents table

The Document Extractor was dropped before it was built (decision 60). Databases created
before migrations existed still have its empty table; new ones never had it.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-02
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS documents")


def downgrade() -> None:
    pass  # nothing to restore: the table never held data
