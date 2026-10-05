import json
from dataclasses import replace
from pathlib import Path

from app.adapters.reports import from_json, from_sr, load_pair
from app.domain.routing import evaluate
from app.evaluation import counts, evaluate_fixture_pairs, rates

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def test_metrics_keep_undefined_rates_explicit():
    assert rates(counts([], []))["f1"] is None
    assert rates(counts(["a"], []))["f1"] == 0.0
    assert counts(["a", "a"], ["a", "b"]) == {
        "true_positive": 1,
        "false_positive": 1,
        "false_negative": 1,
    }


def test_evaluation_exposes_unsafe_route_and_cross_format_disagreement():
    profiles, ruleset = load_pair()
    name = "ct-unknown-purpose"
    selected = [
        (
            name,
            json.loads((FIXTURES / "bft-json" / f"{name}.json").read_text()),
            (FIXTURES / "dicom-sr" / f"{name}.dcm").read_bytes(),
            json.loads((FIXTURES / "expected" / f"{name}.json").read_text()),
        )
    ]

    def missing_json_fact(raw, context, profile):
        report = from_json(raw, context, profile)
        return replace(report, facts=())

    def unsafe_route(report, rules):
        proposal = evaluate(report, rules)
        return {**proposal, "status": "draft"}

    result = evaluate_fixture_pairs(
        selected, profiles, ruleset, missing_json_fact, from_sr, unsafe_route
    )
    assert result["fact_extraction"]["false_negative"] == 1
    assert result["routing"]["unsafe_auto_routes"] == 2
    assert result["strata"]["CT_CHEST:unknown"]["unsafe_auto_routes"] == 2
    assert result["cross_format_parity"]["mismatching_scenarios"] == 1
    assert len(result["errors"]) == 2
