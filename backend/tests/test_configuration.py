import copy
import json

import pytest
from app import api as api_module
from app.adapters import reports
from app.adapters.configuration import validate_pair, validate_profiles, validate_rules
from app.adapters.reports import load_config
from app.adapters.synthetic import make_json, make_sr
from app.config_publish import publish as publish_configuration
from app.domain.routing import DomainError
from app.persistence.models import Report, Route
from conftest import book, create, detail, post, publish
from sqlalchemy import select


def configs():
    return load_config("profiles.json"), load_config("rules.json")


def install_test_profiles(monkeypatch, tmp_path, profiles, rules):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "profiles.json").write_text(json.dumps(profiles, ensure_ascii=False))
    (config_dir / "rules.json").write_text(json.dumps(rules, ensure_ascii=False))
    monkeypatch.setattr(reports, "CONFIG", config_dir)
    reports._read_config.cache_clear()
    return config_dir / "profiles.json"


def test_profiles_and_rules_validate_together():
    profiles, rules = configs()
    validate_pair(profiles, rules)
    assert len(profiles) == 2 and len(rules["rules"]) == 29


def test_ingress_uses_one_profile_and_rules_snapshot_during_config_change(
    client, app, monkeypatch, tmp_path
):
    profiles, rules = configs()
    profile_path = install_test_profiles(monkeypatch, tmp_path, profiles, rules)
    rules_path = profile_path.parent / "rules.json"
    original_from_json = api_module.from_json

    def parse_then_change_config(raw, context, profile):
        parsed = original_from_json(raw, context, profile)
        changed_profiles = copy.deepcopy(profiles)
        changed_profiles["private"]["version"] = "demo-2"
        changed_profiles["private"]["fields"]["MAMMOGRAPHY"]["mmg_rads_right"]["path"] = (
            "aiResult.probParams.mmg.replaced_right"
        )
        changed_rules = copy.deepcopy(rules)
        changed_rules["version"] = f"{rules['version']}-changed"
        profile_path.write_text(json.dumps(changed_profiles, ensure_ascii=False))
        rules_path.write_text(json.dumps(changed_rules, ensure_ascii=False))
        return parsed

    monkeypatch.setattr(api_module, "from_json", parse_then_change_config)
    try:
        response = post(
            client,
            "/reports/json",
            {
                "profile_id": "private",
                "context": {
                    "encounter_ref": "snapshot-visit",
                    "source_version": 1,
                    "modality": "MAMMOGRAPHY",
                    "exam_purpose": "diagnostic",
                },
                "report": make_json("MAMMOGRAPHY"),
            },
        )
        assert response.status_code == 200, response.text
        with app.state.sessions.begin() as session:
            source = session.scalar(select(Report).where(Report.id == response.json()["report_id"]))
            route = session.scalar(select(Route).where(Route.id == response.json()["route_id"]))
            assert source.raw["integration_profile"]["version"] == profiles["private"]["version"]
            assert source.raw["ruleset"]["version"] == rules["version"]
            assert route.ruleset_version == "catboost-synthetic-2026.10.05-v1"
            assert {fact["code"] for fact in source.canonical["facts"]} == {
                "mmg_rads_right",
                "mmg_rads_left",
            }
    finally:
        reports._read_config.cache_clear()


def test_published_release_switches_profiles_and_rules_together(monkeypatch, tmp_path):
    profiles, rules = configs()
    profile_path = install_test_profiles(monkeypatch, tmp_path, profiles, rules)
    config_dir = profile_path.parent
    try:
        first_id = publish_configuration(
            config_dir, "demo-admin", "Initial synthetic configuration"
        )
        assert reports.profile_with_rules("private")[0]["version"] == "demo-1"
        changed_profiles = copy.deepcopy(profiles)
        changed_profiles["private"]["version"] = "demo-2"
        changed_rules = copy.deepcopy(rules)
        changed_rules["version"] = f"{rules['version']}-changed"
        profile_path.write_text(json.dumps(changed_profiles, ensure_ascii=False))
        (config_dir / "rules.json").write_text(json.dumps(changed_rules, ensure_ascii=False))

        active_profile, active_rules = reports.profile_with_rules("private")
        assert (active_profile["version"], active_rules["version"]) == (
            "demo-1",
            rules["version"],
        )
        second_id = publish_configuration(config_dir, "demo-admin", "Update both versions")
        active_profile, active_rules = reports.profile_with_rules("private")
        assert (active_profile["version"], active_rules["version"]) == (
            "demo-2",
            changed_rules["version"],
        )
        assert first_id != second_id
        assert len(list((config_dir / "releases").glob("*.json"))) == 2
        pointer = json.loads((config_dir / "active-release.json").read_text())
        release = json.loads((config_dir / "releases" / f"{second_id}.json").read_text())
        assert pointer["release_id"] == release["release_id"] == second_id
        assert release["author"] == "demo-admin"
        assert release["reason"] == "Update both versions"
    finally:
        reports._read_config.cache_clear()
        reports._read_release.cache_clear()


