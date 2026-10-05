import json
from pathlib import Path

import pytest
from app.adapters.reports import from_json, from_sr, load_config, profile_by_id
from app.domain.routing import evaluate
from app.evaluation import counts, fact_items, step_contract

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.mark.parametrize(
    "path", sorted((FIXTURES / "bft-json").glob("*.json")), ids=lambda p: p.stem
)
def test_committed_fixtures(path):
    data = json.loads(path.read_text())
    expected = json.loads((FIXTURES / "expected" / path.name).read_text())
    reports = [
        from_json(data["report"], data["context"], profile_by_id("private")),
        from_sr(
            (FIXTURES / "dicom-sr" / f"{path.stem}.dcm").read_bytes(),
            data["context"],
            profile_by_id("pacs"),
        ),
    ]
    for report in reports:
        proposal = evaluate(report, load_config("rules.json"))
        fact_score = counts(fact_items(expected["facts"]), fact_items(report.to_dict()["facts"]))
        assert fact_score["false_positive"] == fact_score["false_negative"] == 0
        assert proposal["status"] == expected["status"]
        assert [s["key"] for s in proposal["steps"]] == expected["step_keys"]
        assert step_contract(proposal["steps"]) == expected["step_contract"]
        assert proposal["rule_status"] == expected["rule_status"]
