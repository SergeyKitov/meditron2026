"""store booking feedback reason

Revision ID: a7d945e0102b
Revises: d69981b76ed6
"""

import sqlalchemy as sa
from alembic import op

revision = "a7d945e0102b"
down_revision = "d69981b76ed6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("bookings", sa.Column("status_reason", sa.String(length=500), nullable=True))


def downgrade():
    op.drop_column("bookings", "status_reason")
