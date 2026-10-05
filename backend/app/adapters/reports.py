"""Configurable demo adapters. The SR profile uses explicitly local ZDEMO codes."""

import hashlib
import io
import json
import re
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pydicom

from app.adapters.configuration import validate_pair, validate_profiles, validate_rules
from app.domain.routing import CanonicalReport, DomainError, Fact

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config"


@lru_cache(maxsize=8)
def _read_config(name, contents):
    try:
        data = json.loads(contents)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DomainError(f"Не удалось прочитать конфигурацию {name}: {exc}", 422) from exc
    if name == "profiles.json":
        validate_profiles(data)
    elif name == "rules.json":
        validate_rules(data)
    return data


def load_config(name):
    if name not in ("profiles.json", "rules.json"):
        raise DomainError("Неизвестный файл конфигурации", 422)
    profiles, ruleset = load_pair()
    return profiles if name == "profiles.json" else ruleset


def load_draft_config(name, config_dir=None):
    if name not in ("profiles.json", "rules.json"):
        raise DomainError("Неизвестный файл конфигурации", 422)
    try:
        contents = ((config_dir or CONFIG) / name).read_bytes()
    except OSError as exc:
        raise DomainError(f"Файл конфигурации {name} недоступен", 422) from exc
    return deepcopy(_read_config(name, contents))


def load_draft_pair(config_dir=None) -> tuple[dict, dict]:
    profiles = load_draft_config("profiles.json", config_dir)
    ruleset = load_draft_config("rules.json", config_dir)
    validate_pair(profiles, ruleset)
    return profiles, ruleset


@lru_cache(maxsize=8)
def _read_release(contents: bytes) -> dict:
    try:
        release = json.loads(contents)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DomainError("Некорректный опубликованный релиз конфигурации", 422) from exc
    if (
        not isinstance(release, dict)
        or set(release)
        != {"schema_version", "release_id", "published_at", "author", "reason", "profiles", "rules"}
        or release["schema_version"] != 1
        or not isinstance(release["profiles"], dict)
        or not isinstance(release["rules"], dict)
    ):
        raise DomainError("Неизвестный формат релиза конфигурации", 422)
    validate_pair(release["profiles"], release["rules"])
    return release


def load_pair() -> tuple[dict, dict]:
    profiles, ruleset, _ = load_pair_with_release()
    return profiles, ruleset


