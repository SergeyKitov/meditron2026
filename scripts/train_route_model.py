"""Build a synthetic CatBoost teacher replica. Never run on patient reports."""

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from catboost import CatBoostClassifier, Pool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.domain.model_routing import ARTIFACT_DIR, feature_row  # noqa: E402
from app.domain.routing import CanonicalReport, Fact, evaluate_rules  # noqa: E402


def report(modality, purpose, right=None, left=None, count=None):
    values = {"mmg_rads_right": right, "mmg_rads_left": left, "ct_lc_num": count}
    return CanonicalReport(
        "synthetic-training",
        "synthetic-training",
        1,
        modality,
        purpose,
        "Синтетический обучающий пример",
        tuple(
            Fact(code, value, f"synthetic.{code}")
            for code, value in values.items()
            if value is not None
        ),
    )


def main():
    rules = json.loads((ROOT / "config" / "rules.json").read_text())
    cases = [
        report("MAMMOGRAPHY", purpose, right, left)
        for purpose in ("screening", "diagnostic")
        for right in range(1, 6)
        for left in range(1, 6)
    ]
    cases.extend(
        report("CT_CHEST", purpose, count=count)
        for purpose in ("screening", "diagnostic")
        for count in (0, 1, 2, 3, 4, 5, 8, 12, 25, 50, 100, 500, 1000)
    )
    serialized = {}
    outputs = {}
    labels = []
    for case in cases:
        proposal = evaluate_rules(case, rules)
        if proposal["status"] != "draft":
            raise RuntimeError("Teacher did not label a synthetic training case")
        key = json.dumps(proposal["steps"], ensure_ascii=False, sort_keys=True)
        if key not in serialized:
            label = f"route_{len(serialized)}"
            serialized[key] = label
            outputs[label] = proposal["steps"]
        labels.append(serialized[key])
    rows = [feature_row(case) for case in cases]
    features = ["modality", "exam_purpose", "mmg_rads_right", "mmg_rads_left", "ct_lc_num"]
    pool = Pool(rows, labels, cat_features=[0, 1], feature_names=features)
    model = CatBoostClassifier(
        loss_function="MultiClass",
        iterations=900,
        depth=5,
        learning_rate=0.045,
        l2_leaf_reg=1,
        random_seed=20261005,
        verbose=False,
        thread_count=2,
        allow_writing_files=False,
    )
    model.fit(pool)
    predicted = [str(value) for value in model.predict(pool).reshape(-1)]
    fidelity = sum(actual == expected for actual, expected in zip(predicted, labels)) / len(labels)
    if fidelity < 1:
        raise RuntimeError(f"Teacher fidelity is {fidelity:.3f}; publication stopped")
    ARTIFACT_DIR.mkdir(exist_ok=True)
    model.save_model(str(ARTIFACT_DIR / "route.cbm"))
    source_hash = hashlib.sha256((ROOT / "config" / "rules.json").read_bytes()).hexdigest()
    manifest = {
        "schema_version": 1,
        "version": "catboost-synthetic-2026.10.05-v1",
        "source": "synthetic_teacher_only",
        "source_sha256": source_hash,
        "artifact_sha256": hashlib.sha256((ARTIFACT_DIR / "route.cbm").read_bytes()).hexdigest(),
        "clinical_validation": False,
        "features": features,
        "required_fields": {
            "MAMMOGRAPHY": ["mmg_rads_right", "mmg_rads_left"],
            "CT_CHEST": ["ct_lc_num"],
        },
        "classes": [str(value) for value in model.classes_],
        "outputs": outputs,
        "abstain_below": 0.5,
        "training_cases": len(cases),
        "training_class_counts": dict(sorted(Counter(labels).items())),
        "synthetic_teacher_fidelity": fidelity,
        "independent_clinical_score": None,
    }
    (ARTIFACT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {"version": manifest["version"], "cases": len(cases), "teacher_fidelity": fidelity}
        )
    )


if __name__ == "__main__":
    main()
