"""Separate clinic identity from each report's technical source profile.

Revision ID: e481c9a6207f
Revises: d903726fa2b1
"""

import sqlalchemy as sa
from alembic import op

revision = "e481c9a6207f"
down_revision = "d903726fa2b1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("cases", sa.Column("clinic_id", sa.String(length=50), nullable=True))
    op.execute("UPDATE cases SET clinic_id = profile_id")
    with op.batch_alter_table("cases") as batch:
        batch.alter_column("clinic_id", existing_type=sa.String(length=50), nullable=False)
        batch.create_unique_constraint("uq_cases_clinic_study", ["clinic_id", "study_uid"])

    op.add_column("source_reports", sa.Column("profile_id", sa.String(length=50), nullable=True))
    op.execute(
        "UPDATE source_reports SET profile_id = "
        "(SELECT profile_id FROM cases WHERE cases.id = source_reports.case_id)"
    )
    with op.batch_alter_table("source_reports") as batch:
        batch.alter_column("profile_id", existing_type=sa.String(length=50), nullable=False)


def downgrade():
    with op.batch_alter_table("source_reports") as batch:
        batch.drop_column("profile_id")
    with op.batch_alter_table("cases") as batch:
        batch.drop_constraint("uq_cases_clinic_study", type_="unique")
        batch.drop_column("clinic_id")
