from datetime import datetime, timedelta, timezone
from math import ceil, isfinite


def utc_timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def booking_conversion(
    events,
    booking_routes,
    *,
    attribution_days=7,
    shown_from=None,
    shown_before=None,
    observed_at=None,
):
    """Attribute a confirmed booking to the route version first shown to a patient.

    Counts a booking only when its request and confirmation follow that exposure.
    The original booking route is used for older request events without route_id.
    """
    observed_at = observed_at or datetime.now(timezone.utc)
    exposures = {}
    requests = {}
    confirmations = {}

    for event in events:
        payload = event.payload or {}
        timestamp = utc_timestamp(event.created_at)
        booking_id = payload.get("booking_id")
        route_id = payload.get("route_id")
        if event.kind == "shown" and route_id:
            key = (event.case_id, route_id)
            exposures[key] = min(timestamp, exposures.get(key, timestamp))
        elif event.kind == "booking_requested" and booking_id:
            route_id = route_id or booking_routes.get(booking_id)
            if route_id:
                key = (event.case_id, booking_id)
                if key not in requests or timestamp < requests[key][1]:
                    requests[key] = (route_id, timestamp)
        elif event.kind == "booking_confirmed" and booking_id and route_id:
            key = (event.case_id, booking_id)
            confirmations.setdefault(key, []).append((route_id, timestamp))

    eligible = {
        key: timestamp
        for key, timestamp in exposures.items()
        if (shown_from is None or timestamp >= shown_from)
        and (shown_before is None or timestamp < shown_before)
    }
    window = timedelta(days=attribution_days)
    confirmed_by_route = {}
    for key, (requested_route, requested_at) in requests.items():
        case_id, _ = key
        exposure_key = (case_id, requested_route)
        shown_at = eligible.get(exposure_key)
        if shown_at is None or not shown_at <= requested_at <= shown_at + window:
            continue
        if any(
            confirmed_route == requested_route and requested_at <= confirmed_at <= shown_at + window
            for confirmed_route, confirmed_at in confirmations.get(key, [])
        ):
            confirmed_by_route[exposure_key] = True

    exposed = len(eligible)
    converted = len(confirmed_by_route)
    return {
        "unit": "shown_route_versions",
        "attribution_window_days": attribution_days,
        "shown_route_versions": exposed,
        "converted_route_versions": converted,
        "provisional_route_versions": sum(
            shown_at + window > observed_at and key not in confirmed_by_route
            for key, shown_at in eligible.items()
        ),
        "shown_from": shown_from.isoformat() if shown_from else None,
        "shown_before": shown_before.isoformat() if shown_before else None,
        "booking_conversion": converted / exposed if exposed else None,
    }


def patient_choice_analysis(
    events,
    *,
    attribution_days=7,
    shown_from=None,
    shown_before=None,
    observed_at=None,
):
    """Summarize explicit decisions after a route was first shown.

    The first refusal on each route step supplies its reason. A return counts
    only when it follows that refusal on the same step. A missing decision is
    never interpreted as refusal or abandonment.
    """
    observed_at = observed_at or datetime.now(timezone.utc)
    exposures = {}
    decisions = []
    for event in events:
        payload = event.payload or {}
        route_id = payload.get("route_id")
        if not route_id:
            continue
        timestamp = utc_timestamp(event.created_at)
        route_key = (event.case_id, route_id)
        if event.kind == "shown":
            exposures[route_key] = min(timestamp, exposures.get(route_key, timestamp))
        elif event.kind in ("step_declined", "step_resumed") and payload.get("step_key"):
            decisions.append((timestamp, event.kind, route_key, payload))

    eligible = {
        key: shown_at
        for key, shown_at in exposures.items()
        if shown_at <= observed_at
        and (shown_from is None or shown_at >= shown_from)
        and (shown_before is None or shown_at < shown_before)
    }
    first_declines = {}
    resumed_steps = set()
    window = timedelta(days=attribution_days)
    for timestamp, kind, route_key, payload in sorted(
        decisions, key=lambda item: (item[0], item[1] != "step_declined")
    ):
        shown_at = eligible.get(route_key)
        if shown_at is None or not shown_at <= timestamp <= min(shown_at + window, observed_at):
            continue
        step_key = (route_key, payload["step_key"])
        if kind == "step_declined":
            first_declines.setdefault(step_key, payload.get("reason_code") or "unknown")
        elif step_key in first_declines:
            resumed_steps.add(step_key)

    by_step = {}
    for (route_key, step_key), reason in first_declines.items():
        group = by_step.setdefault(
            step_key,
            {
                "step_key": step_key,
                "declined_route_steps": 0,
                "resumed_route_steps": 0,
                "first_decline_reasons": {},
            },
        )
        group["declined_route_steps"] += 1
        group["first_decline_reasons"][reason] = group["first_decline_reasons"].get(reason, 0) + 1
        if (route_key, step_key) in resumed_steps:
            group["resumed_route_steps"] += 1

    routes_with_decline = {route_key for route_key, _ in first_declines}
    routes_with_resume = {route_key for route_key, _ in resumed_steps}
    return {
        "unit": "shown_route_versions",
        "attribution_window_days": attribution_days,
        "shown_route_versions": len(eligible),
        "route_versions_with_decline": len(routes_with_decline),
        "route_versions_with_resume": len(routes_with_resume),
        "resume_rate_after_decline": (
            len(routes_with_resume) / len(routes_with_decline) if routes_with_decline else None
        ),
        "by_step": [
            {**group, "first_decline_reasons": dict(sorted(group["first_decline_reasons"].items()))}
            for _, group in sorted(by_step.items())
        ],
    }


