import copy
import io

import pydicom
import pytest
from app.adapters.reports import from_json, from_sr, load_config, profile_by_id
from app.adapters.synthetic import make_json, make_sr
from app.domain.routing import DomainError, evaluate


def context(modality="MAMMOGRAPHY", version=1):
    return {
        "encounter_ref": "synthetic-visit",
        "source_version": version,
        "modality": modality,
        "exam_purpose": "diagnostic",
    }


@pytest.mark.parametrize("modality", ["MAMMOGRAPHY", "CT_CHEST"])
@pytest.mark.parametrize("scenario", ["finding", "normal"])
def test_equivalent_json_and_sr(modality, scenario):
    raw = make_json(modality, scenario)
    json_report = from_json(raw, context(modality), profile_by_id("private"))
    sr_report = from_sr(make_sr(raw, modality), context(modality), profile_by_id("pacs"))
    assert [(f.code, f.value) for f in json_report.facts] == [
        (f.code, f.value) for f in sr_report.facts
    ]
    rules = load_config("rules.json")
    assert evaluate(json_report, rules)["steps"] == evaluate(sr_report, rules)["steps"]
    assert all(f.source_pointer.startswith("SR.ContentSequence") for f in sr_report.facts)
    assert sr_report.conclusion == json_report.conclusion


@pytest.mark.parametrize("value", ["4", 4.5, True, 0, 6])
def test_no_silent_coercion_of_facts(value):
    raw = make_json("MAMMOGRAPHY")
    raw["aiResult"]["probParams"]["mmg"]["mmg_rads_right"] = value
    with pytest.raises(DomainError):
        from_json(raw, context(), profile_by_id("private"))


def test_missing_field_is_manual_and_runtime_does_not_execute_teacher_rules():
    raw = make_json("MAMMOGRAPHY", "missing")
    report = from_json(raw, context(), profile_by_id("private"))
    assert evaluate(report, load_config("rules.json"))["status"] == "manual"
    report = from_json(make_json("MAMMOGRAPHY"), context(), profile_by_id("private"))
    rules = load_config("rules.json")
    original = evaluate(report, rules)
    conflict = copy.deepcopy(rules["rules"][0])
    conflict["id"] = "conflicting-rule"
    rules["rules"].append(conflict)
    assert evaluate(report, rules) == original


def test_mapping_changes_without_changing_rules():
    raw = make_json("MAMMOGRAPHY")
    baseline = from_json(raw, context(), profile_by_id("private"))
    profile = copy.deepcopy(profile_by_id("private"))
    profile["fields"]["MAMMOGRAPHY"]["mmg_rads_right"]["path"] = "custom.right_category"
    raw["custom"] = {"right_category": raw["aiResult"]["probParams"]["mmg"].pop("mmg_rads_right")}
    changed = from_json(raw, context(), profile)
    assert next(f for f in changed.facts if f.code == "mmg_rads_right").source_pointer == (
        "custom.right_category"
    )
    rules = load_config("rules.json")
    assert evaluate(baseline, rules)["steps"] == evaluate(changed, rules)["steps"]


def test_duplicate_sr_fact_rejected():
    ds = pydicom.dcmread(io.BytesIO(make_sr(make_json("MAMMOGRAPHY"), "MAMMOGRAPHY")))
    ds.ContentSequence.append(copy.deepcopy(ds.ContentSequence[0]))
    stream = io.BytesIO()
    ds.save_as(stream, enforce_file_format=True)
    with pytest.raises(DomainError, match="Неоднозначное"):
        from_sr(stream.getvalue(), context(), profile_by_id("pacs"))


def test_report_version_dedup_and_conflict(client):
    raw = make_json("MAMMOGRAPHY")
    payload = {"profile_id": "private", "context": context(), "report": raw}
    first = client.post("/api/v1/reports/json", json=payload)
    assert first.status_code == 200
    second = client.post("/api/v1/reports/json", json=payload)
    assert second.status_code == 200 and second.json()["duplicate"]
    assert second.json()["route_id"] == first.json()["route_id"]
    assert client.get("/api/v1/metrics").json()["routing_latency"]["count"] == 1
    raw["aiResult"]["conclusion"] = "Изменённое заключение"
    assert client.post("/api/v1/reports/json", json=payload).status_code == 409
    payload["context"]["source_version"] = 2
    assert client.post("/api/v1/reports/json", json=payload).status_code == 200


def test_dicom_upload_and_invalid_metadata(client):
    content = make_sr(make_json("CT_CHEST"), "CT_CHEST")
    params = {"profile_id": "pacs", **context("CT_CHEST")}
    response = client.post(
        "/api/v1/reports/dicom",
        params=params,
        files={"file": ("synthetic.dcm", content, "application/dicom")},
    )
    assert response.status_code == 200, response.text
    params["source_version"] = 0
    assert (
        client.post(
            "/api/v1/reports/dicom", params=params, files={"file": ("bad.dcm", content)}
        ).status_code
        == 422
    )


def test_only_synthetic_input_accepted(client):
    raw = make_json("MAMMOGRAPHY")
    raw.pop("synthetic")
    assert (
        client.post(
            "/api/v1/reports/json",
            json={"profile_id": "private", "context": context(), "report": raw},
        ).status_code
        == 422
    )
