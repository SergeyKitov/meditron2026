"""Validate technical profiles and the demo rules before they can affect routing."""

import re
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from app.domain.routing import DomainError, validate_steps

CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
PROFILE_ID = re.compile(r"[a-z][a-z0-9_-]{0,49}\Z")
PATH_NAME = r"[A-Za-z_][A-Za-z0-9_-]*"
PATH_SEGMENT = rf"{PATH_NAME}(?:\[(?:0|[1-9][0-9]*|{PATH_NAME}=[A-Za-z0-9_-]+)\])?"
PATH = re.compile(rf"{PATH_SEGMENT}(?:\.{PATH_SEGMENT})*\Z")


class StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldMapping(StrictConfig):
    path: str = Field(min_length=1, max_length=256)
    type: Literal["integer", "number"]
    min: StrictInt | StrictFloat
    max: StrictInt | StrictFloat
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    sr_code: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def check_bounds(self):
        if not PATH.fullmatch(self.path):
            raise ValueError("path должен содержать имена полей, индекс или фильтр массива")
        if self.min > self.max:
            raise ValueError("min больше max")
        if self.type == "integer" and (type(self.min) is not int or type(self.max) is not int):
            raise ValueError("целочисленному полю нужны целочисленные границы")
        return self


class HmacSource(StrictConfig):
    auth: Literal["hmac_sha256"]
    secret_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,127}$")
    max_clock_skew_seconds: StrictInt = Field(ge=1, le=300)


class IntegrationProfile(StrictConfig):
    label: str = Field(min_length=1, max_length=150)
    clinic_id: str = Field(min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_-]{0,49}$")
    input: Literal["json", "dicom"]
    study_path: str = Field(min_length=1, max_length=256)
    conclusion_path: str = Field(min_length=1, max_length=256)
    fields: dict[Literal["MAMMOGRAPHY", "CT_CHEST"], dict[str, FieldMapping]]
    services: dict[str, str]
    version: str = Field(min_length=1, max_length=60)
    booking_mode: Literal["local_simulator", "deferred_simulator"]
    sr_scheme: str | None = Field(default=None, min_length=1, max_length=32)
    sr_conclusion_code: str | None = Field(default=None, min_length=1, max_length=64)
    booking_callback: HmacSource | None = None
    report_ingress: HmacSource | None = None
    demo_scenarios: bool = False

    @model_validator(mode="after")
    def check_profile(self):
        if not PATH.fullmatch(self.study_path) or not PATH.fullmatch(self.conclusion_path):
            raise ValueError("study_path и conclusion_path должны быть допустимыми путями")
        if not self.fields or any(not mapping for mapping in self.fields.values()):
            raise ValueError("для каждой модальности нужен непустой набор полей")
        for fields in self.fields.values():
            if any(not CODE.fullmatch(code) for code in fields):
                raise ValueError("код канонического факта должен быть в snake_case")
            paths = [spec.path for spec in fields.values()]
            if len(paths) != len(set(paths)):
                raise ValueError("разные факты не могут читать один JSON-путь")
            sr_codes = [spec.sr_code for spec in fields.values() if spec.sr_code]
            if len(sr_codes) != len(set(sr_codes)) or self.sr_conclusion_code in sr_codes:
                raise ValueError("коды фактов SR должны быть уникальны и отличаться от заключения")
        if self.input == "dicom" and (
            not self.sr_scheme
            or not self.sr_conclusion_code
            or any(not spec.sr_code for fields in self.fields.values() for spec in fields.values())
        ):
            raise ValueError("для DICOM нужны sr_scheme, sr_conclusion_code и sr_code каждого поля")
        if self.booking_mode == "deferred_simulator" and not self.booking_callback:
            raise ValueError("для отложенной записи нужен booking_callback")
        if any(
            not CODE.fullmatch(action) or not service for action, service in self.services.items()
        ):
            raise ValueError("services должен сопоставлять action_type с непустым кодом услуги")
        return self


