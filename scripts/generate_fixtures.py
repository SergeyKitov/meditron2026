"""Generate only synthetic inputs; expected decisions below are specified independently."""

import json
from pathlib import Path

from app.adapters.synthetic import make_json, make_sr

ROOT = Path(__file__).resolve().parents[1] / "fixtures"


def main():
    for folder in ("bft-json", "dicom-sr", "expected"):
        (ROOT / folder).mkdir(parents=True, exist_ok=True)
    scenarios = [
        (
            "mmg-finding",
            "MAMMOGRAPHY",
            "finding",
            "diagnostic",
            "draft",
            ["review"],
            {"mmg_rads_right": 4, "mmg_rads_left": 2},
        ),
        (
            "mmg-normal",
            "MAMMOGRAPHY",
            "normal",
            "diagnostic",
            "draft",
            [],
            {"mmg_rads_right": 1, "mmg_rads_left": 2},
        ),
        (
            "mmg-missing",
            "MAMMOGRAPHY",
            "missing",
            "diagnostic",
            "manual",
            [],
            {"mmg_rads_right": 4},
        ),
        (
            "ct-finding",
            "CT_CHEST",
            "finding",
            "diagnostic",
            "draft",
            ["review"],
            {"ct_lc_num": 1},
        ),
        ("ct-normal", "CT_CHEST", "normal", "diagnostic", "draft", [], {"ct_lc_num": 0}),
        ("ct-unknown-purpose", "CT_CHEST", "finding", "unknown", "manual", [], {"ct_lc_num": 1}),
        (
            "ct-screening",
            "CT_CHEST",
            "finding",
            "screening",
            "draft",
            ["review"],
            {"ct_lc_num": 1},
        ),
    ]
    for index, (name, modality, scenario, purpose, status, keys, facts) in enumerate(scenarios, 1):
        expected_steps = (
            [
                {"key": "review", "action_type": "consultation", "depends_on": [], "unlock_on": []},
            ]
            if keys
            else []
        )
        raw = make_json(modality, scenario, f"1.2.826.0.1.3680043.10.2026.100.{index}")
        context = {
            "encounter_ref": f"synthetic-fixture-{index}",
            "source_version": 1,
            "modality": modality,
            "exam_purpose": purpose,
        }
        (ROOT / "bft-json" / f"{name}.json").write_text(
            json.dumps(
                {
                    "profile_id": "private",
                    "context": context,
                    "report": raw,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        (ROOT / "dicom-sr" / f"{name}.dcm").write_bytes(make_sr(raw, modality))
        (ROOT / "expected" / f"{name}.json").write_text(
            json.dumps(
                {
                    "synthetic": True,
                    "status": status,
                    "step_keys": keys,
                    "step_contract": expected_steps,
                    "facts": [{"code": code, "value": value} for code, value in facts.items()],
                    "rule_status": "HYPOTHESIS",
                    "visible_before_approval": False,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
    print(f"Generated {len(scenarios)} synthetic JSON/SR pairs in {ROOT}")


if __name__ == "__main__":
    main()
