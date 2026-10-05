"""Demo inputs should show distinct routes without inventing patient data."""

import pytest
from conftest import create, patient_view, post, publish


@pytest.mark.parametrize(
    ("modality", "scenario", "expected_fact", "expected_title"),
    [
        ("CT_CHEST", "normal", 0, None),
        ("CT_CHEST", "finding", 1, "пульмонолога"),
        ("CT_CHEST", "multiple", 3, "пульмонолога"),
        ("MAMMOGRAPHY", "normal", 1, None),
        ("MAMMOGRAPHY", "followup", 3, "визуализации"),
        ("MAMMOGRAPHY", "finding", 4, "молочной железы"),
        ("MAMMOGRAPHY", "priority", 5, "Приоритетная"),
    ],
)
def test_distinct_synthetic_inputs_and_patient_outcomes(
    client, app, modality, scenario, expected_fact, expected_title
):
    case = create(client, modality=modality, scenario=scenario)
    facts = {item["code"]: item["value"] for item in case["report"]["facts"]}
    fact_code = "ct_lc_num" if modality == "CT_CHEST" else "mmg_rads_right"
    assert facts[fact_code] == expected_fact
    assert patient_view(client, case)["route"] is None
    if expected_title is None:
        assert case["proposal"]["steps"] == []
    else:
        assert expected_title in case["proposal"]["steps"][0]["title"]

    published = publish(client, app, case)
    patient = patient_view(client, published)
    assert len(patient["route"]["steps"]) == (0 if expected_title is None else 1)
    listed = client.get("/api/v1/cases").json()
    assert (
        next(item for item in listed if item["id"] == case["id"])["conclusion"]
        == case["report"]["conclusion"]
    )


def test_scenario_cannot_cross_modality(client):
    response = post(
        client,
        "/demo/cases",
        {"modality": "CT_CHEST", "scenario": "priority"},
    )
    assert response.status_code == 422
    assert "не подходит" in response.json()["detail"]
