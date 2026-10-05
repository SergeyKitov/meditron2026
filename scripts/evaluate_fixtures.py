"""Evaluate the committed synthetic oracle, not medical correctness."""

import json
import sys
from pathlib import Path

from app.adapters.reports import from_json, from_sr, load_pair_with_release
from app.domain.routing import evaluate
from app.evaluation import evaluate_fixture_pairs

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


def fixture_pairs():
    names = {path.stem for path in (FIXTURES / "bft-json").glob("*.json")}
    sr_names = {path.stem for path in (FIXTURES / "dicom-sr").glob("*.dcm")}
    expected_names = {path.stem for path in (FIXTURES / "expected").glob("*.json")}
    if not names or names != sr_names or names != expected_names:
        raise ValueError("Synthetic JSON, SR and expected fixture names must match and be nonempty")
    for name in sorted(names):
        path = FIXTURES / "bft-json" / f"{name}.json"
        sr_path = FIXTURES / "dicom-sr" / f"{path.stem}.dcm"
        expected_path = FIXTURES / "expected" / path.name
        yield (
            name,
            json.loads(path.read_text()),
            sr_path.read_bytes(),
            json.loads(expected_path.read_text()),
        )


def main():
    profiles, ruleset, release_id = load_pair_with_release()
    result = evaluate_fixture_pairs(
        fixture_pairs(), profiles, ruleset, from_json, from_sr, evaluate, release_id
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["errors"] or result["cross_format_parity"]["mismatching_scenarios"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
