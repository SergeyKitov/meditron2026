from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.application.metrics import patient_choice_analysis


def event(case_id, kind, route_id, at, **payload):
    return SimpleNamespace(
        case_id=case_id,
        kind=kind,
        created_at=at.isoformat(),
        payload={"route_id": route_id, **payload},
    )


def test_choice_analysis_counts_first_explicit_decision_per_shown_route_step():
    shown_at = datetime(2026, 10, 1, 10, tzinfo=timezone.utc)
    day = timedelta(days=1)
    events = [
        event(
            "case-1",
            "step_declined",
            "route-1",
            shown_at - day,
            step_key="review",
            reason_code="other",
        ),
        event("case-1", "shown", "route-1", shown_at),
        event("case-1", "shown", "route-1", shown_at + day),
        event(
            "case-1",
            "step_declined",
            "route-1",
            shown_at + day,
            step_key="review",
            reason_code="no_time",
        ),
        event("case-1", "step_resumed", "route-1", shown_at + 2 * day, step_key="review"),
        event(
            "case-1",
            "step_declined",
            "route-1",
            shown_at + 3 * day,
            step_key="review",
            reason_code="cost",
        ),
        event(
            "case-1",
            "step_declined",
            "route-1",
            shown_at + 4 * day,
            step_key="followup",
            reason_code="cost",
        ),
        event("case-2", "shown", "route-2", shown_at),
        event(
            "case-2",
            "step_declined",
            "route-2",
            shown_at + 8 * day,
            step_key="review",
            reason_code="cost",
        ),
        event(
            "case-3",
            "step_declined",
            "route-3",
            shown_at + day,
            step_key="review",
            reason_code="other",
        ),
    ]
    result = patient_choice_analysis(events, observed_at=shown_at + 10 * day)
    assert result["shown_route_versions"] == 2
    assert result["route_versions_with_decline"] == 1
    assert result["route_versions_with_resume"] == 1
    assert result["resume_rate_after_decline"] == 1.0
    assert result["by_step"] == [
        {
            "step_key": "followup",
            "declined_route_steps": 1,
            "resumed_route_steps": 0,
            "first_decline_reasons": {"cost": 1},
        },
        {
            "step_key": "review",
            "declined_route_steps": 1,
            "resumed_route_steps": 1,
            "first_decline_reasons": {"no_time": 1},
        },
    ]
    filtered = patient_choice_analysis(
        events,
        shown_from=shown_at + timedelta(hours=1),
        observed_at=shown_at + 10 * day,
    )
    assert filtered["shown_route_versions"] == 0
    assert filtered["resume_rate_after_decline"] is None