def _latency_percentiles(values):
    ordered = sorted(values)

    def percentile(rank):
        return ordered[ceil(rank * len(ordered)) - 1] if ordered else None

    return {
        "count": len(ordered),
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
        "p99_ms": percentile(0.99),
    }


def routing_latency(reports):
    """Summarize local parsing-to-proposal times without report identifiers."""
    all_values = []
    by_modality = {}
    by_format = {}
    for report in reports:
        duration = report.processing_ms
        if duration is None or not isfinite(duration) or duration < 0:
            continue
        all_values.append(duration)
        modality = report.canonical.get("modality", "UNKNOWN")
        source_format = "dicom" if "dicom" in report.source_kind else "json"
        by_modality.setdefault(modality, []).append(duration)
        by_format.setdefault(source_format, []).append(duration)
    return {
        "unit": "ms",
        "boundary": "field_parsing_to_route_proposal_before_commit",
        **_latency_percentiles(all_values),
        "by_modality": {
            key: _latency_percentiles(values) for key, values in sorted(by_modality.items())
        },
        "by_format": {
            key: _latency_percentiles(values) for key, values in sorted(by_format.items())
        },
    }


def workflow_latency(events):
    """Measure observed route-stage intervals from persisted event timestamps."""
    timestamps = {
        kind: {} for kind in ("route_proposed", "approved", "route_rejected", "published")
    }
    for event in events:
        if event.kind not in timestamps:
            continue
        route_id = (event.payload or {}).get("route_id")
        if not route_id:
            continue
        timestamp = utc_timestamp(event.created_at)
        previous = timestamps[event.kind].get(route_id)
        if previous is None or timestamp < previous:
            timestamps[event.kind][route_id] = timestamp

    decision_durations = []
    for route_id, proposed_at in timestamps["route_proposed"].items():
        decision_times = [
            when
            for kind in ("approved", "route_rejected")
            if (when := timestamps[kind].get(route_id)) is not None
        ]
        if decision_times:
            elapsed_ms = (min(decision_times) - proposed_at).total_seconds() * 1000
            if elapsed_ms >= 0:
                decision_durations.append(round(elapsed_ms, 3))

    publication_durations = []
    for route_id, approved_at in timestamps["approved"].items():
        published_at = timestamps["published"].get(route_id)
        if published_at is not None:
            elapsed_ms = (published_at - approved_at).total_seconds() * 1000
            if elapsed_ms >= 0:
                publication_durations.append(round(elapsed_ms, 3))

    return {
        "unit": "ms",
        "boundary": "persisted_event_timestamps",
        "proposal_to_decision": _latency_percentiles(decision_durations),
        "approval_to_publication": _latency_percentiles(publication_durations),
    }
