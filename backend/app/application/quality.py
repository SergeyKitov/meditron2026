"""Aggregate specialist decisions without returning report or patient content."""

from collections import defaultdict


def _route_shape(steps):
    return [
        (
            step["key"],
            step["action_type"],
            tuple(step.get("depends_on", [])),
            tuple(step.get("unlock_on", [])),
        )
        for step in steps
    ]


def _change_type(decision):
    if decision.original_steps == decision.final_steps:
        return "no_effect"
    if _route_shape(decision.original_steps) == _route_shape(decision.final_steps):
        return "wording_only"
    return "route_changed"


def aggregate_decisions(rows):
    """Rows are (Decision, Route, Case, Report); output excludes identifiers and free text."""
    groups = defaultdict(
        lambda: {
            "decisions": 0,
            "approved": 0,
            "edited": 0,
            "rejected": 0,
            "edit_types": defaultdict(int),
            "reason_codes": defaultdict(int),
        }
    )
    for decision, route, case, report in rows:
        matched = [item["rule_id"] for item in route.trace if item["matched"]]
        key = (
            report.profile_id,
            case.modality,
            report.canonical["exam_purpose"],
            route.ruleset_version,
            matched[0] if len(matched) == 1 else "NO_UNIQUE_RULE",
            "manual" if route.warnings or len(matched) != 1 else "rule",
        )
        group = groups[key]
        group["decisions"] += 1
        if decision.action == "approve":
            group["approved"] += 1
        elif decision.action == "edit_and_approve":
            group["edited"] += 1
            group["edit_types"][_change_type(decision)] += 1
            group["reason_codes"][decision.reason_code or "unspecified"] += 1
        elif decision.action == "reject":
            group["rejected"] += 1
            group["reason_codes"][decision.reason_code or "unspecified"] += 1

    result = []
    for key, group in sorted(groups.items()):
        profile_id, modality, exam_purpose, ruleset_version, rule_id, proposal_mode = key
        result.append(
            {
                "profile_id": profile_id,
                "modality": modality,
                "exam_purpose": exam_purpose,
                "ruleset_version": ruleset_version,
                "rule_id": rule_id,
                "proposal_mode": proposal_mode,
                "decisions": group["decisions"],
                "approved": group["approved"],
                "edited": group["edited"],
                "rejected": group["rejected"],
                "edit_types": dict(sorted(group["edit_types"].items())),
                "reason_codes": dict(sorted(group["reason_codes"].items())),
            }
        )
    return {
        "synthetic": True,
        "unit": "route_decisions",
        "aggregation_only": True,
        "total_decisions": sum(group["decisions"] for group in groups.values()),
        "groups": result,
    }
