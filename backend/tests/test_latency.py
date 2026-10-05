from types import SimpleNamespace

from app.application.metrics import routing_latency, workflow_latency
from app.persistence.models import Report
from conftest import create, publish
from sqlalchemy import select


def test_nearest_rank_latency_percentiles_and_groups():
    reports = [
        SimpleNamespace(
            processing_ms=value,
            canonical={"modality": "MAMMOGRAPHY" if index < 3 else "CT_CHEST"},
            source_kind="json" if index % 2 == 0 else "signed_dicom",
        )
        for index, value in enumerate([10.0, 20.0, 30.0, 40.0, 50.0])
    ]
    summary = routing_latency(reports)
    assert (summary["count"], summary["p50_ms"], summary["p95_ms"], summary["p99_ms"]) == (
        5,
        30.0,
        50.0,
        50.0,
    )
    assert summary["by_modality"]["CT_CHEST"]["count"] == 2
    assert summary["by_format"]["dicom"]["p95_ms"] == 40.0
    assert routing_latency([])["p95_ms"] is None


def test_successful_report_has_duration_and_duplicate_does_not_add_sample(client, app):
    case = create(client)
    with app.state.sessions.begin() as session:
        report = session.scalar(select(Report).where(Report.case_id == case["id"]))
        assert report.processing_ms is not None and report.processing_ms >= 0
    stats = client.get("/api/v1/metrics").json()["routing_latency"]
    assert stats["count"] == 1
    assert stats["by_modality"]["MAMMOGRAPHY"]["count"] == 1
    assert stats["by_format"]["json"]["count"] == 1


def test_workflow_stage_intervals_pair_events_by_route_version():
    def event(kind, route_id, second):
        return SimpleNamespace(
            kind=kind,
            case_id="case-1",
            payload={"route_id": route_id},
            created_at=f"2026-10-04T12:00:{second:02d}+00:00",
        )

    summary = workflow_latency(
        [
            event("route_proposed", "route-a", 0),
            event("approved", "route-a", 2),
            event("published", "route-a", 3),
            event("route_proposed", "route-b", 0),
            event("route_rejected", "route-b", 4),
            event("route_proposed", "route-c", 5),
            event("approved", "route-c", 4),  # Invalid negative interval is excluded.
            event("approved", "route-a", 5),  # Repeated event does not replace first.
        ]
    )
    assert summary["proposal_to_decision"] == {
        "count": 2,
        "p50_ms": 2000.0,
        "p95_ms": 4000.0,
        "p99_ms": 4000.0,
    }
    assert summary["approval_to_publication"] == {
        "count": 1,
        "p50_ms": 1000.0,
        "p95_ms": 1000.0,
        "p99_ms": 1000.0,
    }


def test_metrics_include_review_and_publication_intervals(client, app):
    case = publish(client, app, create(client))
    assert case["published_route"] is not None
    stats = client.get("/api/v1/metrics").json()["workflow_latency"]
    assert stats["proposal_to_decision"]["count"] == 1
    assert stats["approval_to_publication"]["count"] == 1
    assert stats["proposal_to_decision"]["p95_ms"] >= 0
    assert stats["approval_to_publication"]["p95_ms"] >= 0
