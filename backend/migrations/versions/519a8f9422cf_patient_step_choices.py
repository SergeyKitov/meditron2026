"""Track a patient's decision on each published route step.

Revision ID: 519a8f9422cf
Revises: 8c24e187d092
"""

import sqlalchemy as sa
from alembic import op

revision = "519a8f9422cf"
down_revision = "8c24e187d092"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "patient_choices",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "route_id", sa.String(length=36), sa.ForeignKey("route_versions.id"), nullable=False
        ),
        sa.Column("step_key", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason_code", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("updated_at", sa.String(length=40), nullable=False),
        sa.UniqueConstraint("route_id", "step_key"),
    )
    op.create_index("ix_patient_choices_route_id", "patient_choices", ["route_id"])


def downgrade():
    op.drop_index("ix_patient_choices_route_id", table_name="patient_choices")
    op.drop_table("patient_choices")
