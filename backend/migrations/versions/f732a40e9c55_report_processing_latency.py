"""Record local report parsing and route proposal duration.

Revision ID: f732a40e9c55
Revises: e481c9a6207f
"""

import sqlalchemy as sa
from alembic import op

revision = "f732a40e9c55"
down_revision = "e481c9a6207f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("source_reports", sa.Column("processing_ms", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("source_reports", "processing_ms")
