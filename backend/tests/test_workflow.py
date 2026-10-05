import copy
from datetime import datetime, timedelta, timezone

import pytest
from app.application.service import dispatch_once
from app.persistence.models import Event
from conftest import book, create, detail, patient_view, post, publish
from sqlalchemy import select


def test_approval_outbox_and_result_gate(client, app):
    case = create(client)
    assert patient_view(client, case)["route"] is None
    response = post(client, f"/cases/{case['id']}/decisions", {"version": 1, "action": "approve"})
    assert response.status_code == 200
    # Approval commits independently; a restarted worker can publish later.
    assert patient_view(client, case)["route"] is None
    with app.state.sessions.begin() as session:
        assert dispatch_once(session) == 1
    with app.state.sessions.begin() as session:
        assert dispatch_once(session) == 0
    case = detail(client, case["id"])
    patient = patient_view(client, case)
    assert [s["key"] for s in patient["route"]["steps"]] == ["review"]
    assert len(patient["route"]["steps"]) == 1
    assert "trace" not in patient["route"]
    assert book(client, case, "followup").status_code == 409
    assert book(client, case).status_code == 200
    assert book(client, case, "followup").status_code == 409  # Booking is not a result.
    response = post(
        client,
        f"/cases/{case['id']}/results",
        {
            "route_id": case["published_route"]["id"],
            "step_key": "review",
            "outcome": "followup_needed",
        },
    )
    assert response.status_code == 200, response.text
    updated = detail(client, case["id"])
    assert updated["proposal"]["status"] == "manual"
    assert updated["proposal"]["steps"] == []
    assert updated["proposal"]["parent_route_id"] == case["published_route"]["id"]
    assert updated["proposal"]["trigger_result_id"]
    assert book(client, case, "followup").status_code == 409
    assert book(client, case).status_code == 409
    next_step = [
        {
            "key": "review",
            "title": "Следующий приём по результату",
            "description": "Специалист определил продолжение после получения результата.",
            "action_type": "followup",
            "depends_on": [],
            "unlock_on": [],
            "prerequisites": [],
        }
    ]
    response = post(
        client,
        f"/cases/{case['id']}/decisions",
        {
            "version": updated["proposal"]["version"],
            "action": "edit_and_approve",
            "steps": next_step,
            "reason": "Получен результат предыдущего шага",
        },
    )
    assert response.status_code == 200, response.text
    with app.state.sessions.begin() as session:
        dispatch_once(session)
    second = detail(client, case["id"])
    assert book(client, second).status_code == 200
    closed = post(
        client,
        f"/cases/{case['id']}/results",
        {
            "route_id": second["published_route"]["id"],
            "step_key": "review",
            "outcome": "resolved",
        },
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["next_route_id"] is None
    finished = detail(client, case["id"])
    assert finished["pending_review"] is False
    assert finished["published_route"]["steps"][0]["availability"] == "completed"
    events = finished["events"]
    assert sum(e["kind"] == "published" for e in events) == 2
    assert any(e["kind"] == "cycle_closed" for e in events)


def test_manual_requires_explicit_choice_and_preserves_correction(client, app):
    case = create(client, modality="CT_CHEST", exam_purpose="unknown")
    assert case["proposal"]["status"] == "manual"
    assert (
        post(
            client, f"/cases/{case['id']}/decisions", {"version": 1, "action": "approve"}
        ).status_code
        == 422
    )
    corrected = [
        {
            "key": "review",
            "title": "Уточнить дальнейшие действия",
            "description": "Выбор специалиста",
            "action_type": "consultation",
            "depends_on": [],
            "unlock_on": [],
            "prerequisites": [],
        }
    ]
    assert (
        post(
            client,
            f"/cases/{case['id']}/decisions",
            {
                "version": 1,
                "action": "edit_and_approve",
                "steps": corrected,
                "reason": "Назначение исследования неизвестно",
            },
        ).status_code
        == 200
    )
    with app.state.sessions.begin() as session:
        dispatch_once(session)
    updated = detail(client, case["id"])
    assert updated["decisions"][0]["original_steps"] == []
    assert updated["decisions"][0]["final_steps"] == corrected
    assert patient_view(client, case)["route"]["steps"][0]["title"] == corrected[0]["title"]


def test_corrected_report_freezes_booking_and_requires_new_approval(client, app):
    case = publish(client, app, create(client))
    old_id = case["published_route"]["id"]
    assert (
        post(client, f"/cases/{case['id']}/demo-revision", {"scenario": "normal"}).status_code
        == 200
    )
    updated = detail(client, case["id"])
    assert updated["proposal"]["version"] == 2
    assert patient_view(client, case)["route"]["id"] == old_id
    assert patient_view(client, case)["pending_review"] is True
    assert book(client, case).status_code == 409
    assert (
        post(
            client, f"/cases/{case['id']}/decisions", {"version": 1, "action": "approve"}
        ).status_code
        == 409
    )
    updated = publish(client, app, updated)
    assert updated["published_route"]["id"] != old_id
    assert patient_view(client, case)["route"]["steps"] == []
    assert book(client, case).status_code == 409


def test_stale_outbox_cannot_publish_superseded_route(client, app):
    case = create(client)
    post(client, f"/cases/{case['id']}/decisions", {"version": 1, "action": "approve"})
    post(client, f"/cases/{case['id']}/demo-revision", {"scenario": "normal"})
    with app.state.sessions.begin() as session:
        dispatch_once(session)
    assert patient_view(client, case)["route"] is None


def test_idempotency_conflict_cancellation_and_slot_collision(client, app):
    body = {"modality": "MAMMOGRAPHY"}
    a = post(client, "/demo/cases", body, token="create-1")
    b = post(client, "/demo/cases", body, token="create-1")
    assert a.json() == b.json()
    assert (
        post(client, "/demo/cases", {"modality": "CT_CHEST"}, token="create-1").status_code == 409
    )
    case = publish(client, app, detail(client, a.json()["case_id"]))
    other = publish(client, app, create(client))
    body = {
        "route_id": case["published_route"]["id"],
        "step_key": "review",
        "slot": "tomorrow-09:00",
    }
    a = post(
        client,
        f"/patient/cases/{case['id']}/bookings",
        body,
        token="book-1",
        patient=case["patient_token"],
    )
    b = post(
        client,
        f"/patient/cases/{case['id']}/bookings",
        body,
        token="book-1",
        patient=case["patient_token"],
    )
    assert a.status_code == 200, a.text
    assert a.json() == b.json()
    assert book(client, other).status_code == 409
    assert (
        post(
            client,
            f"/patient/cases/{case['id']}/bookings/{a.json()['id']}/cancel",
            patient=case["patient_token"],
        ).status_code
        == 200
    )
    assert book(client, other).status_code == 200
    assert book(client, case, slot="tomorrow-11:30").status_code == 200


@pytest.mark.parametrize("outcome", ["resolved", "replan"])
def test_results_can_end_or_replan_path(client, app, outcome):
    case = publish(client, app, create(client))
    assert book(client, case).status_code == 200
    response = post(
        client,
        f"/cases/{case['id']}/results",
        {
            "route_id": case["published_route"]["id"],
            "step_key": "review",
            "outcome": outcome,
        },
    )
    assert response.status_code == 200
    updated = detail(client, case["id"])
    assert len(updated["published_route"]["steps"]) == 1
    assert updated["published_route"]["steps"][0]["availability"] == "completed"
    assert book(client, case, "followup").status_code == 409
    if outcome == "replan":
        assert updated["proposal"]["status"] == "manual"
        assert updated["pending_review"]
    else:
        assert updated["pending_review"] is False
        assert any(event["kind"] == "cycle_closed" for event in updated["events"])


def test_rejected_route_not_published_and_cycles_rejected(client, app):
    case = create(client)
    steps = copy.deepcopy(case["proposal"]["proposed_steps"])
    steps[0]["depends_on"] = ["followup"]
    steps[0]["unlock_on"] = ["followup_needed"]
    assert (
        post(
            client,
            f"/cases/{case['id']}/decisions",
            {
                "version": 1,
                "action": "edit_and_approve",
                "reason": "Проверка цикла",
                "steps": steps,
            },
        ).status_code
        == 422
    )
    rejection_body = {"version": 1, "action": "reject", "reason": "Нужно уточнение"}
    rejected = post(client, f"/cases/{case['id']}/decisions", rejection_body, token="reject-v1")
    assert rejected.status_code == 200
    assert rejected.json()["revision_version"] == 2
    assert (
        post(client, f"/cases/{case['id']}/decisions", rejection_body, token="reject-v1").json()
        == rejected.json()
    )
    with app.state.sessions.begin() as session:
        assert dispatch_once(session) == 0
    assert patient_view(client, case)["route"] is None
    revised = detail(client, case["id"])
    assert revised["pending_review"] is True
    assert revised["proposal"]["status"] == "manual"
    assert revised["proposal"]["version"] == 2
    assert [item["status"] for item in revised["history"]] == ["rejected", "manual"]
    assert len(revised["decisions"]) == 1
    assert post(client, f"/cases/{case['id']}/decisions", rejection_body).status_code == 409
    assert (
        post(
            client, f"/cases/{case['id']}/decisions", {"version": 2, "action": "approve"}
        ).status_code
        == 422
    )
    corrected = [
        {
            key: value
            for key, value in step.items()
            if key not in ("availability", "booking", "booking_gate_open", "execution_gate_open")
        }
        for step in revised["proposal"]["steps"]
    ]
    corrected[0]["title"] = "Уточнённый первый шаг"
    approval = post(
        client,
        f"/cases/{case['id']}/decisions",
        {
            "version": 2,
            "action": "edit_and_approve",
            "steps": corrected,
            "reason": "Исправлен маршрут после отклонения",
            "reason_code": "route_logic",
        },
    )
    assert approval.status_code == 200, approval.text
    assert patient_view(client, case)["route"] is None
    with app.state.sessions.begin() as session:
        assert dispatch_once(session) == 1
    final = detail(client, case["id"])
    assert final["proposal"]["status"] == "published"
    assert [item["action"] for item in final["decisions"]] == ["reject", "edit_and_approve"]
    assert patient_view(client, case)["route"]["steps"][0]["title"] == corrected[0]["title"]


def test_role_and_patient_scope(client):
    case, other = create(client), create(client)
    assert client.get("/api/v1/cases", headers={"X-Demo-Role": "patient"}).status_code == 403
    assert (
        client.get(
            f"/api/v1/patient/cases/{case['id']}",
            headers={"X-Patient-Token": other["patient_token"]},
        ).status_code
        == 403
    )


def test_metrics_deduplicate_views_and_keep_conversion_bounded(client, app):
    seen, unseen = publish(client, app, create(client)), publish(client, app, create(client))
    for _ in range(3):
        post(client, f"/patient/cases/{seen['id']}/shown", patient=seen["patient_token"])
    assert book(client, seen).status_code == 200
    assert book(client, unseen, slot="tomorrow-11:30").status_code == 200
    stats = client.get("/api/v1/metrics").json()
    assert stats["counts"]["shown"] == 1
    assert stats["counts"]["booking_confirmed"] == 2
    assert stats["booking_conversion"] == 1.0
    assert stats["conversion_details"]["shown_route_versions"] == 1
    assert stats["conversion_details"]["converted_route_versions"] == 1
    assert stats["conversion_details"]["provisional_route_versions"] == 0
    assert stats["uplift"] is None


def test_conversion_does_not_attribute_booking_requested_before_show(client, app):
    case = publish(client, app, create(client))
    assert book(client, case).status_code == 200
    assert (
        post(
            client, f"/patient/cases/{case['id']}/shown", patient=case["patient_token"]
        ).status_code
        == 200
    )
    stats = client.get("/api/v1/metrics").json()
    assert stats["counts"]["booking_confirmed"] == 1
    assert stats["conversion_details"]["shown_route_versions"] == 1
    assert stats["conversion_details"]["converted_route_versions"] == 0
    assert stats["booking_conversion"] == 0


def test_conversion_requires_same_route_version_and_window(client, app):
    case = publish(client, app, create(client))
    assert (
        post(
            client, f"/patient/cases/{case['id']}/shown", patient=case["patient_token"]
        ).status_code
        == 200
    )
    assert (
        post(client, f"/cases/{case['id']}/demo-revision", {"scenario": "finding"}).status_code
        == 200
    )
    revised = publish(client, app, detail(client, case["id"]))
    assert book(client, revised).status_code == 200
    before_second_show = client.get("/api/v1/metrics").json()
    assert before_second_show["conversion_details"]["shown_route_versions"] == 1
    assert before_second_show["booking_conversion"] == 0

    assert (
        post(
            client, f"/patient/cases/{case['id']}/shown", patient=case["patient_token"]
        ).status_code
        == 200
    )
    after_second_show = client.get("/api/v1/metrics").json()
    assert after_second_show["conversion_details"]["shown_route_versions"] == 2
    assert after_second_show["conversion_details"]["converted_route_versions"] == 0

    assert client.get("/api/v1/metrics?shown_from=2026-10-04T10:00:00").status_code == 422
    assert client.get("/api/v1/metrics?attribution_days=0").status_code == 422


def test_conversion_window_and_show_cohort(client, app):
    case = publish(client, app, create(client))
    assert (
        post(
            client, f"/patient/cases/{case['id']}/shown", patient=case["patient_token"]
        ).status_code
        == 200
    )
    assert book(client, case).status_code == 200
    assert client.get("/api/v1/metrics").json()["booking_conversion"] == 1

    old_show = datetime.now(timezone.utc) - timedelta(days=8)
    with app.state.sessions.begin() as session:
        shown_event = next(
            event
            for event in session.scalars(
                select(Event).where(Event.case_id == case["id"], Event.kind == "shown")
            )
            if event.payload["route_id"] == case["published_route"]["id"]
        )
        shown_event.created_at = old_show.isoformat()

    seven_day = client.get("/api/v1/metrics?attribution_days=7").json()
    assert seven_day["conversion_details"]["shown_route_versions"] == 1
    assert seven_day["conversion_details"]["converted_route_versions"] == 0
    assert seven_day["conversion_details"]["provisional_route_versions"] == 0
    assert client.get("/api/v1/metrics?attribution_days=10").json()["booking_conversion"] == 1

    cohort_start = (old_show + timedelta(days=1)).isoformat()
    excluded = client.get("/api/v1/metrics", params={"shown_from": cohort_start}).json()
    assert excluded["conversion_details"]["shown_route_versions"] == 0
    assert excluded["booking_conversion"] is None
