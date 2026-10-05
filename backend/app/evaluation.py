"""Fixture agreement metrics, deliberately separate from clinical validation."""

from collections import Counter


def counts(expected, actual):
    """Count exact matches and both error directions for a multiset."""
    expected_items, actual_items = Counter(expected), Counter(actual)
    return {
        "true_positive": sum((expected_items & actual_items).values()),
        "false_positive": sum((actual_items - expected_items).values()),
        "false_negative": sum((expected_items - actual_items).values()),
    }


def rates(totals):
    """Undefined precision/recall stay null instead of being called perfect."""
    tp, fp, fn = (
        totals["true_positive"],
        totals["false_positive"],
        totals["false_negative"],
    )
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else None
    if precision == 0 or recall == 0:
        f1 = 0.0
    return {**totals, "precision": precision, "recall": recall, "f1": f1}


def fact_items(facts):
    """Ignore provenance pointers, which necessarily differ between JSON and SR."""
    return [(fact["code"], repr(fact["value"]), fact.get("unit")) for fact in facts]


def step_contract(steps):
    """Compare action and transition semantics as well as the visible step key."""
    return [
        {
            "key": step["key"],
            "action_type": step["action_type"],
            "depends_on": step.get("depends_on", []),
            "unlock_on": step.get("unlock_on", []),
        }
        for step in steps
    ]


def evaluate_fixture_pairs(
    fixtures, profiles, ruleset, parse_json, parse_sr, route, config_release_id=None
):
    """Run independent expected fixture labels against both representations."""
    total_facts = counts([], [])
    total_steps = counts([], [])
    cases = 0
    exact_facts = 0
    exact_routes = 0
    exact_step_contracts = 0
    status_correct = 0
    expected_manual = 0
    manual_caught = 0
    unsafe_auto_routes = 0
    unnecessary_abstentions = 0
    parity_mismatches = 0
    strata = {}
    errors = []

    for name, json_data, sr_data, expected in fixtures:
        if not expected.get("synthetic"):
            raise ValueError(f"{name}: expected fixture must be synthetic")
        if expected["status"] not in ("draft", "manual"):
            raise ValueError(f"{name}: unknown expected route status")
        if expected["status"] == "manual" and expected["step_keys"]:
            raise ValueError(f"{name}: manual route cannot have expected steps")
        expected_facts = fact_items(expected["facts"])
        expected_contract = expected["step_contract"]
        if [step["key"] for step in expected_contract] != expected["step_keys"]:
            raise ValueError(f"{name}: expected step contract disagrees with step keys")
        if len(expected_facts) != len(set(expected_facts)):
            raise ValueError(f"{name}: duplicate expected fact")
        outputs = []
        context = json_data["context"]
        stratum_key = f"{context['modality']}:{context['exam_purpose']}"
        stratum = strata.setdefault(
            stratum_key,
            {
                "scenarios": 0,
                "representations": 0,
                "exact_facts": 0,
                "exact_routes": 0,
                "unsafe_auto_routes": 0,
            },
        )
        stratum["scenarios"] += 1
        for source_format, report in (
            ("json", parse_json(json_data["report"], context, profiles["private"])),
            ("dicom_sr", parse_sr(sr_data, context, profiles["pacs"])),
        ):
            proposal = route(report, ruleset)
            actual_facts = fact_items(report.to_dict()["facts"])
            actual_steps = [step["key"] for step in proposal["steps"]]
            actual_status = proposal["status"]
            actual_contract = step_contract(proposal["steps"])
            outputs.append((sorted(actual_facts), actual_status, actual_contract))
            cases += 1
            stratum["representations"] += 1
            fact_score = counts(expected_facts, actual_facts)
            for key in total_facts:
                total_facts[key] += fact_score[key]
            fact_equal = fact_score["false_positive"] == fact_score["false_negative"] == 0
            exact_facts += fact_equal
            stratum["exact_facts"] += fact_equal
            status_equal = actual_status == expected["status"]
            status_correct += status_equal
            route_equal = status_equal and actual_steps == expected["step_keys"]
            exact_routes += route_equal
            stratum["exact_routes"] += route_equal
            contract_equal = actual_contract == expected_contract
            exact_step_contracts += contract_equal
            if expected["status"] == "manual":
                expected_manual += 1
                manual_caught += actual_status == "manual"
                unsafe_auto_routes += actual_status != "manual"
                stratum["unsafe_auto_routes"] += actual_status != "manual"
            else:
                unnecessary_abstentions += actual_status == "manual"
                step_score = counts(expected["step_keys"], actual_steps)
                for key in total_steps:
                    total_steps[key] += step_score[key]
            if not (fact_equal and route_equal and contract_equal):
                errors.append(
                    {
                        "fixture": name,
                        "format": source_format,
                        "fact_errors": fact_score,
                        "expected_status": expected["status"],
                        "actual_status": actual_status,
                        "expected_step_keys": expected["step_keys"],
                        "actual_step_keys": actual_steps,
                        "expected_step_contract": expected_contract,
                        "actual_step_contract": actual_contract,
                    }
                )
        if outputs[0] != outputs[1]:
            parity_mismatches += 1

    scenario_count = cases // 2
    return {
        "schema_version": 1,
        "evidence_level": "synthetic_fixture_agreement_only",
        "configuration": {
            "release_id": config_release_id,
            "ruleset_version": ruleset["version"],
            "profile_versions": {
                profile_id: profiles[profile_id]["version"] for profile_id in ("private", "pacs")
            },
        },
        "sample": {"scenarios": scenario_count, "representations": cases},
        "strata": dict(sorted(strata.items())),
        "fact_extraction": {**rates(total_facts), "exact_representations": exact_facts},
        "routing": {
            "status_correct": status_correct,
            "exact_representations": exact_routes,
            "exact_step_contract_representations": exact_step_contracts,
            "expected_manual": expected_manual,
            "manual_caught": manual_caught,
            "unsafe_auto_routes": unsafe_auto_routes,
            "unnecessary_abstentions": unnecessary_abstentions,
            "step_keys_on_expected_drafts": rates(total_steps),
        },
        "cross_format_parity": {
            "matching_scenarios": scenario_count - parity_mismatches,
            "mismatching_scenarios": parity_mismatches,
        },
        "errors": errors,
    }