def test_broken_active_release_does_not_fall_back_to_draft(monkeypatch, tmp_path):
    profiles, rules = configs()
    profile_path = install_test_profiles(monkeypatch, tmp_path, profiles, rules)
    config_dir = profile_path.parent
    (config_dir / "active-release.json").write_text(
        json.dumps({"schema_version": 1, "release_id": "0" * 32, "sha256": "0" * 64})
    )
    with pytest.raises(DomainError, match="недоступен"):
        reports.profile_with_rules("private")


def test_ingested_report_records_published_release_id(client, app):
    release_id = json.loads((reports.CONFIG / "active-release.json").read_text())["release_id"]
    response = post(
        client,
        "/reports/json",
        {
            "profile_id": "private",
            "context": {
                "encounter_ref": "release-audit-visit",
                "source_version": 1,
                "modality": "MAMMOGRAPHY",
                "exam_purpose": "diagnostic",
            },
            "report": make_json("MAMMOGRAPHY"),
        },
    )
    assert response.status_code == 200, response.text
    with app.state.sessions.begin() as session:
        source = session.get(Report, response.json()["report_id"])
        assert source.raw["config_release_id"] == release_id


def test_input_and_booking_modes_can_be_combined_independently(client, app, monkeypatch, tmp_path):
    profiles, rules = configs()
    json_deferred = copy.deepcopy(profiles["private"])
    json_deferred["clinic_id"] = "json_deferred"
    json_deferred["booking_mode"] = "deferred_simulator"
    json_deferred["booking_callback"] = copy.deepcopy(profiles["pacs"]["booking_callback"])
    profiles["json_deferred"] = json_deferred
    sr_local = copy.deepcopy(profiles["pacs"])
    sr_local["clinic_id"] = "sr_local"
    sr_local["booking_mode"] = "local_simulator"
    del sr_local["booking_callback"]
    profiles["sr_local"] = sr_local
    validate_pair(profiles, rules)
    install_test_profiles(monkeypatch, tmp_path, profiles, rules)
    try:
        json_case = publish(client, app, create(client, profile_id="json_deferred"))
        sr_case = publish(client, app, create(client, profile_id="sr_local"))
        assert book(client, json_case).json()["status"] == "requested"
        sr_booking = book(client, sr_case).json()
        assert sr_booking["status"] == "confirmed"
        assert sr_booking["service_id"] == "DC-01"
    finally:
        reports._read_config.cache_clear()


def test_existing_route_keeps_service_and_booking_mode_after_profile_change(
    client, app, monkeypatch, tmp_path
):
    profiles, rules = configs()
    config_path = install_test_profiles(monkeypatch, tmp_path, profiles, rules)
    try:
        case = publish(client, app, create(client))
        profiles["private"]["services"]["consultation"] = "SP-NEW"
        profiles["private"]["booking_mode"] = "deferred_simulator"
        profiles["private"]["booking_callback"] = copy.deepcopy(
            profiles["pacs"]["booking_callback"]
        )
        config_path.write_text(json.dumps(profiles, ensure_ascii=False))
        reports._read_config.cache_clear()

        old_booking = book(client, case).json()
        assert old_booking["status"] == "confirmed"
        assert old_booking["service_id"] == "SP-01"
        assert (
            post(
                client,
                f"/patient/cases/{case['id']}/bookings/{old_booking['id']}/cancel",
                patient=case["patient_token"],
            ).status_code
            == 200
        )
        assert (
            post(client, f"/cases/{case['id']}/demo-revision", {"scenario": "finding"}).status_code
            == 200
        )
        revised = publish(client, app, detail(client, case["id"]))
        new_booking = book(client, revised, slot="tomorrow-11:30").json()
        assert new_booking["status"] == "requested"
        assert new_booking["service_id"] == "SP-NEW"
    finally:
        reports._read_config.cache_clear()


