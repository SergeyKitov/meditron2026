from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from time import sleep
from types import SimpleNamespace

from app.adapters.reports import from_json, profile_with_rules
from app.adapters.synthetic import make_json
from app.application import service
from app.persistence.db import database
from app.persistence.models import Base, Case, Command, Report, Route
from sqlalchemy import select
from sqlalchemy.dialects import postgresql


def test_same_idempotency_key_replays_result_under_sqlite_contention(tmp_path):
    engine, sessions = database(f"sqlite:///{tmp_path}/concurrent-command.db")
    Base.metadata.create_all(engine)
    barrier = Barrier(2)
    guard = Lock()
    executions = 0

    def run():
        nonlocal executions
        barrier.wait()
        with sessions.begin() as session:

            def action():
                nonlocal executions
                with guard:
                    executions += 1
                    value = executions
                sleep(0.05)
                return {"value": value}

            return service.command(session, "same-scope", "same-key", {"x": 1}, action)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    with sessions.begin() as session:
        assert len(session.scalars(select(Command)).all()) == 1
    engine.dispose()
    assert results == [{"value": 1}, {"value": 1}]
    assert executions == 1


def test_postgres_advisory_lock_is_requested_before_command_lookup():
    calls = []

    class Session:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, statement, parameters):
            calls.append(("lock", str(statement), parameters["lock_key"]))

        def scalar(self, _statement):
            calls.append(("lookup",))
            return None

        def add(self, _command):
            calls.append(("save",))

    result = service.command(Session(), "book:case", "request-1", {"slot": "09:00"}, lambda: 7)
    assert result == 7
    assert [call[0] for call in calls] == ["lock", "lookup", "save"]
    assert calls[0][1] == "SELECT pg_advisory_xact_lock(:lock_key)"
    assert -(2**63) <= calls[0][2] < 2**63


def test_same_new_study_delivered_concurrently_creates_one_case(tmp_path):
    engine, sessions = database(f"sqlite:///{tmp_path}/concurrent-study.db")
    Base.metadata.create_all(engine)
    raw = make_json("MAMMOGRAPHY")
    context = {
        "encounter_ref": "same-visit",
        "source_version": 1,
        "modality": "MAMMOGRAPHY",
        "exam_purpose": "diagnostic",
    }
    profile, ruleset = profile_with_rules("private")
    report = from_json(raw, context, profile)
    barrier = Barrier(2)

    def deliver(_):
        barrier.wait()
        with sessions.begin() as session:
            return service.ingest(
                session, report, "private", "json", raw, profile=profile, ruleset=ruleset
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(deliver, range(2)))
    with sessions.begin() as session:
        assert len(session.scalars(select(Case)).all()) == 1
        assert len(session.scalars(select(Report)).all()) == 1
        assert len(session.scalars(select(Route)).all()) == 1
    engine.dispose()
    assert sorted(result["duplicate"] for result in results) == [False, True]
    assert results[0]["case_id"] == results[1]["case_id"]
    assert results[0]["route_id"] == results[1]["route_id"]


def test_case_read_query_does_not_take_postgres_row_lock():
    statements = []

    class Session:
        def scalar(self, statement):
            statements.append(str(statement.compile(dialect=postgresql.dialect())))
            return SimpleNamespace(id="case-1")

    session = Session()
    service.get_case(session, "case-1", lock=False)
    service.get_case(session, "case-1")
    assert "FOR UPDATE" not in statements[0]
    assert "FOR UPDATE" in statements[1]
