from app.application import service
from app.persistence.models import Event, OutboxEvent
from conftest import create, detail, patient_view, post
from sqlalchemy import select


def approve(client, case):
    response = post(
        client,
        f"/cases/{case['id']}/decisions",
        {"version": case["proposal"]["version"], "action": "approve"},
    )
    assert response.status_code == 200, response.text


def test_bad_event_does_not_block_other_cases_and_can_be_retried(client, app):
    first, second = create(client), create(client)
    approve(client, first)
    approve(client, second)
    with app.state.sessions.begin() as session:
        poison = service.emit(session, first["id"], "unknown_outbox_kind", queued=True)
        poison.created_at = "2000-01-01T00:00:00.000000+00:00"
        session.flush()
        poison_id = poison.id

    with app.state.sessions.begin() as session:
        assert service.dispatch_once(session) == 2
    assert patient_view(client, first)["route"] is not None
    assert patient_view(client, second)["route"] is not None

    with app.state.sessions.begin() as session:
        poison = session.get(OutboxEvent, poison_id)
        assert poison.attempts == 1
        assert poison.next_attempt_at
        assert poison.last_error == "invalid_event_reference_or_kind"
        assert poison.processed is False
        assert service.dispatch_once(session) == 0  # Backoff prevents a hot loop.

    for expected_attempt in range(2, service.OUTBOX_MAX_ATTEMPTS + 1):
        with app.state.sessions.begin() as session:
            session.get(OutboxEvent, poison_id).next_attempt_at = "2000-01-01T00:00:00.000000+00:00"
            session.flush()
            assert service.dispatch_once(session) == 0
            assert session.get(OutboxEvent, poison_id).attempts == expected_attempt

    status = client.get("/api/v1/operations/outbox").json()
    assert status["total_unprocessed"] == status["total_failed"] == 1
    assert status["events"][0]["status"] == "failed"
    assert "payload" not in status["events"][0]
    assert (
        client.get("/api/v1/operations/outbox", headers={"X-Demo-Role": "patient"}).status_code
        == 403
    )
    published_route_id = detail(client, first["id"])["published_route"]["id"]
    with app.state.sessions.begin() as session:
        assert service.dispatch_once(session) == 0  # Terminal failure is skipped.
        poison = session.get(OutboxEvent, poison_id)
        poison.kind = "publish_route"
        poison.payload = {"route_id": published_route_id}
        assert session.get(Event, poison_id).kind == "unknown_outbox_kind"

    assert post(client, f"/operations/outbox/{poison_id}/retry", {"reason": " "}).status_code == 422
    retry = post(
        client,
        f"/operations/outbox/{poison_id}/retry",
        {"reason": "Источник события исправлен"},
        token="retry-once",
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "queued"
    assert (
        post(
            client,
            f"/operations/outbox/{poison_id}/retry",
            {"reason": "Источник события исправлен"},
            token="retry-once",
        ).json()
        == retry.json()
    )
    with app.state.sessions.begin() as session:
        assert service.dispatch_once(session) == 1
        assert session.get(OutboxEvent, poison_id).processed is True
    assert sum(e["kind"] == "published" for e in detail(client, first["id"])["events"]) == 1


def test_event_savepoint_rolls_back_partial_publication(client, app, monkeypatch):
    case = create(client)
    approve(client, case)
    with app.state.sessions.begin() as session:
        queued = session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.case_id == case["id"], OutboxEvent.kind == "publish_route"
            )
        )
        queued_id = queued.id

    original = service.previous_bookings

    def fail_after_status_change(*args):
        raise RuntimeError("sensitive report content must not be persisted as an error")

    monkeypatch.setattr(service, "previous_bookings", fail_after_status_change)
    with app.state.sessions.begin() as session:
        assert service.dispatch_once(session) == 0
    monkeypatch.setattr(service, "previous_bookings", original)
    assert patient_view(client, case)["route"] is None
    assert detail(client, case["id"])["proposal"]["status"] == "approved"
    with app.state.sessions.begin() as session:
        queued = session.get(OutboxEvent, queued_id)
        assert queued.last_error == "RuntimeError"
        queued.next_attempt_at = "2000-01-01T00:00:00.000000+00:00"

    with app.state.sessions.begin() as session:
        assert service.dispatch_once(session) == 1
    assert patient_view(client, case)["route"] is not None
    assert sum(e["kind"] == "published" for e in detail(client, case["id"])["events"]) == 1
