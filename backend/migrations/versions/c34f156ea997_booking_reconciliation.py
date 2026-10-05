"""Preserve original booking route when a specialist carries it forward.

Revision ID: c34f156ea997
Revises: b5a9e760dc18
"""

import sqlalchemy as sa
from alembic import op

revision = "c34f156ea997"
down_revision = "b5a9e760dc18"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("bookings") as batch:
        batch.add_column(sa.Column("reconciled_route_id", sa.String(length=36), nullable=True))
        batch.create_index("ix_bookings_reconciled_route_id", ["reconciled_route_id"])
        batch.create_foreign_key(
            "fk_bookings_reconciled_route_id_route_versions",
            "route_versions",
            ["reconciled_route_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("bookings") as batch:
        batch.drop_constraint("fk_bookings_reconciled_route_id_route_versions", type_="foreignkey")
        batch.drop_index("ix_bookings_reconciled_route_id")
        batch.drop_column("reconciled_route_id")