class RulePredicate(StrictConfig):
    field: str = Field(min_length=1, max_length=64)
    op: Literal["exists", "eq", "in", "range"]
    value: Any = None

    @model_validator(mode="after")
    def check_value(self):
        if self.op == "in" and (not isinstance(self.value, list) or not self.value):
            raise ValueError("оператор in требует непустой список")
        if self.op == "range" and (
            not isinstance(self.value, list)
            or len(self.value) != 2
            or any(type(x) not in (int, float) for x in self.value)
            or self.value[0] > self.value[1]
        ):
            raise ValueError("оператор range требует две упорядоченные числовые границы")
        if self.op == "eq" and self.value is None:
            raise ValueError("оператор eq требует значение")
        return self


class Prerequisite(StrictConfig):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,49}$")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)
    kind: Literal["lab"]
    service_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    gate: Literal["before_booking", "before_execution"]


class RuleStep(StrictConfig):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,49}$")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)
    action_type: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    depends_on: list[str] = Field(default_factory=list, max_length=10)
    unlock_on: list[Literal["followup_needed", "resolved"]] = Field(default_factory=list)
    prerequisites: list[Prerequisite] = Field(default_factory=list, max_length=3)


class Rule(StrictConfig):
    id: str = Field(min_length=1, max_length=100)
    modality: Literal["MAMMOGRAPHY", "CT_CHEST"]
    all: list[RulePredicate] = Field(min_length=1)
    steps: list[RuleStep] = Field(max_length=1)


class RuleSet(StrictConfig):
    version: str = Field(min_length=1, max_length=60)
    status: Literal["HYPOTHESIS"]
    source: str = Field(min_length=1, max_length=500)
    required_fields: dict[Literal["MAMMOGRAPHY", "CT_CHEST"], list[str]]
    rules: list[Rule] = Field(min_length=1)


def _validation_error(name: str, exc: ValidationError) -> DomainError:
    details = "; ".join(
        f"{'.'.join(map(str, error['loc']))}: {error['msg']}" for error in exc.errors()[:4]
    )
    return DomainError(f"Ошибка конфигурации {name}: {details}", 422)


def validate_profiles(data: dict) -> None:
    try:
        parsed = TypeAdapter(dict[str, IntegrationProfile]).validate_python(data)
    except ValidationError as exc:
        raise _validation_error("profiles.json", exc) from exc
    clinic_labels = {}
    for profile_id, profile in parsed.items():
        if not PROFILE_ID.fullmatch(profile_id):
            raise DomainError(f"Ошибка конфигурации profiles.json: неверный ID {profile_id}", 422)
        previous_label = clinic_labels.setdefault(profile.clinic_id, profile.label)
        if previous_label != profile.label:
            raise DomainError(
                f"Профили клиники {profile.clinic_id} должны иметь одинаковое label", 422
            )


def validate_rules(data: dict) -> None:
    try:
        parsed = RuleSet.model_validate(data)
    except ValidationError as exc:
        raise _validation_error("rules.json", exc) from exc
    ids = [rule.id for rule in parsed.rules]
    if len(ids) != len(set(ids)):
        raise DomainError("Ошибка конфигурации rules.json: повторяется ID правила", 422)
    for rule in data["rules"]:
        try:
            validate_steps(rule["steps"])
        except DomainError as exc:
            raise DomainError(f"Правило {rule['id']}: {exc.message}", 422) from exc


def validate_pair(profiles: dict, rules: dict) -> None:
    validate_profiles(profiles)
    validate_rules(rules)
    for profile_id, profile in profiles.items():
        for modality, fields in profile["fields"].items():
            absent = set(rules["required_fields"].get(modality, [])) - set(fields)
            if absent:
                raise DomainError(
                    f"Профиль {profile_id}: нет обязательных канонических полей {', '.join(sorted(absent))}",
                    422,
                )
            for rule in rules["rules"]:
                if rule["modality"] == modality:
                    references = {predicate["field"] for predicate in rule["all"]}
                    unknown = references - set(fields) - {"exam_purpose"}
                    if unknown:
                        raise DomainError(
                            f"Профиль {profile_id}: правило {rule['id']} ссылается на неизвестные поля {', '.join(sorted(unknown))}",
                            422,
                        )
                    for step in rule["steps"]:
                        service_keys = [step["action_type"]] + [
                            item["service_key"] for item in step.get("prerequisites", [])
                        ]
                        missing_services = set(service_keys) - set(profile["services"])
                        if missing_services:
                            raise DomainError(
                                f"Профиль {profile_id}: правило {rule['id']} не имеет услуг {', '.join(sorted(missing_services))}",
                                422,
                            )
