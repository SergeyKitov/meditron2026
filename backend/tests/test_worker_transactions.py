import logging

from app.worker import process_one, run_iteration
from conftest import create, patient_view, post


def test_worker_commits_one_delivery_per_transaction(client, app):
    cases = [create(client), create(client)]
    for case in cases:
        response = post(
            client,
            f"/cases/{case['id']}/decisions",
            {"version": case["proposal"]["version"], "action": "approve"},
        )
        assert response.status_code == 200, response.text

    assert process_one(app.state.sessions) == 1
    assert sum(patient_view(client, case)["route"] is not None for case in cases) == 1
    assert process_one(app.state.sessions) == 1
    assert all(patient_view(client, case)["route"] is not None for case in cases)
    assert process_one(app.state.sessions) == 0


def test_worker_does_not_log_exception_content(caplog):
    class BrokenSessions:
        def begin(self):
            raise RuntimeError("patient text must not reach logs")

    with caplog.at_level(logging.ERROR):
        assert run_iteration(BrokenSessions()) == 0
    assert "error_code=RuntimeError" in caplog.text
    assert "patient text" not in caplog.text
