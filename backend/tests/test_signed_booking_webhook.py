import copy
import hashlib
import hmac
import json
import time

from app.adapters import reports
from app.adapters.reports import load_config
from app.adapters.synthetic import make_json
from app.application.service import dispatch_once
from conftest import book, create, post, publish


def signed_request(
    client,
    booking,
    case,
    *,
    secret="local-test-secret",
    event_id="clinic-event-1",
    timestamp=None,
    body_changes=None,
    signature=None,
):
    path = f"/api/v1/integrations/bookings/{booking['id']}/feedback"
    body = {
        "case_id": case["id"],
        "profile_id": "pacs",
        "external_ref": booking["external_ref"],
        "status": "confirmed",
        "reason": "",
        **(body_changes or {}),
    }
    content = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    timestamp = str(int(time.time())) if timestamp is None else str(timestamp)
    signed = b"\n".join([timestamp.encode(), b"pacs", event_id.encode(), path.encode(), content])
    value = signature or hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return client.post(
        path,
        content=content,
        headers={
            "Content-Type": "application/json",
            "X-Demo-Role": "patient",  # The integration endpoint authenticates its source independently.
            "X-Source-Profile": "pacs",
            "X-Event-Id": event_id,
            "X-Timestamp": timestamp,
            "X-Signature": value,
        },
    )


def ready_booking(client, app, slot="tomorrow-09:00"):
    case = publish(client, app, create(client, profile_id="pacs"))
    booking = book(client, case, slot=slot).json()
    with app.state.sessions.begin() as session:
        dispatch_once(session)
    return case, booking


def test_signed_source_is_required_and_replay_is_idempotent(client, app, monkeypatch):
    case, booking = ready_booking(client, app)
    assert signed_request(client, booking, case).status_code == 503
    monkeypatch.setenv("MEDITRON_BOOKING_SECRET_PACS", "local-test-secret")
    assert signed_request(client, booking, case, signature="0" * 64).status_code == 401
    assert (
        client.post(
            f"/api/v1/integrations/bookings/{booking['id']}/feedback",
            content=b"{",
            headers={
                "Content-Type": "application/json",
                "X-Source-Profile": "pacs",
                "X-Event-Id": "malformed-body",
                "X-Timestamp": str(int(time.time())),
                "X-Signature": "0" * 64,
            },
        ).status_code
        == 401
    )
    assert (
        signed_request(client, booking, case, timestamp=int(time.time()) - 301).status_code == 401
    )
    assert (
        signed_request(client, booking, case, body_changes={"profile_id": "private"}).status_code
        == 401
    )
    first = signed_request(client, booking, case)
    second = signed_request(client, booking, case)
    assert first.status_code == 200 and first.json() == second.json()
    assert first.json()["status"] == "confirmed"
    assert signed_request(client, booking, case, body_changes={"reason": "new"}).status_code == 409


def test_event_id_is_unique_per_source_and_signature_binds_path(client, app, monkeypatch):
    monkeypatch.setenv("MEDITRON_BOOKING_SECRET_PACS", "local-test-secret")
    case1, booking1 = ready_booking(client, app)
    case2, booking2 = ready_booking(client, app, slot="tomorrow-11:30")
    assert signed_request(client, booking1, case1, event_id="same-id").status_code == 200
    assert signed_request(client, booking2, case2, event_id="same-id").status_code == 409
    path1 = f"/api/v1/integrations/bookings/{booking1['id']}/feedback"
    body2 = {
        "case_id": case2["id"],
        "profile_id": "pacs",
        "external_ref": booking2["external_ref"],
        "status": "confirmed",
        "reason": "",
    }
    content2 = json.dumps(body2, ensure_ascii=False, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    bad_signed = b"\n".join([timestamp.encode(), b"pacs", b"new-id", path1.encode(), content2])
    bad_signature = hmac.new(b"local-test-secret", bad_signed, hashlib.sha256).hexdigest()
    assert (
        signed_request(
            client, booking2, case2, event_id="new-id", timestamp=timestamp, signature=bad_signature
        ).status_code
        == 401
    )
    assert signed_request(client, booking2, case2, event_id="new-id").status_code == 200


def test_demo_feedback_remains_role_restricted(client, app):
    case, booking = ready_booking(client, app)
    response = client.post(
        f"/api/v1/demo/bookings/{booking['id']}/feedback",
        json={
            "case_id": case["id"],
            "profile_id": "pacs",
            "external_ref": booking["external_ref"],
            "status": "confirmed",
            "reason": "",
        },
        headers={"X-Demo-Role": "patient", "Idempotency-Key": "attempt"},
    )
    assert response.status_code == 403


def test_signed_cancellation_feedback_waits_for_cancel_request(client, app, monkeypatch):
    monkeypatch.setenv("MEDITRON_BOOKING_SECRET_PACS", "local-test-secret")
    case, booking = ready_booking(client, app)
    premature = signed_request(
        client,
        booking,
        case,
        event_id="premature-cancel",
        body_changes={"status": "cancelled"},
    )
    assert premature.status_code == 409
    assert signed_request(client, booking, case).status_code == 200
    request = post(
        client,
        f"/patient/cases/{case['id']}/bookings/{booking['id']}/cancel",
        patient=case["patient_token"],
    )
    assert request.status_code == 200 and request.json()["status"] == "cancel_requested"
    first = signed_request(
        client,
        booking,
        case,
        event_id="cancel-event",
        body_changes={"status": "cancelled"},
    )
    second = signed_request(
        client,
        booking,
        case,
        event_id="cancel-event",
        body_changes={"status": "cancelled"},
    )
    assert first.status_code == 200 and second.json() == first.json()
    assert first.json()["status"] == "cancelled"


def test_old_pending_booking_accepts_signed_reply_after_profile_update(
    client, app, monkeypatch, tmp_path
):
    case, booking = ready_booking(client, app)
    profiles = load_config("profiles.json")
    rules = load_config("rules.json")
    updated = copy.deepcopy(profiles)
    updated["pacs"]["booking_mode"] = "local_simulator"
    del updated["pacs"]["booking_callback"]
    updated["pacs_json"] = copy.deepcopy(profiles["private"])
    updated["pacs_json"]["clinic_id"] = "pacs"
    updated["pacs_json"]["label"] = profiles["pacs"]["label"]
    updated["pacs_json"]["services"] = copy.deepcopy(profiles["pacs"]["services"])
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "profiles.json").write_text(json.dumps(updated, ensure_ascii=False))
    (config_dir / "rules.json").write_text(json.dumps(rules, ensure_ascii=False))
    monkeypatch.setattr(reports, "CONFIG", config_dir)
    reports._read_config.cache_clear()
    monkeypatch.setenv("MEDITRON_BOOKING_SECRET_PACS", "local-test-secret")
    try:
        raw = make_json(case["modality"], study_uid=case["report"]["study_uid"])
        context = {
            "encounter_ref": case["report"]["encounter_ref"],
            "source_version": 2,
            "modality": case["modality"],
            "exam_purpose": case["report"]["exam_purpose"],
        }
        revision = client.post(
            "/api/v1/reports/json",
            json={"profile_id": "pacs_json", "context": context, "report": raw},
        )
        assert revision.status_code == 200, revision.text
        changed_case = client.get(f"/api/v1/cases/{case['id']}").json()
        assert changed_case["profile_id"] == "pacs_json"
        assert signed_request(client, booking, case).status_code == 200
    finally:
        reports._read_config.cache_clear()
