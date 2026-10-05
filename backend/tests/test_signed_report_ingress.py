import base64
import copy
import hashlib
import hmac
import json
import time

from app.adapters.synthetic import make_json, make_sr


def signed_report(
    client,
    path,
    body,
    *,
    profile_id,
    secret="report-test-secret",
    event_id="report-event-1",
    timestamp=None,
    signature=None,
    signed_path=None,
):
    content = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    timestamp = str(int(time.time())) if timestamp is None else str(timestamp)
    signed = b"\n".join(
        [
            timestamp.encode(),
            profile_id.encode(),
            event_id.encode(),
            (signed_path or path).encode(),
            content,
        ]
    )
    signature = signature or hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return client.post(
        path,
        content=content,
        headers={
            "Content-Type": "application/json",
            "X-Demo-Role": "patient",
            "X-Source-Profile": profile_id,
            "X-Event-Id": event_id,
            "X-Timestamp": timestamp,
            "X-Signature": signature,
        },
    )


def json_body(study_uid=None):
    return {
        "profile_id": "private",
        "context": {
            "encounter_ref": "synthetic-visit",
            "source_version": 1,
            "modality": "MAMMOGRAPHY",
            "exam_purpose": "diagnostic",
        },
        "report": make_json("MAMMOGRAPHY", study_uid=study_uid),
    }


def test_signed_json_report_authentication_and_event_dedup(client, monkeypatch):
    path = "/api/v1/integrations/reports/json"
    body = json_body()
    assert signed_report(client, path, body, profile_id="private").status_code == 503
    monkeypatch.setenv("MEDITRON_REPORT_SECRET_PRIVATE", "report-test-secret")
    assert (
        client.post(
            path,
            content=b"{invalid-json",
            headers={
                "Content-Type": "application/json",
                "X-Source-Profile": "private",
                "X-Event-Id": "malformed-event",
                "X-Timestamp": str(int(time.time())),
                "X-Signature": "0" * 64,
            },
        ).status_code
        == 401
    )
    assert (
        signed_report(client, path, body, profile_id="private", signature="0" * 64).status_code
        == 401
    )
    assert (
        signed_report(
            client, path, body, profile_id="private", timestamp=int(time.time()) - 301
        ).status_code
        == 401
    )
    assert (
        signed_report(
            client, path, body, profile_id="private", signed_path=path + "/other"
        ).status_code
        == 401
    )
    assert (
        signed_report(client, path + "?source=other", body, profile_id="private").status_code == 400
    )
    first = signed_report(client, path, body, profile_id="private")
    second = signed_report(client, path, body, profile_id="private")
    assert first.status_code == 200, first.text
    assert second.status_code == 200 and second.json() == first.json()
    assert first.json()["duplicate"] is False
    changed = copy.deepcopy(body)
    changed["report"]["aiResult"]["conclusion"] = "Исправленный синтетический текст"
    assert signed_report(client, path, changed, profile_id="private").status_code == 409
    new_event_same_report = signed_report(
        client, path, body, profile_id="private", event_id="report-event-2"
    )
    assert new_event_same_report.status_code == 200
    assert new_event_same_report.json()["duplicate"] is True


def test_invalid_signed_report_does_not_consume_event_id(client, monkeypatch):
    monkeypatch.setenv("MEDITRON_REPORT_SECRET_PRIVATE", "report-test-secret")
    path = "/api/v1/integrations/reports/json"
    invalid = json_body()
    invalid["report"].pop("synthetic")
    assert signed_report(client, path, invalid, profile_id="private").status_code == 422
    valid = json_body(study_uid=invalid["report"]["studyIUID"])
    assert signed_report(client, path, valid, profile_id="private").status_code == 200
    wrong_profile = {**valid, "profile_id": "pacs"}
    assert signed_report(client, path, wrong_profile, profile_id="private").status_code == 401


def test_signed_dicom_report_uses_same_core_and_binds_sr_bytes(client, monkeypatch):
    monkeypatch.setenv("MEDITRON_REPORT_SECRET_PACS", "report-test-secret")
    path = "/api/v1/integrations/reports/dicom"
    raw = make_json("CT_CHEST")
    body = {
        "profile_id": "pacs",
        "context": {
            "encounter_ref": "synthetic-ct-visit",
            "source_version": 1,
            "modality": "CT_CHEST",
            "exam_purpose": "diagnostic",
        },
        "dicom_base64": base64.b64encode(make_sr(raw, "CT_CHEST")).decode(),
    }
    first = signed_report(client, path, body, profile_id="pacs")
    assert first.status_code == 200, first.text
    assert signed_report(client, path, body, profile_id="pacs").json() == first.json()
    altered = copy.deepcopy(body)
    altered["context"]["exam_purpose"] = "screening"
    original_bytes = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    original_signed = b"\n".join(
        [timestamp.encode(), b"pacs", b"tamper-event", path.encode(), original_bytes]
    )
    original_signature = hmac.new(
        b"report-test-secret", original_signed, hashlib.sha256
    ).hexdigest()
    assert (
        signed_report(
            client,
            path,
            altered,
            profile_id="pacs",
            event_id="tamper-event",
            timestamp=timestamp,
            signature=original_signature,
        ).status_code
        == 401
    )
    assert signed_report(client, path, altered, profile_id="pacs").status_code == 409
    bad = copy.deepcopy(body)
    bad["dicom_base64"] = "not-base64"
    assert (
        signed_report(client, path, bad, profile_id="pacs", event_id="new-dicom-event").status_code
        == 422
    )
