"""Move mutable delivery state out of the audit events table.

Revision ID: a941f97c2e10
Revises: f732a40e9c55
"""

import sqlalchemy as sa
from alembic import op

revision = "a941f97c2e10"
down_revision = "f732a40e9c55"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.String(length=40), nullable=True),
        sa.Column("failed_at", sa.String(length=40), nullable=True),
        sa.Column("last_error", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["id"], ["events.id"]),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbox_events_case_id", "outbox_events", ["case_id"])
    op.execute(
        "INSERT INTO outbox_events "
        "(id, case_id, kind, payload, processed, attempts, next_attempt_at, failed_at, last_error, created_at) "
        "SELECT id, case_id, kind, payload, processed, attempts, next_attempt_at, failed_at, last_error, created_at "
        "FROM events WHERE processed = false"
    )
    op.drop_column("events", "last_error")
    op.drop_column("events", "failed_at")
    op.drop_column("events", "next_attempt_at")
    op.drop_column("events", "attempts")
    op.drop_column("events", "processed")


def downgrade():
    op.add_column(
        "events", sa.Column("processed", sa.Boolean(), server_default=sa.true(), nullable=False)
    )
    op.add_column("events", sa.Column("attempts", sa.Integer(), server_default="0", nullable=False))
    op.add_column("events", sa.Column("next_attempt_at", sa.String(length=40), nullable=True))
    op.add_column("events", sa.Column("failed_at", sa.String(length=40), nullable=True))
    op.add_column("events", sa.Column("last_error", sa.String(length=100), nullable=True))
    op.execute(
        "UPDATE events SET "
        "processed = (SELECT processed FROM outbox_events WHERE outbox_events.id = events.id), "
        "attempts = (SELECT attempts FROM outbox_events WHERE outbox_events.id = events.id), "
        "next_attempt_at = (SELECT next_attempt_at FROM outbox_events WHERE outbox_events.id = events.id), "
        "failed_at = (SELECT failed_at FROM outbox_events WHERE outbox_events.id = events.id), "
        "last_error = (SELECT last_error FROM outbox_events WHERE outbox_events.id = events.id) "
        "WHERE id IN (SELECT id FROM outbox_events)"
    )
    op.drop_index("ix_outbox_events_case_id", table_name="outbox_events")
    op.drop_table("outbox_events")
