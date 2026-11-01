"""follow-up nudge: when a lead was replied to, and its one follow-up

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-02
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("leads") as batch:
        batch.add_column(sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("followed_up_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("follow_up_reply", sa.Text(), nullable=True))
    # leads replied to before this column existed: their last update is the best guess
    op.execute("UPDATE leads SET replied_at = updated_at WHERE replied = true AND replied_at IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("leads") as batch:
        batch.drop_column("follow_up_reply")
        batch.drop_column("followed_up_at")
        batch.drop_column("replied_at")
