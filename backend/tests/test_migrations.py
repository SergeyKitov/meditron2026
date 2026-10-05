import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

ROOT = Path(__file__).resolve().parents[2]


def test_migrations_round_trip(tmp_path):
    url = f"sqlite:///{tmp_path}/migration.db"
    env = {**os.environ, "DATABASE_URL": url, "PYTHONPATH": str(ROOT / "backend")}

    def migrate(*args):
        subprocess.run(
            [str(ROOT / ".venv/bin/alembic"), *args],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
        )

    migrate("upgrade", "head")
    engine = create_engine(url)
    assert {
        "cases",
        "route_versions",
        "source_reports",
        "events",
        "outbox_events",
        "bookings",
        "clinical_decisions",
        "commands",
        "step_results",
        "patient_choices",
    } <= set(inspect(engine).get_table_names())
    migrate("downgrade", "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    migrate("upgrade", "head")
    migrate("check")
    engine.dispose()


def test_pending_outbox_is_preserved_when_audit_and_queue_are_split(tmp_path):
    url = f"sqlite:///{tmp_path}/outbox-split.db"
    env = {**os.environ, "DATABASE_URL": url, "PYTHONPATH": str(ROOT / "backend")}

    def migrate(*args):
        subprocess.run(
            [str(ROOT / ".venv/bin/alembic"), *args],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
        )

    migrate("upgrade", "f732a40e9c55")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO cases (id, profile_id, clinic_id, study_uid, encounter_ref, "
                "patient_token, modality, pending_review, created_at) VALUES "
                "('case-1', 'private', 'private', 'study-1', 'encounter-1', "
                "'token-1', 'MAMMOGRAPHY', 1, '2026-10-04T00:00:00+00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO events (id, case_id, kind, payload, processed, attempts, "
                "next_attempt_at, failed_at, last_error, created_at) VALUES "
                "('queued-1', 'case-1', 'publish_route', '{\"route_id\":\"route-1\"}', "
                "0, 2, '2026-10-04T00:00:10+00:00', NULL, 'temporary', "
                "'2026-10-04T00:00:00+00:00'), "
                "('audit-1', 'case-1', 'approved', '{}', 1, 0, NULL, NULL, NULL, "
                "'2026-10-04T00:00:00+00:00')"
            )
        )
    migrate("upgrade", "head")
    with engine.connect() as connection:
        queued = connection.execute(
            text(
                "SELECT id, kind, processed, attempts, next_attempt_at, last_error "
                "FROM outbox_events"
            )
        ).one()
        assert queued == (
            "queued-1",
            "publish_route",
            0,
            2,
            "2026-10-04T00:00:10+00:00",
            "temporary",
        )
        assert connection.scalar(text("SELECT count(*) FROM events")) == 2
        assert "processed" not in {col["name"] for col in inspect(engine).get_columns("events")}
    migrate("downgrade", "f732a40e9c55")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT processed, attempts, last_error FROM events WHERE id='queued-1'")
        ).one() == (0, 2, "temporary")
    engine.dispose()


def test_reconciliation_migration_preserves_existing_booking(tmp_path):
    url = f"sqlite:///{tmp_path}/existing-booking.db"
    env = {**os.environ, "DATABASE_URL": url, "PYTHONPATH": str(ROOT / "backend")}

    def migrate(*args):
        subprocess.run(
            [str(ROOT / ".venv/bin/alembic"), *args],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
        )

    migrate("upgrade", "b5a9e760dc18")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO cases (id, profile_id, study_uid, encounter_ref, patient_token, "
                "modality, pending_review, created_at) VALUES "
                "('case-1', 'private', 'study-1', 'encounter-1', 'token-1', "
                "'MAMMOGRAPHY', 0, '2026-10-04T00:00:00+00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO source_reports (id, case_id, source_version, content_hash, "
                "source_kind, canonical, raw, created_at) VALUES "
                "('report-1', 'case-1', 1, 'hash', 'json', '{}', '{}', "
                "'2026-10-04T00:00:00+00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO route_versions (id, case_id, report_id, version, status, "
                "ruleset_version, proposed_steps, steps, trace, warnings, created_at) VALUES "
                "('route-1', 'case-1', 'report-1', 1, 'published', 'demo', "
                "'[]', '[]', '[]', '[]', '2026-10-04T00:00:00+00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO bookings (id, route_id, step_key, service_id, slot, slot_key, "
                "status, external_ref, status_reason, created_at) VALUES "
                "('booking-1', 'route-1', 'review', 'SP-01', 'tomorrow-09:00', "
                "'private:SP-01:tomorrow-09:00', 'confirmed', 'DEMO-1', NULL, "
                "'2026-10-04T00:00:00+00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO clinical_decisions (id, route_id, action, reason, original_steps, "
                "final_steps, created_at) VALUES "
                "('decision-1', 'route-1', 'approve', '', '[]', '[]', "
                "'2026-10-04T00:00:00+00:00')"
            )
        )
    migrate("upgrade", "head")
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT route_id, status, slot_key, reconciled_route_id FROM bookings")
        ).one()
        assert row == ("route-1", "confirmed", "private:SP-01:tomorrow-09:00", None)
        assert (
            connection.scalar(text("SELECT reason_code FROM clinical_decisions")) == "unspecified"
        )
        assert connection.scalar(text("SELECT clinic_id FROM cases")) == "private"
        assert connection.scalar(text("SELECT profile_id FROM source_reports")) == "private"
        assert connection.scalar(text("SELECT processing_ms FROM source_reports")) is None
    engine.dispose()


def test_audit_events_are_append_only_after_migration(tmp_path):
    url = f"sqlite:///{tmp_path}/audit-protection.db"
    env = {**os.environ, "DATABASE_URL": url, "PYTHONPATH": str(ROOT / "backend")}

    def migrate(*args):
        subprocess.run(
            [str(ROOT / ".venv/bin/alembic"), *args],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
        )

    migrate("upgrade", "head")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO cases (id, profile_id, clinic_id, study_uid, encounter_ref, "
                "patient_token, modality, pending_review, created_at) VALUES "
                "('case-1', 'private', 'private', 'study-1', 'visit-1', 'token-1', "
                "'MAMMOGRAPHY', 1, '2026-10-04T00:00:00+00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO events (id, case_id, kind, payload, created_at) VALUES "
                "('event-1', 'case-1', 'approved', '{}', '2026-10-04T00:00:00+00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO outbox_events (id, case_id, kind, payload, processed, "
                "created_at) VALUES ('event-1', 'case-1', 'publish_route', '{}', 0, "
                "'2026-10-04T00:00:00+00:00')"
            )
        )
    with pytest.raises(DBAPIError, match="events is append-only"):
        with engine.begin() as connection:
            connection.execute(text("UPDATE events SET kind='changed' WHERE id='event-1'"))
    with pytest.raises(DBAPIError, match="events is append-only"):
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM events WHERE id='event-1'"))
    with engine.begin() as connection:
        connection.execute(text("UPDATE outbox_events SET attempts=1 WHERE id='event-1'"))
        assert connection.scalar(text("SELECT attempts FROM outbox_events")) == 1
    migrate("downgrade", "a941f97c2e10")
    with engine.begin() as connection:
        connection.execute(text("UPDATE events SET kind='changed' WHERE id='event-1'"))
        assert connection.scalar(text("SELECT kind FROM events")) == "changed"
    engine.dispose()
