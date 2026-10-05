from app.application.service import dispatch_once
from conftest import book, create, detail, patient_view, post, publish


def test_rejection_of_new_report_keeps_old_path_until_corrected_path_is_published(client, app):
    first = publish(client, app, create(client))
    old_route_id = first["published_route"]["id"]
    assert (
        post(client, f"/cases/{first['id']}/demo-revision", {"scenario": "normal"}).status_code
        == 200
    )
    rejected = post(
        client,
        f"/cases/{first['id']}/decisions",
        {"version": 2, "action": "reject", "reason": "Нужна иная последовательность"},
    )
    assert rejected.status_code == 200, rejected.text
    current = detail(client, first["id"])
    assert [item["status"] for item in current["history"]] == [
        "published",
        "rejected",
        "manual",
    ]
    assert current["proposal"]["version"] == 3
    assert patient_view(client, first)["route"]["id"] == old_route_id
    assert patient_view(client, first)["pending_review"] is True
    assert book(client, first).status_code == 409
    corrected = [
        {
            "key": "review",
            "title": "Обсудить уточнённый результат",
            "description": "Решение специалиста по новой версии заключения",
            "action_type": "consultation",
            "depends_on": [],
            "unlock_on": [],
        }
    ]
    approved = post(
        client,
        f"/cases/{first['id']}/decisions",
        {
            "version": 3,
            "action": "edit_and_approve",
            "steps": corrected,
            "reason": "Уточнён дальнейший путь",
            "reason_code": "route_logic",
        },
    )
    assert approved.status_code == 200, approved.text
    assert patient_view(client, first)["route"]["id"] == old_route_id
    with app.state.sessions.begin() as session:
        assert dispatch_once(session) == 1
    patient = patient_view(client, first)
    assert patient["pending_review"] is False
    assert patient["route"]["id"] != old_route_id
    assert patient["route"]["steps"][0]["title"] == corrected[0]["title"]


def test_old_booking_survives_new_route_and_requires_reconciliation(client, app):
    case = publish(client, app, create(client))
    old = book(client, case).json()
    assert (
        post(client, f"/cases/{case['id']}/demo-revision", {"scenario": "finding"}).status_code
        == 200
    )
    updated = publish(client, app, detail(client, case["id"]))
    previous = patient_view(client, updated)["previous_bookings"]
    assert previous[0]["id"] == old["id"]
    assert previous[0]["route_version"] == 1
    assert book(client, updated, slot="tomorrow-11:30").status_code == 409
    assert (
        post(
            client,
            f"/patient/cases/{case['id']}/bookings/{old['id']}/cancel",
            patient=case["patient_token"],
        ).status_code
        == 200
    )
    assert book(client, updated, slot="tomorrow-11:30").status_code == 200


def carry_over(client, case, booking_id, reason="Специалист подтвердил соответствие услуги"):
    return post(
        client,
        f"/cases/{case['id']}/bookings/{booking_id}/reconcile",
        {
            "action": "carry_over",
            "target_route_id": case["published_route"]["id"],
            "reason": reason,
        },
    )


def test_specialist_carries_booking_to_matching_revised_route(client, app):
    case = publish(client, app, create(client))
    old = book(client, case).json()
    assert (
        post(client, f"/cases/{case['id']}/demo-revision", {"scenario": "finding"}).status_code
        == 200
    )
    updated = publish(client, app, detail(client, case["id"]))
    assert carry_over(client, updated, old["id"], " ").status_code == 422
    transferred = carry_over(client, updated, old["id"])
    assert transferred.status_code == 200, transferred.text
    assert transferred.json()["reconciled_route_id"] == updated["published_route"]["id"]
    assert patient_view(client, updated)["previous_bookings"] == []
    assert patient_view(client, updated)["route"]["steps"][0]["booking"]["id"] == old["id"]
    assert book(client, updated, slot="tomorrow-11:30").status_code == 409
    assert (
        post(
            client,
            f"/cases/{case['id']}/results",
            {
                "route_id": updated["published_route"]["id"],
                "step_key": "review",
                "outcome": "followup_needed",
            },
        ).status_code
        == 200
    )
    events = detail(client, case["id"])["events"]
    reconciled = next(e for e in events if e["kind"] == "booking_reconciled")
    assert reconciled["payload"]["from_route_id"] == case["published_route"]["id"]
    assert reconciled["payload"]["to_route_id"] == updated["published_route"]["id"]


def test_booking_cannot_be_carried_to_incompatible_route(client, app):
    case = publish(client, app, create(client))
    old = book(client, case).json()
    assert (
        post(client, f"/cases/{case['id']}/demo-revision", {"scenario": "normal"}).status_code
        == 200
    )
    updated = publish(client, app, detail(client, case["id"]))
    assert carry_over(client, updated, old["id"]).status_code == 409
    assert patient_view(client, updated)["previous_bookings"][0]["id"] == old["id"]


