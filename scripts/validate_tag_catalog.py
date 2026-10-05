"""Check the draft referral catalog without activating it in routing rules."""

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "docs" / "tag.json"


def main() -> None:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    entries = data["entries"]
    assert data["status"] == "HYPOTHESIS_MEDICAL_APPROVAL_REQUIRED"
    assert data["usage_policy"]["execution_state"] == "REFERENCE_CATALOG_NOT_LOADED_AT_RUNTIME"
    assert 1 <= len(entries) <= 10, "Первая выборка должна содержать не более 10 сценариев"

    ids = [entry["id"] for entry in entries]
    assert len(ids) == len(set(ids)), "Повторяются идентификаторы сценариев"

    references = set(data["source_registry"])
    allowed_modes = {"no_new_step", "candidate_for_review", "manual_only", "urgent_handoff"}
    allowed_priorities = {"routine", "prompt", "urgent"}
    for entry in entries:
        assert entry["routing_mode"] in allowed_modes, entry["id"]
        assert entry["priority_for_review"] in allowed_priorities, entry["id"]
        assert entry["references"] and set(entry["references"]) <= references, entry["id"]
        assert entry["reason_for_route"].strip(), entry["id"]
        assert entry["first_step_candidate"].strip(), entry["id"]
        assert entry["signal"]["mapping_status"], entry["id"]
        if entry["routing_mode"] == "candidate_for_review":
            assert entry["specialist_candidates"], entry["id"]
            assert entry["signal"]["mapping_status"] == "field_available_catalog_not_executed"
            assert entry["patient_text_template"], entry["id"]
        else:
            assert entry["patient_text_template"] is None, entry["id"]
        if entry["routing_mode"] in {"no_new_step", "urgent_handoff"}:
            assert entry["next_step_gate"] is None or entry["routing_mode"] == "urgent_handoff"

    sections = Counter(entry["section"] for entry in entries)
    print(f"Каталог корректен: {len(entries)} сценариев; разделы: {dict(sections)}")


if __name__ == "__main__":
    main()