def load_pair_with_release() -> tuple[dict, dict, str | None]:
    active_path = CONFIG / "active-release.json"
    try:
        pointer = json.loads(active_path.read_bytes())
    except FileNotFoundError:
        profiles, ruleset = load_draft_pair()
        return profiles, ruleset, None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DomainError("Не удалось прочитать активный релиз конфигурации", 422) from exc
    if not isinstance(pointer, dict) or set(pointer) != {"schema_version", "release_id", "sha256"}:
        raise DomainError("Некорректный указатель на релиз конфигурации", 422)
    release_id, expected_hash = pointer["release_id"], pointer["sha256"]
    if (
        pointer["schema_version"] != 1
        or not isinstance(release_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", release_id) is None
        or not isinstance(expected_hash, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
    ):
        raise DomainError("Некорректный указатель на релиз конфигурации", 422)
    try:
        contents = (CONFIG / "releases" / f"{release_id}.json").read_bytes()
    except OSError as exc:
        raise DomainError("Опубликованный релиз конфигурации недоступен", 422) from exc
    if hashlib.sha256(contents).hexdigest() != expected_hash:
        raise DomainError("Контрольная сумма релиза конфигурации не совпадает", 422)
    release = _read_release(contents)
    if release["release_id"] != release_id:
        raise DomainError("ID опубликованного релиза не совпадает", 422)
    return deepcopy(release["profiles"]), deepcopy(release["rules"]), release_id


def profile_with_rules(profile_id: str) -> tuple[dict, dict]:
    profile, ruleset, _ = profile_with_rules_release(profile_id)
    return profile, ruleset


def profile_with_rules_release(profile_id: str) -> tuple[dict, dict, str | None]:
    profiles, ruleset, release_id = load_pair_with_release()
    if profile_id not in profiles:
        raise DomainError("Неизвестный профиль интеграции", 422)
    return profiles[profile_id], ruleset, release_id


def profile_by_id(profile_id: str) -> dict:
    return profile_with_rules(profile_id)[0]


PATH_PART = re.compile(
    r"(?P<name>[A-Za-z_][A-Za-z0-9_-]*)(?:\[(?:(?P<index>0|[1-9][0-9]*)|(?P<filter_field>[A-Za-z_][A-Za-z0-9_-]*)=(?P<filter_value>[A-Za-z0-9_-]+))\])?\Z"
)


def resolve_path(payload, path):
    """Resolve a configured JSON selector and its concrete source pointer."""
    value = payload
    pointer = []
    for part in path.split("."):
        match = PATH_PART.fullmatch(part)
        if match is None:
            raise DomainError("Недопустимый путь к полю JSON", 422)
        name = match.group("name")
        if not isinstance(value, dict) or name not in value:
            return None, None
        value = value[name]
        if match.group("index") is not None:
            index = int(match.group("index"))
            if not isinstance(value, list) or index >= len(value):
                return None, None
            value = value[index]
            pointer.append(f"{name}[{index}]")
        elif match.group("filter_field") is not None:
            if not isinstance(value, list):
                return None, None
            field, expected = match.group("filter_field", "filter_value")
            matches = [
                (index, item)
                for index, item in enumerate(value)
                if isinstance(item, dict) and item.get(field) == expected
            ]
            if len(matches) > 1:
                raise DomainError(f"Неоднозначный JSON-селектор: {path}", 422)
            if not matches:
                return None, None
            index, value = matches[0]
            pointer.append(f"{name}[{index}]")
        else:
            pointer.append(name)
    return value, ".".join(pointer)


def select_path(payload, path):
    return resolve_path(payload, path)[0]


def typed_fact(code, value, selector, spec):
    if value is None:
        return None
    if spec["type"] == "integer":
        if type(value) is not int or not spec["min"] <= value <= spec["max"]:
            raise DomainError(
                f"Поле {code}: ожидается целое в диапазоне {spec['min']}–{spec['max']}", 422
            )
    elif spec["type"] == "number":
        if type(value) not in (int, float) or not spec["min"] <= value <= spec["max"]:
            raise DomainError(f"Недопустимое числовое значение {code}", 422)
    return Fact(code, value, selector, spec.get("unit"))


def from_json(raw: dict, context: dict, profile: dict) -> CanonicalReport:
    if raw.get("synthetic") is not True:
        raise DomainError("Этот контур принимает только синтетические данные", 422)
    if context["modality"] not in profile["fields"]:
        raise DomainError("Профиль не поддерживает эту модальность", 422)
    study = select_path(raw, profile["study_path"])
    conclusion = select_path(raw, profile["conclusion_path"])
    if not isinstance(study, str) or not study or not isinstance(conclusion, str):
        raise DomainError("Не найдены UID исследования или заключение", 422)
    facts = []
    for code, spec in profile["fields"][context["modality"]].items():
        value, pointer = resolve_path(raw, spec["path"])
        fact = typed_fact(code, value, pointer, spec)
        if fact:
            facts.append(fact)
    return CanonicalReport(
        study,
        context["encounter_ref"],
        context["source_version"],
        context["modality"],
        context["exam_purpose"],
        conclusion,
        tuple(facts),
    )


def from_sr(content: bytes, context: dict, profile: dict) -> CanonicalReport:
    try:
        ds = pydicom.dcmread(io.BytesIO(content))
    except Exception as exc:
        raise DomainError("Не удалось прочитать DICOM SR", 422) from exc
    if str(getattr(ds, "PatientID", "")) != "SYNTHETIC":
        raise DomainError("Принимаются только SR демонстрационного профиля SYNTHETIC", 422)
    if str(getattr(ds, "Modality", "")) != "SR" or not hasattr(ds, "ContentSequence"):
        raise DomainError("Ожидается DICOM Structured Report", 422)
    items = {}

    def walk(node, path):
        for i, item in enumerate(getattr(node, "ContentSequence", [])):
            pointer = f"{path}.ContentSequence[{i}]"
            names = getattr(item, "ConceptNameCodeSequence", [])
            if names:
                name = names[0]
                if name.CodingSchemeDesignator == profile.get("sr_scheme", "ZDEMO"):
                    code = str(name.CodeValue)
                    if code in items:
                        raise DomainError(f"Неоднозначное поле SR: {code}", 422)
                    value = None
                    if item.ValueType == "NUM":
                        measured = item.MeasuredValueSequence[0]
                        value = float(measured.NumericValue)
                        units = measured.MeasurementUnitsCodeSequence[0]
                        unit = str(units.CodeValue)
                    elif item.ValueType == "TEXT":
                        value, unit = str(item.TextValue), None
                    else:
                        unit = None
                    items[code] = (value, pointer, unit)
            walk(item, pointer)

    try:
        walk(ds, "SR")
        facts = []
        for code, spec in profile["fields"][context["modality"]].items():
            value, pointer, unit = items.get(spec.get("sr_code", code), (None, None, None))
            if value is not None and spec.get("unit", "1") != unit:
                raise DomainError(f"Неожиданная единица измерения SR: {code}", 422)
            if spec["type"] == "integer" and isinstance(value, float) and value.is_integer():
                value = int(value)
            fact = typed_fact(code, value, pointer, spec)
            if fact:
                facts.append(fact)
        conclusion = items.get(profile.get("sr_conclusion_code", "conclusion"), (None,))[0]
        if not isinstance(conclusion, str):
            raise DomainError("В SR отсутствует заключение", 422)
        study = str(ds.StudyInstanceUID)
    except (AttributeError, IndexError, KeyError, ValueError) as exc:
        raise DomainError("SR не соответствует демонстрационному профилю", 422) from exc
    return CanonicalReport(
        study,
        context["encounter_ref"],
        context["source_version"],
        context["modality"],
        context["exam_purpose"],
        conclusion,
        tuple(facts),
    )
