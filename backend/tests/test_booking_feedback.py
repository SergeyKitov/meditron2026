from app.application.service import dispatch_once
from conftest import book, create, detail, patient_view, post, publish


def send_feedback(client, case, booking, status, token=None, **changes):
    body = {
        "case_id": case["id"],
        "profile_id": case["profile_id"],
        "external_ref": booking["external_ref"],
        "status": status,
        "reason": "Синтетический отказ" if status != "confirmed" else "",
        **changes,
    }
    return post(client, f"/demo/bookings/{booking['id']}/feedback", body, token=token)


def test_deferred_booking_requires_external_confirmation(client, app):
    case = publish(client, app, create(client, profile_id="pacs"))
    assert (
        post(
            client, f"/patient/cases/{case['id']}/shown", patient=case["patient_token"]
        ).status_code
        == 200
    )
    booking = book(client, case).json()
    assert booking["status"] == "requested"
    assert patient_view(client, case)["route"]["steps"][0]["booking"]["status"] == "requested"
    assert client.get("/api/v1/metrics").json()["counts"]["booking_confirmed"] == 0
    assert book(client, case, slot="tomorrow-11:30").status_code == 409
    assert send_feedback(client, case, booking, "confirmed").status_code == 409
    with app.state.sessions.begin() as session:
        assert dispatch_once(session) == 1
    assert (
        patient_view(client, case)["route"]["steps"][0]["booking"]["status"]
        == "awaiting_confirmation"
    )
    assert (
        send_feedback(client, case, booking, "confirmed", external_ref="wrong").status_code == 409
    )
    assert (
        send_feedback(client, case, booking, "confirmed", profile_id="private").status_code == 403
    )
    first = send_feedback(client, case, booking, "confirmed", token="provider-event-1")
    second = send_feedback(client, case, booking, "confirmed", token="provider-event-1")
    assert first.status_code == 200 and second.json() == first.json()
    assert first.json()["status"] == "confirmed"
    assert send_feedback(client, case, booking, "rejected").status_code == 409
    stats = client.get("/api/v1/metrics").json()
    assert stats["counts"]["booking_confirmed"] == 1
    assert stats["conversion_details"]["converted_route_versions"] == 1
    assert stats["booking_conversion"] == 1
    assert (
        post(
            client,
            f"/cases/{case['id']}/results",
            {
                "route_id": case["published_route"]["id"],
                "step_key": "review",
                "outcome": "followup_needed",
            },
        ).status_code
        == 200
    )


def test_rejection_and_no_slots_release_reservation(client, app):
    case = publish(client, app, create(client, profile_id="pacs"))
    first = book(client, case).json()
    with app.state.sessions.begin() as session:
        dispatch_once(session)
    assert send_feedback(client, case, first, "rejected", reason="").status_code == 422
    rejected = send_feedback(client, case, first, "rejected")
    assert rejected.status_code == 200
    assert rejected.json()["status_reason"] == "Синтетический отказ"
    second = book(client, case).json()
    assert second["status"] == "requested"
    with app.state.sessions.begin() as session:
        dispatch_once(session)
    assert send_feedback(client, case, second, "no_slots").status_code == 200
    third = book(client, case, slot="tomorrow-11:30").json()
    assert third["status"] == "requested"
    assert client.get("/api/v1/metrics").json()["counts"]["booking_confirmed"] == 0


def test_deferred_cancellation_waits_for_provider_before_releasing_slot(client, app):
    case = publish(client, app, create(client, profile_id="pacs"))
    booking = book(client, case).json()
    with app.state.sessions.begin() as session:
        assert dispatch_once(session) == 1
    assert send_feedback(client, case, booking, "confirmed").status_code == 200
    cancelled = post(
        client,
        f"/patient/cases/{case['id']}/bookings/{booking['id']}/cancel",
        patient=case["patient_token"],
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancel_requested"
    assert book(client, case, slot="tomorrow-11:30").status_code == 409
    with app.state.sessions.begin() as session:
        assert dispatch_once(session) == 1
    assert any(
        event["kind"] == "booking_cancellation_submission_simulated"
        for event in detail(client, case["id"])["events"]
    )
    assert send_feedback(client, case, booking, "confirmed").status_code == 409
    response = send_feedback(client, case, booking, "cancelled")
    assert response.status_code == 200 and response.json()["status"] == "cancelled"
    assert book(client, case).status_code == 200


def test_provider_can_reject_deferred_cancellation_without_losing_booking(client, app):
    case = publish(client, app, create(client, profile_id="pacs"))
    booking = book(client, case).json()
    with app.state.sessions.begin() as session:
        dispatch_once(session)
    assert send_feedback(client, case, booking, "confirmed").status_code == 200
    assert (
        post(
            client,
            f"/patient/cases/{case['id']}/bookings/{booking['id']}/cancel",
            patient=case["patient_token"],
        ).json()["status"]
        == "cancel_requested"
    )
    assert send_feedback(client, case, booking, "cancel_rejected", reason="").status_code == 422
    response = send_feedback(client, case, booking, "cancel_rejected", reason="Приём уже начался")
    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"
    assert response.json()["status_reason"] == "Приём уже начался"
    assert book(client, case, slot="tomorrow-11:30").status_code == 409


def test_old_pending_booking_survives_route_correction(client, app):
    case = publish(client, app, create(client, profile_id="pacs"))
    booking = book(client, case).json()
    with app.state.sessions.begin() as session:
        dispatch_once(session)
    assert (
        post(client, f"/cases/{case['id']}/demo-revision", {"scenario": "finding"}).status_code
        == 200
    )
    updated = publish(client, app, detail(client, case["id"]))
    previous = patient_view(client, updated)["previous_bookings"]
    assert previous[0]["status"] == "awaiting_confirmation"
    assert previous[0]["id"] == booking["id"]
    assert book(client, updated, slot="tomorrow-11:30").status_code == 409
    assert send_feedback(client, case, booking, "confirmed").status_code == 200
    assert patient_view(client, updated)["previous_bookings"][0]["status"] == "confirmed"
