"""One next action, parallel lab preparation, and a linked decision cycle."""

from datetime import datetime, timedelta, timezone

from app.application.service import dispatch_once
from conftest import book, create, detail, patient_view, post


def approved_with_lab(client, app, gate):
    case = create(client)
    steps = case["proposal"]["proposed_steps"]
    assert len(steps) == 1
    steps[0]["prerequisites"] = [
        {
            "key": "lab_1",
            "title": "Синтетический анализ по протоколу услуги",
            "description": "Только после решения специалиста; результат нужен для следующей услуги.",
            "kind": "lab",
            "service_key": "lab_demo",
            "gate": gate,
        }
    ]
    response = post(
        client,
        f"/cases/{case['id']}/decisions",
        {
            "version": case["proposal"]["version"],
            "action": "edit_and_approve",
            "steps": steps,
            "reason": "Подготовка предусмотрена синтетическим протоколом услуги",
        },
    )
    assert response.status_code == 200, response.text
    with app.state.sessions.begin() as session:
        dispatch_once(session)
    return detail(client, case["id"])


def lab_booking(client, case):
    response = book(client, case, "lab_1", slot="tomorrow-11:30")
    assert response.status_code == 200, response.text
    return response.json()


def lab_result(client, case, booking, outcome="accepted", valid_until=None):
    return post(
        client,
        f"/cases/{case['id']}/prerequisite-results",
        {
            "route_id": case["published_route"]["id"],
            "booking_id": booking["id"],
            "requirement_key": "lab_1",
            "outcome": outcome,
            "valid_until": valid_until,
        },
    )


def main_result(client, case, outcome="followup_needed"):
    return post(
        client,
        f"/cases/{case['id']}/results",
        {"route_id": case["published_route"]["id"], "step_key": "review", "outcome": outcome},
    )


def clearance(client, case):
    return client.get(
        f"/api/v1/cases/{case['id']}/steps/review/clearance",
        params={"route_id": case["published_route"]["id"]},
    )


def test_lab_and_main_booking_can_run_in_parallel_before_execution(client, app):
    case = approved_with_lab(client, app, "before_execution")
    visible = patient_view(client, case)["route"]
    assert len(visible["steps"]) == 1
    assert visible["steps"][0]["prerequisites"][0]["readiness"] == "pending"
    assert visible["steps"][0]["booking_gate_open"] is True
    main = book(client, case, slot="tomorrow-15:00")
    lab = lab_booking(client, case)
    assert main.status_code == 200
    assert main.json()["status"] == lab["status"] == "confirmed"
    assert clearance(client, case).json() == {
        "ready": False,
        "reasons": ["preparation_not_ready"],
        "missing_prerequisites": ["lab_1"],
    }
    assert main_result(client, case).status_code == 409
    accepted = lab_result(client, case, lab)
    assert accepted.status_code == 200, accepted.text
    assert (
        patient_view(client, case)["route"]["steps"][0]["prerequisites"][0]["readiness"] == "ready"
    )
    assert clearance(client, case).json()["ready"] is True
    recorded = main_result(client, case)
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["next_route_id"]
    changed = detail(client, case["id"])
    assert changed["proposal"]["status"] == "manual"
    assert changed["proposal"]["steps"] == []
    assert changed["proposal"]["parent_route_id"] == case["published_route"]["id"]
    assert changed["proposal"]["trigger_result_id"]
    assert len(patient_view(client, case)["route"]["steps"]) == 1


def test_before_booking_gate_and_rejected_result(client, app):
    case = approved_with_lab(client, app, "before_booking")
    assert book(client, case).status_code == 409
    lab = lab_booking(client, case)
    rejected = lab_result(client, case, lab, "rejected")
    assert rejected.status_code == 200
    assert book(client, case).status_code == 409
    assert (
        patient_view(client, case)["route"]["steps"][0]["prerequisites"][0]["readiness"]
        == "rejected"
    )
    second = lab_booking(client, case)
    accepted = lab_result(client, case, second)
    assert accepted.status_code == 200
    assert book(client, case, slot="tomorrow-15:00").status_code == 200


def test_expired_or_corrected_lab_result_blocks_completion(client, app):
    case = approved_with_lab(client, app, "before_execution")
    assert book(client, case, slot="tomorrow-15:00").status_code == 200
    lab = lab_booking(client, case)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert lab_result(client, case, lab, valid_until=past).status_code == 422
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert lab_result(client, case, lab, valid_until=future).status_code == 200
    assert lab_result(client, case, lab, outcome="rejected").status_code == 200
    assert main_result(client, case).status_code == 409
    assert lab_result(client, case, lab, valid_until=future).status_code == 200
    assert main_result(client, case, "resolved").status_code == 200
    updated = detail(client, case["id"])
    assert updated["pending_review"] is False
    assert updated["published_route"]["steps"][0]["availability"] == "completed"


def test_unmapped_lab_service_and_two_clinical_steps_are_rejected(client):
    case = create(client)
    step = case["proposal"]["proposed_steps"][0]
    step["prerequisites"] = [
        {
            "key": "lab_1",
            "title": "Тест",
            "description": "Только демо",
            "kind": "lab",
            "service_key": "missing_lab_service",
            "gate": "before_execution",
        }
    ]
    body = {
        "version": 1,
        "action": "edit_and_approve",
        "steps": [step],
        "reason": "Тест профиля",
    }
    assert post(client, f"/cases/{case['id']}/decisions", body).status_code == 422
    body["steps"] = [case["proposal"]["proposed_steps"][0]] * 2
    assert post(client, f"/cases/{case['id']}/decisions", body).status_code == 422


def test_parallel_booking_rejects_same_slot_and_lab_after_main(client, app):
    case = approved_with_lab(client, app, "before_execution")
    assert book(client, case, "review", slot="tomorrow-11:30").status_code == 200
    assert book(client, case, "lab_1", slot="tomorrow-11:30").status_code == 409
    assert book(client, case, "lab_1", slot="tomorrow-15:00").status_code == 409
    assert book(client, case, "lab_1", slot="tomorrow-09:00").status_code == 200
