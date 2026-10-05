import base64
import time

from sqlalchemy import select

from app.adapters.reports import from_json, from_sr, profile_with_rules_release
from app.adapters.synthetic import make_json, make_sr
from app.application.service import ingest
from app.persistence.db import database
from app.persistence.models import Case


def main():
    _, sessions = database()
    examples = [
        ("private", "CT_CHEST", "unknown", "finding"),
        ("pacs", "CT_CHEST", "diagnostic", "finding"),
        ("private", "MAMMOGRAPHY", "diagnostic", "finding"),
        ("private", "CT_CHEST", "diagnostic", "normal"),
        ("private", "CT_CHEST", "diagnostic", "finding"),
        ("pacs", "CT_CHEST", "screening", "multiple"),
        ("pacs", "MAMMOGRAPHY", "screening", "normal"),
        ("private", "MAMMOGRAPHY", "screening", "followup"),
        ("private", "MAMMOGRAPHY", "diagnostic", "priority"),
    ]
    created = 0
    with sessions.begin() as session:
        for i, (profile_id, modality, purpose, scenario) in enumerate(examples, start=1):
            study_uid = f"1.2.826.0.1.3680043.10.2026.{i}"
            if session.scalar(select(Case.id).where(Case.study_uid == study_uid)):
                continue
            raw = make_json(modality, scenario, study_uid=study_uid)
            context = {
                "encounter_ref": f"synthetic-encounter-{i}",
                "source_version": 1,
                "modality": modality,
                "exam_purpose": purpose,
            }
            profile, ruleset, release_id = profile_with_rules_release(profile_id)
            if profile["input"] == "dicom":
                content = make_sr(raw, modality)
                started_ns = time.perf_counter_ns()
                report, source = (
                    from_sr(content, context, profile),
                    {"base64": base64.b64encode(content).decode()},
                )
            else:
                started_ns = time.perf_counter_ns()
                report, source = from_json(raw, context, profile), raw
            ingest(
                session,
                report,
                profile_id,
                profile["input"],
                source,
                profile=profile,
                ruleset=ruleset,
                config_release_id=release_id,
                started_ns=started_ns,
            )
            created += 1
    print(f"Добавлено {created} синтетических случаев; существующие сохранены")


if __name__ == "__main__":
    main()
