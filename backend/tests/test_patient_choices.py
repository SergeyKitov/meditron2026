from conftest import book, create, detail, patient_view, post, publish


def choice_request(client, case, action, *, route_id=None, reason_code=None, token=None):
    body = {"route_id": route_id or case["published_route"]["id"]}
    if reason_code is not None:
        body["reason_code"] = reason_code
    return post(
        client,
        f"/patient/cases/{case['id']}/steps/review/{action}",
        body,
        token=token,
        patient=case["patient_token"],
    )


def test_decline_requires_reason_and_blocks_booking_until_resume(client, app):
    case = publish(client, app, create(client))
    assert (
        post(
            client, f"/patient/cases/{case['id']}/shown", patient=case["patient_token"]
        ).status_code
        == 200
    )
    assert choice_request(client, case, "decline").status_code == 422
    declined = choice_request(client, case, "decline", reason_code="not_ready", token="choice-1")
    assert declined.status_code == 200, declined.text
    assert declined.json()["status"] == "declined"
    assert (
        choice_request(client, case, "decline", reason_code="not_ready", token="choice-1").json()
        == declined.json()
    )
    assert patient_view(client, case)["route"]["steps"][0]["choice"]["reason_code"] == "not_ready"
    assert (
        detail(client, case["id"])["published_route"]["steps"][0]["choice"]["status"] == "declined"
    )
    assert book(client, case).status_code == 409
    assert choice_request(client, case, "decline", reason_code="no_time").status_code == 409
    resumed = choice_request(client, case, "resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "resumed"
    assert resumed.json()["reason_code"] is None
    assert book(client, case).status_code == 200
    counts = client.get("/api/v1/metrics").json()["counts"]
    assert counts["step_declined"] == 1
    assert counts["step_resumed"] == 1
    analysis = client.get("/api/v1/metrics").json()["patient_choices"]
    assert analysis["shown_route_versions"] == 1
    assert analysis["route_versions_with_decline"] == 1
    assert analysis["route_versions_with_resume"] == 1
    assert analysis["by_step"] == [
        {
            "step_key": "review",
            "declined_route_steps": 1,
            "resumed_route_steps": 1,
            "first_decline_reasons": {"not_ready": 1},
        }
    ]
    events = detail(client, case["id"])["events"]
    assert len([event for event in events if event["kind"] == "step_declined"]) == 1


def test_active_booking_must_be_cancelled_before_decline(client, app):
    case = publish(client, app, create(client))
    booking = book(client, case).json()
    assert choice_request(client, case, "decline", reason_code="no_time").status_code == 409
    cancel = post(
        client,
        f"/patient/cases/{case['id']}/bookings/{booking['id']}/cancel",
        patient=case["patient_token"],
    )
    assert cancel.status_code == 200
    assert choice_request(client, case, "decline", reason_code="no_time").status_code == 200


def test_choice_is_bound_to_current_route_version(client, app):
    case = publish(client, app, create(client))
    old_route_id = case["published_route"]["id"]
    assert choice_request(client, case, "decline", reason_code="other").status_code == 200
    revision = post(client, f"/cases/{case['id']}/demo-revision", {"scenario": "finding"})
    assert revision.status_code == 200
    assert choice_request(client, case, "resume").status_code == 409
    assert choice_request(client, case, "decline", reason_code="other").status_code == 409
    updated = publish(client, app, detail(client, case["id"]))
    assert updated["published_route"]["id"] != old_route_id
    assert updated["published_route"]["steps"][0].get("choice") is None
    assert choice_request(client, updated, "decline", reason_code="other").status_code == 200
