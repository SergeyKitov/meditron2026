"""Link route cycles and record preparation result readiness.

Revision ID: 6e5eafc72d21
Revises: 519a8f9422cf
"""

import sqlalchemy as sa
from alembic import op

revision = "6e5eafc72d21"
down_revision = "519a8f9422cf"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("route_versions") as batch:
        batch.add_column(sa.Column("parent_route_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("trigger_result_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_route_versions_parent_route_id", "route_versions", ["parent_route_id"], ["id"]
        )
        batch.create_foreign_key(
            "fk_route_versions_trigger_result_id", "step_results", ["trigger_result_id"], ["id"]
        )
    op.create_table(
        "prerequisite_results",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "route_id", sa.String(length=36), sa.ForeignKey("route_versions.id"), nullable=False
        ),
        sa.Column("booking_id", sa.String(length=36), sa.ForeignKey("bookings.id"), nullable=False),
        sa.Column("requirement_key", sa.String(length=50), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("valid_until", sa.String(length=40), nullable=True),
        sa.Column("source_ref", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.String(length=40), nullable=False),
    )
    op.create_index("ix_prerequisite_results_route_id", "prerequisite_results", ["route_id"])
    op.create_index("ix_prerequisite_results_booking_id", "prerequisite_results", ["booking_id"])


def downgrade():
    op.drop_index("ix_prerequisite_results_booking_id", table_name="prerequisite_results")
    op.drop_index("ix_prerequisite_results_route_id", table_name="prerequisite_results")
    op.drop_table("prerequisite_results")
    with op.batch_alter_table("route_versions") as batch:
        batch.drop_constraint("fk_route_versions_trigger_result_id", type_="foreignkey")
        batch.drop_constraint("fk_route_versions_parent_route_id", type_="foreignkey")
        batch.drop_column("trigger_result_id")
        batch.drop_column("parent_route_id")
