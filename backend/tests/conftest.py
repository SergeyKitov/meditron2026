import uuid

import pytest
from app.api import create_app
from app.application.service import dispatch_once
from app.persistence.models import Base
from fastapi.testclient import TestClient


@pytest.fixture
def app(tmp_path):
    application = create_app(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(application.state.engine)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def client(app):
    with TestClient(app, headers={"X-Demo-Role": "reviewer"}) as c:
        yield c


def post(client, path, body=None, token=None, patient=None):
    headers = {"Idempotency-Key": token or str(uuid.uuid4())}
    if patient:
        headers["X-Patient-Token"] = patient
    return client.post("/api/v1" + path, json=body, headers=headers)


def create(client, **scenario):
    response = post(client, "/demo/cases", scenario)
    assert response.status_code == 200, response.text
    return detail(client, response.json()["case_id"])


def detail(client, case_id):
    response = client.get("/api/v1/cases/" + case_id)
    assert response.status_code == 200, response.text
    return response.json()


def publish(client, app, case):
    response = post(
        client,
        f"/cases/{case['id']}/decisions",
        {
            "version": case["proposal"]["version"],
            "action": "approve",
        },
    )
    assert response.status_code == 200, response.text
    with app.state.sessions.begin() as session:
        dispatch_once(session)
    return detail(client, case["id"])


def patient_view(client, case):
    response = client.get(
        f"/api/v1/patient/cases/{case['id']}", headers={"X-Patient-Token": case["patient_token"]}
    )
    assert response.status_code == 200
    return response.json()


def book(client, case, step="review", **overrides):
    body = {
        "route_id": case["published_route"]["id"],
        "step_key": step,
        "slot": "tomorrow-09:00",
        **overrides,
    }
    return post(
        client, f"/patient/cases/{case['id']}/bookings", body, patient=case["patient_token"]
    )
