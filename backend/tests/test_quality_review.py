import copy
import json

from conftest import create, post


def decision(client, case, action, reason="", reason_code="unspecified", steps=None):
    return post(
        client,
        f"/cases/{case['id']}/decisions",
        {
            "version": case["proposal"]["version"],
            "action": action,
            "reason": reason,
            "reason_code": reason_code,
            "steps": steps,
        },
    )


def test_quality_summary_aggregates_corrections_without_patient_content(client):
    approved = create(client)
    wording = create(client)
    routing = create(client)
    rejected = create(client)
    assert decision(client, approved, "approve").status_code == 200

    wording_steps = copy.deepcopy(wording["proposal"]["proposed_steps"])
    wording_steps[0]["title"] = "Понятное пациенту название"
    private_reason = "Синтетический свободный комментарий, не предназначенный для экспорта"
    assert (
        decision(
            client, wording, "edit_and_approve", private_reason, "wording", wording_steps
        ).status_code
        == 200
    )

    routing_steps = copy.deepcopy(routing["proposal"]["proposed_steps"])
    routing_steps[0]["action_type"] = "diagnostic_imaging"
    assert (
        decision(
            client,
            routing,
            "edit_and_approve",
            "Изменён тип следующей услуги",
            "route_logic",
            routing_steps,
        ).status_code
        == 200
    )
    assert decision(client, rejected, "reject", "Нужен пересмотр", "other").status_code == 200

    response = client.get("/api/v1/quality/rule-review")
    assert response.status_code == 200
    data = response.json()
    assert data["synthetic"] is True
    assert data["aggregation_only"] is True
    assert data["total_decisions"] == 4
    assert len(data["groups"]) == 1
    group = data["groups"][0]
    assert group["exam_purpose"] == "diagnostic"
    assert (group["approved"], group["edited"], group["rejected"]) == (1, 2, 1)
    assert group["edit_types"] == {"route_changed": 1, "wording_only": 1}
    assert group["reason_codes"] == {"other": 1, "route_logic": 1, "wording": 1}
    serialized = json.dumps(data, ensure_ascii=False)
    for forbidden in [
        approved["id"],
        wording["patient_token"],
        wording["report"]["conclusion"],
        private_reason,
        "study_uid",
        "case_id",
        "source_pointer",
    ]:
        assert forbidden not in serialized
    assert (
        client.get("/api/v1/quality/rule-review", headers={"X-Demo-Role": "patient"}).status_code
        == 403
    )


def test_quality_summary_marks_manual_and_legacy_unspecified_reason(client):
    case = create(client, modality="CT_CHEST", exam_purpose="unknown")
    steps = [
        {
            "key": "review",
            "title": "Консультация по результату",
            "description": "Определить дальнейшие действия",
            "action_type": "consultation",
            "depends_on": [],
            "unlock_on": [],
        }
    ]
    response = post(
        client,
        f"/cases/{case['id']}/decisions",
        {
            "version": 1,
            "action": "edit_and_approve",
            "reason": "Неизвестное назначение исследования",
            "steps": steps,
        },
    )
    assert response.status_code == 200
    group = client.get("/api/v1/quality/rule-review").json()["groups"][0]
    assert group["exam_purpose"] == "unknown"
    assert group["proposal_mode"] == "manual"
    assert group["reason_codes"] == {"unspecified": 1}
    assert group["edit_types"] == {"route_changed": 1}
