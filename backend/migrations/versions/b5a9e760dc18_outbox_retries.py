"""Track outbox retries and terminal failures.

Revision ID: b5a9e760dc18
Revises: a7d945e0102b
"""

import sqlalchemy as sa
from alembic import op

revision = "b5a9e760dc18"
down_revision = "a7d945e0102b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("attempts", sa.Integer(), server_default="0", nullable=False))
    op.add_column("events", sa.Column("next_attempt_at", sa.String(length=40), nullable=True))
    op.add_column("events", sa.Column("failed_at", sa.String(length=40), nullable=True))
    op.add_column("events", sa.Column("last_error", sa.String(length=100), nullable=True))


def downgrade():
    op.drop_column("events", "last_error")
    op.drop_column("events", "failed_at")
    op.drop_column("events", "next_attempt_at")
    op.drop_column("events", "attempts")