def test_two_source_profiles_share_a_clinic_case_and_detect_conflicts(
    client, app, monkeypatch, tmp_path
):
    profiles, rules = configs()
    second = copy.deepcopy(profiles["pacs"])
    second["clinic_id"] = "private"
    second["label"] = profiles["private"]["label"]
    second["services"] = copy.deepcopy(profiles["private"]["services"])
    second["booking_mode"] = "local_simulator"
    del second["booking_callback"]
    profiles["private_sr"] = second
    mismatch = copy.deepcopy(profiles)
    mismatch["private_sr"]["label"] = "Иное название учреждения"
    with pytest.raises(DomainError, match="одинаковое label"):
        validate_profiles(mismatch)
    validate_pair(profiles, rules)
    config_path = install_test_profiles(monkeypatch, tmp_path, profiles, rules)
    try:
        raw = make_json("MAMMOGRAPHY", study_uid="1.2.826.0.1.3680043.10.2026.811")
        context = {
            "encounter_ref": "same-clinic-visit",
            "source_version": 1,
            "modality": "MAMMOGRAPHY",
            "exam_purpose": "diagnostic",
        }
        first = client.post(
            "/api/v1/reports/json",
            json={"profile_id": "private", "context": context, "report": raw},
        )
        assert first.status_code == 200, first.text
        first_case = detail(client, first.json()["case_id"])
        assert first_case["clinic_id"] == "private"
        first_case = publish(client, app, first_case)

        content = make_sr(raw, "MAMMOGRAPHY")
        params = {"profile_id": "private_sr", **context}
        same = client.post(
            "/api/v1/reports/dicom",
            params=params,
            files={"file": ("same.dcm", content, "application/dicom")},
        )
        assert same.status_code == 200, same.text
        assert same.json()["duplicate"] is True
        assert same.json()["case_id"] == first_case["id"]

        conflicting = make_json("MAMMOGRAPHY", "normal", raw["studyIUID"])
        conflict = client.post(
            "/api/v1/reports/dicom",
            params=params,
            files={"file": ("conflict.dcm", make_sr(conflicting, "MAMMOGRAPHY"))},
        )
        assert conflict.status_code == 409

        revised = client.post(
            "/api/v1/reports/dicom",
            params={**params, "source_version": 2},
            files={"file": ("revised.dcm", content, "application/dicom")},
        )
        assert revised.status_code == 200, revised.text
        assert revised.json()["case_id"] == first_case["id"]
        latest = detail(client, first_case["id"])
        assert latest["profile_id"] == latest["source_profile_id"] == "private_sr"
        assert latest["patient_token"] == first_case["patient_token"]
        assert latest["proposal"]["version"] == 2
        assert len(client.get("/api/v1/cases").json()) == 1
        latest = publish(client, app, latest)
        groups = client.get("/api/v1/quality/rule-review").json()["groups"]
        assert {group["profile_id"] for group in groups} == {"private", "private_sr"}
        assert book(client, latest).status_code == 200
        another = publish(client, app, create(client, profile_id="private_sr"))
        assert book(client, another).status_code == 409  # One clinic's shared slot.

        profiles["private_sr"]["clinic_id"] = "another_clinic"
        config_path.write_text(json.dumps(profiles, ensure_ascii=False))
        reports._read_config.cache_clear()
        assert post(client, "/demo/cases", {"profile_id": "private_sr"}).status_code == 409
    finally:
        reports._read_config.cache_clear()


def test_invalid_mapping_and_missing_required_field_rejected():
    profiles, rules = configs()
    profiles["private"]["fields"]["MAMMOGRAPHY"]["mmg_rads_right"]["path"] = "aiResult..right"
    with pytest.raises(DomainError, match="path"):
        validate_profiles(profiles)
    profiles, rules = configs()
    del profiles["private"]["fields"]["MAMMOGRAPHY"]["mmg_rads_right"]
    with pytest.raises(DomainError, match="обязательных канонических полей"):
        validate_pair(profiles, rules)
    profiles, rules = configs()
    del profiles["pacs"]["fields"]["CT_CHEST"]["ct_lc_num"]["sr_code"]
    with pytest.raises(DomainError, match="sr_code"):
        validate_profiles(profiles)
    profiles, _ = configs()
    profiles["pacs"]["fields"]["MAMMOGRAPHY"]["mmg_rads_left"]["sr_code"] = "mmg_rads_right"
    with pytest.raises(DomainError, match="уникальны"):
        validate_profiles(profiles)
    profiles, _ = configs()
    profiles["private"]["report_ingress"]["secret_env"] = "not-an-env-name"
    with pytest.raises(DomainError, match="report_ingress"):
        validate_profiles(profiles)
    profiles, _ = configs()
    del profiles["private"]["report_ingress"]
    validate_profiles(profiles)  # A future Kafka connector need not enable signed HTTP ingress.


