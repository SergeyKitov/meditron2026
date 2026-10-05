"""Classify specialist corrections without exporting free-text reasons.

Revision ID: d903726fa2b1
Revises: c34f156ea997
"""

import sqlalchemy as sa
from alembic import op

revision = "d903726fa2b1"
down_revision = "c34f156ea997"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "clinical_decisions",
        sa.Column(
            "reason_code",
            sa.String(length=40),
            server_default="unspecified",
            nullable=False,
        ),
    )


def downgrade():
    op.drop_column("clinical_decisions", "reason_code")
