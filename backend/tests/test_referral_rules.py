"""The short referral matrix uses available facts and leaves unsafe cases manual."""

import pytest
from app.adapters.reports import load_draft_pair
from app.domain.routing import CanonicalReport, Fact, evaluate


def report(modality, facts, purpose="diagnostic"):
    return CanonicalReport(
        study_uid="synthetic-test-study",
        encounter_ref="synthetic-test-encounter",
        source_version=1,
        modality=modality,
        exam_purpose=purpose,
        conclusion="Синтетическое заключение",
        facts=tuple(Fact(code, value, f"synthetic.{code}") for code, value in facts.items()),
    )


@pytest.mark.parametrize(
    ("right", "left", "specialist", "category"),
    [
        (1, 2, None, None),
        (2, 1, None, None),
        (3, 1, "специалиста по визуализации молочной железы", 3),
        (1, 3, "специалиста по визуализации молочной железы", 3),
        (4, 3, "специалиста по заболеваниям молочной железы", 4),
        (3, 4, "специалиста по заболеваниям молочной железы", 4),
        (5, 4, "специалиста по заболеваниям молочной железы", 5),
        (4, 5, "специалиста по заболеваниям молочной железы", 5),
    ],
)
def test_mammography_routes_by_higher_category(right, left, specialist, category):
    _, rules = load_draft_pair()
    proposed = evaluate(
        report("MAMMOGRAPHY", {"mmg_rads_right": right, "mmg_rads_left": left}),
        rules,
    )
    assert proposed["status"] == "draft"
    assert proposed["rule_status"] == "HYPOTHESIS"
    if specialist is None:
        assert proposed["steps"] == []
    else:
        first = proposed["steps"][0]
        assert specialist in first["title"]
        assert f"BI-RADS {category}" in first["description"]
        assert len(proposed["steps"]) == 1
        assert first["depends_on"] == first["unlock_on"] == []


@pytest.mark.parametrize("purpose", ["screening", "diagnostic"])
def test_known_ct_purpose_suggests_only_consultation(purpose):
    _, rules = load_draft_pair()
    proposed = evaluate(report("CT_CHEST", {"ct_lc_num": 1}, purpose), rules)
    assert proposed["status"] == "draft"
    first = proposed["steps"][0]
    assert "пульмонолога" in first["title"]
    assert "только число узлов" in first["description"]


def test_unknown_ct_purpose_stays_manual():
    _, rules = load_draft_pair()
    proposed = evaluate(report("CT_CHEST", {"ct_lc_num": 1}, "unknown"), rules)
    assert proposed["status"] == "manual"
    assert proposed["steps"] == []
