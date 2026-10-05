"""Versioned CatBoost proposal from canonical SR facts, with explicit abstention."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from app.domain.routing import CanonicalReport, DomainError, validate_steps

ARTIFACT_DIR = Path(__file__).resolve().parents[3] / "config" / "model"
MISSING_NUMBER = -1.0


@lru_cache(maxsize=1)
def load_model():
    from catboost import CatBoostClassifier

    try:
        manifest = json.loads((ARTIFACT_DIR / "manifest.json").read_text())
        model_path = ARTIFACT_DIR / "route.cbm"
        artifact_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
        if artifact_sha256 != manifest["artifact_sha256"]:
            raise DomainError("Контрольная сумма модели маршрутизации не совпадает", 503)
        model = CatBoostClassifier()
        model.load_model(str(model_path))
    except (OSError, ValueError, KeyError) as exc:
        raise DomainError("Опубликованная модель маршрутизации недоступна", 503) from exc
    if manifest.get("schema_version") != 1 or list(model.classes_) != manifest["classes"]:
        raise DomainError("Версия модели маршрутизации не соответствует манифесту", 503)
    return model, manifest


def feature_row(report: CanonicalReport):
    facts = {fact.code: fact for fact in report.facts}
    return [
        report.modality,
        report.exam_purpose,
        float(facts["mmg_rads_right"].value) if "mmg_rads_right" in facts else MISSING_NUMBER,
        float(facts["mmg_rads_left"].value) if "mmg_rads_left" in facts else MISSING_NUMBER,
        float(facts["ct_lc_num"].value) if "ct_lc_num" in facts else MISSING_NUMBER,
    ]


def predict_route(report: CanonicalReport) -> dict:
    from catboost import Pool

    model, manifest = load_model()
    facts = {fact.code: fact for fact in report.facts}
    warnings = list(report.warnings)
    required = manifest["required_fields"].get(report.modality)
    if required is None:
        warnings.append("Модальность не поддерживается моделью")
    else:
        for code in required:
            if code not in facts:
                warnings.append(f"Нет обязательного факта: {code}")
    if report.modality == "CT_CHEST" and report.exam_purpose == "unknown":
        warnings.append("Неизвестно назначение КТ: выбор пути передан специалисту")
    if report.exam_purpose not in ("screening", "diagnostic", "unknown"):
        warnings.append("Неизвестное назначение исследования")
    if warnings:
        return {
            "status": "manual",
            "steps": [],
            "trace": [],
            "warnings": warnings,
            "ruleset_version": manifest["version"],
            "rule_status": "HYPOTHESIS",
        }

    row = feature_row(report)
    pool = Pool([row], cat_features=[0, 1], feature_names=manifest["features"])
    probabilities = model.predict_proba(pool)[0]
    index = int(probabilities.argmax())
    label = manifest["classes"][index]
    score = float(probabilities[index])
    if score < manifest["abstain_below"]:
        return {
            "status": "manual",
            "steps": [],
            "trace": [],
            "warnings": [
                "Модель не выбрала достаточно устойчивый вариант; требуется решение специалиста"
            ],
            "ruleset_version": manifest["version"],
            "rule_status": "HYPOTHESIS",
        }
    # Contributions describe the model's prediction, not clinical causality.
    shap = model.get_feature_importance(pool, type="ShapValues")[0, index, :-1]
    visible = [
        (feature, float(shap[position]))
        for position, feature in enumerate(manifest["features"])
        if feature in facts or feature in ("modality", "exam_purpose")
    ]
    visible.sort(key=lambda item: abs(item[1]), reverse=True)
    checks = []
    for feature, impact in visible[:3]:
        actual = (
            report.modality
            if feature == "modality"
            else report.exam_purpose
            if feature == "exam_purpose"
            else facts[feature].value
        )
        checks.append(
            {
                "field": feature,
                "actual": actual,
                "op": "model_contribution",
                "expected": None,
                "passed": True,
                "source_pointer": facts[feature].source_pointer
                if feature in facts
                else f"context.{feature}",
                "impact": round(impact, 4),
            }
        )
    steps = manifest["outputs"][label]
    validate_steps(steps)
    return {
        "status": "draft",
        "steps": steps,
        "trace": [
            {
                "rule_id": f"MODEL:{label}",
                "matched": True,
                "checks": checks,
                "model_score": round(score, 4),
            }
        ],
        "warnings": [],
        "ruleset_version": manifest["version"],
        "rule_status": "HYPOTHESIS",
    }
