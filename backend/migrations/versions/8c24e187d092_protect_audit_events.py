"""Prevent accidental updates or deletes of the audit event journal.

Revision ID: 8c24e187d092
Revises: a941f97c2e10
"""

from alembic import op

revision = "8c24e187d092"
down_revision = "a941f97c2e10"
branch_labels = None
depends_on = None


def upgrade():
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            "CREATE TRIGGER trg_events_no_update BEFORE UPDATE ON events "
            "BEGIN SELECT RAISE(ABORT, 'events is append-only'); END"
        )
        op.execute(
            "CREATE TRIGGER trg_events_no_delete BEFORE DELETE ON events "
            "BEGIN SELECT RAISE(ABORT, 'events is append-only'); END"
        )
    elif dialect == "postgresql":
        op.execute(
            "CREATE FUNCTION prevent_events_mutation() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN "
            "RAISE EXCEPTION 'events is append-only'; "
            "END; $$"
        )
        op.execute(
            "CREATE TRIGGER trg_events_no_mutation "
            "BEFORE UPDATE OR DELETE ON events "
            "FOR EACH ROW EXECUTE FUNCTION prevent_events_mutation()"
        )
    else:
        raise RuntimeError(f"Unsupported database for audit protection: {dialect}")


def downgrade():
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER trg_events_no_delete")
        op.execute("DROP TRIGGER trg_events_no_update")
    elif dialect == "postgresql":
        op.execute("DROP TRIGGER trg_events_no_mutation ON events")
        op.execute("DROP FUNCTION prevent_events_mutation()")
    else:
        raise RuntimeError(f"Unsupported database for audit protection: {dialect}")