def test_json_array_selectors_keep_concrete_pointers_and_reject_ambiguity(
    client, monkeypatch, tmp_path
):
    profiles, rules = configs()
    profile = profiles["private"]
    profile["study_path"] = "metadata.identifiers[0].uid"
    profile["conclusion_path"] = "aiResult.conclusions[0].text"
    fields = profile["fields"]["MAMMOGRAPHY"]
    fields["mmg_rads_right"]["path"] = "aiResult.findings[code=right].value"
    fields["mmg_rads_left"]["path"] = "aiResult.findings[code=left].value"
    validate_pair(profiles, rules)
    install_test_profiles(monkeypatch, tmp_path, profiles, rules)
    try:
        raw = make_json("MAMMOGRAPHY")
        raw["metadata"] = {"identifiers": [{"uid": raw["studyIUID"]}]}
        raw["aiResult"]["conclusions"] = [{"text": raw["aiResult"]["conclusion"]}]
        raw["aiResult"]["findings"] = [
            {"code": "left", "value": 2},
            {"code": "right", "value": 4},
        ]
        body = {
            "profile_id": "private",
            "context": {
                "encounter_ref": "array-example",
                "source_version": 1,
                "modality": "MAMMOGRAPHY",
                "exam_purpose": "diagnostic",
            },
            "report": raw,
        }
        response = client.post("/api/v1/profiles/private/preview", json=body)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["route_preview"]["status"] == "draft"
        assert {fact["code"]: fact["source_pointer"] for fact in result["facts"]} == {
            "mmg_rads_right": "aiResult.findings[1].value",
            "mmg_rads_left": "aiResult.findings[0].value",
        }

        raw["aiResult"]["findings"].reverse()
        reordered = client.post("/api/v1/profiles/private/preview", json=body)
        assert reordered.status_code == 200, reordered.text
        assert reordered.json()["route_preview"]["steps"] == result["route_preview"]["steps"]
        assert {fact["code"]: fact["source_pointer"] for fact in reordered.json()["facts"]} == {
            "mmg_rads_right": "aiResult.findings[0].value",
            "mmg_rads_left": "aiResult.findings[1].value",
        }

        raw["aiResult"]["findings"].append({"code": "right", "value": 3})
        response = client.post("/api/v1/profiles/private/preview", json=body)
        assert response.status_code == 422
        assert "Неоднозначный JSON-селектор" in response.text
    finally:
        reports._read_config.cache_clear()


def test_invalid_array_selector_is_rejected_by_profile_validation():
    profiles, _ = configs()
    fields = profiles["private"]["fields"]["MAMMOGRAPHY"]
    fields["mmg_rads_right"]["path"] = "aiResult.findings[*].value"
    with pytest.raises(DomainError, match="path"):
        validate_profiles(profiles)


def test_rule_reference_cycle_and_duplicate_id_rejected():
    profiles, rules = configs()
    rules["rules"][0]["all"][0]["field"] = "not_mapped"
    with pytest.raises(DomainError, match="неизвестные поля"):
        validate_pair(profiles, rules)
    _, rules = configs()
    rules["rules"].append(copy.deepcopy(rules["rules"][0]))
    with pytest.raises(DomainError, match="повторяется ID"):
        validate_rules(rules)
    _, rules = configs()
    step_rule = next(rule for rule in rules["rules"] if rule["steps"])
    step_rule["steps"][0]["depends_on"] = ["review"]
    step_rule["steps"][0]["unlock_on"] = ["followup_needed"]
    with pytest.raises(DomainError, match="цикл"):
        validate_rules(rules)


def test_json_and_sr_preview_do_not_persist_and_agree(client):
    raw = make_json("MAMMOGRAPHY", study_uid="1.2.826.0.1.3680043.10.2026.700")
    context = {
        "encounter_ref": "preview-visit",
        "source_version": 1,
        "modality": "MAMMOGRAPHY",
        "exam_purpose": "diagnostic",
    }
    json_preview = client.post(
        "/api/v1/profiles/private/preview",
        json={
            "profile_id": "private",
            "context": context,
            "report": raw,
        },
    )
    sr_preview = client.post(
        "/api/v1/profiles/pacs/preview-sr",
        params=context,
        files={
            "file": ("preview.dcm", make_sr(raw, "MAMMOGRAPHY"), "application/dicom"),
        },
    )
    assert json_preview.status_code == 200, json_preview.text
    assert sr_preview.status_code == 200, sr_preview.text
    a, b = json_preview.json(), sr_preview.json()
    assert [(fact["code"], fact["value"]) for fact in a["facts"]] == [
        (fact["code"], fact["value"]) for fact in b["facts"]
    ]
    assert a["route_preview"]["steps"] == b["route_preview"]["steps"]
    assert a["route_preview"]["status"] == "draft"
    assert a["profile_version"] == b["profile_version"] == "demo-1"
    assert client.get("/api/v1/cases").json() == []


def test_preview_rejects_wrong_input_type_and_untrusted_sr(client):
    raw = make_json("CT_CHEST")
    context = {"encounter_ref": "preview", "source_version": 1, "modality": "CT_CHEST"}
    assert (
        client.post(
            "/api/v1/profiles/pacs/preview",
            json={
                "profile_id": "pacs",
                "context": context,
                "report": raw,
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/profiles/private/preview-sr",
            params=context,
            files={
                "file": ("preview.dcm", make_sr(raw, "CT_CHEST")),
            },
        ).status_code
        == 422
    )