def test_late_confirmation_after_carry_over_targets_current_route(client, app):
    case = publish(client, app, create(client, profile_id="pacs"))
    old = book(client, case).json()
    with app.state.sessions.begin() as session:
        assert dispatch_once(session) == 1
    assert (
        post(client, f"/cases/{case['id']}/demo-revision", {"scenario": "finding"}).status_code
        == 200
    )
    updated = publish(client, app, detail(client, case["id"]))
    assert carry_over(client, updated, old["id"]).status_code == 200
    feedback = post(
        client,
        f"/demo/bookings/{old['id']}/feedback",
        {
            "case_id": case["id"],
            "profile_id": "pacs",
            "external_ref": old["external_ref"],
            "status": "confirmed",
            "reason": "",
        },
    )
    assert feedback.status_code == 200, feedback.text
    assert feedback.json()["status"] == "confirmed"
    assert patient_view(client, updated)["previous_bookings"] == []
    assert patient_view(client, updated)["route"]["steps"][0]["booking"]["status"] == "confirmed"
    event = next(
        e for e in detail(client, case["id"])["events"] if e["kind"] == "booking_confirmed"
    )
    assert event["payload"]["route_id"] == updated["published_route"]["id"]


def test_result_of_old_booking_requires_review_of_current_route(client, app):
    first = publish(client, app, create(client))
    old_route_id = first["published_route"]["id"]
    old_booking = book(client, first).json()
    assert (
        post(client, f"/cases/{first['id']}/demo-revision", {"scenario": "finding"}).status_code
        == 200
    )
    current = publish(client, app, detail(client, first["id"]))
    current_route_id = current["published_route"]["id"]
    assert current_route_id != old_route_id

    response = post(
        client,
        f"/cases/{first['id']}/results",
        {"route_id": old_route_id, "step_key": "review", "outcome": "followup_needed"},
    )
    assert response.status_code == 200, response.text
    updated = detail(client, first["id"])
    assert updated["proposal"]["version"] == 3
    assert updated["proposal"]["status"] == "manual"
    assert updated["pending_review"] is True
    assert updated["published_route"]["id"] == current_route_id
    assert patient_view(client, first)["route"]["id"] == current_route_id
    assert book(client, current, slot="tomorrow-11:30").status_code == 409
    assert old_booking["id"] not in {
        booking["id"] for booking in patient_view(client, first)["previous_bookings"]
    }
    trigger = next(
        event
        for event in updated["events"]
        if event["kind"] == "route_proposed"
        and event["payload"]["route_id"] == updated["proposal"]["id"]
    )
    assert trigger["payload"]["trigger_route_id"] == old_route_id


def test_result_during_pending_correction_supersedes_stale_proposal(client, app):
    first = publish(client, app, create(client))
    assert book(client, first).status_code == 200
    assert (
        post(client, f"/cases/{first['id']}/demo-revision", {"scenario": "normal"}).status_code
        == 200
    )
    pending = detail(client, first["id"])
    assert pending["proposal"]["version"] == 2

    response = post(
        client,
        f"/cases/{first['id']}/results",
        {
            "route_id": first["published_route"]["id"],
            "step_key": "review",
            "outcome": "resolved",
        },
    )
    assert response.status_code == 200, response.text
    updated = detail(client, first["id"])
    assert updated["proposal"]["version"] == 3
    assert updated["proposal"]["status"] == "manual"
    assert (
        next(item for item in updated["history"] if item["version"] == 2)["status"] == "superseded"
    )
    assert (
        post(
            client,
            f"/cases/{first['id']}/decisions",
            {"version": 2, "action": "approve"},
        ).status_code
        == 409
    )


def test_result_invalidates_approved_route_waiting_for_worker(client, app):
    first = publish(client, app, create(client))
    published_id = first["published_route"]["id"]
    assert book(client, first).status_code == 200
    assert (
        post(client, f"/cases/{first['id']}/demo-revision", {"scenario": "normal"}).status_code
        == 200
    )
    assert (
        post(
            client,
            f"/cases/{first['id']}/decisions",
            {"version": 2, "action": "approve"},
        ).status_code
        == 200
    )
    assert (
        post(
            client,
            f"/cases/{first['id']}/results",
            {"route_id": published_id, "step_key": "review", "outcome": "resolved"},
        ).status_code
        == 200
    )
    with app.state.sessions.begin() as session:
        assert dispatch_once(session) == 1
    updated = detail(client, first["id"])
    assert updated["published_route"]["id"] == published_id
    assert updated["proposal"]["version"] == 3
    assert updated["proposal"]["status"] == "manual"
    assert (
        next(item for item in updated["history"] if item["version"] == 2)["status"] == "superseded"
    )
