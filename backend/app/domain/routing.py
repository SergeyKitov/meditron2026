"""Canonical routing contracts and the versioned model entry point."""

from dataclasses import asdict, dataclass
from typing import Any


class DomainError(Exception):
    def __init__(self, message: str, status: int = 409):
        self.message, self.status = message, status
        super().__init__(message)


@dataclass(frozen=True)
class Fact:
    code: str
    value: Any
    source_pointer: str
    unit: str | None = None


@dataclass(frozen=True)
class CanonicalReport:
    study_uid: str
    encounter_ref: str
    source_version: int
    modality: str
    exam_purpose: str
    conclusion: str
    facts: tuple[Fact, ...]
    synthetic: bool = True
    warnings: tuple[str, ...] = ()

    def to_dict(self):
        return asdict(self)


def validate_steps(steps: list[dict]) -> None:
    # A route version is one clinical next action. Preparation is parallel work
    # for that action, never a precomputed second clinical action.
    if len(steps) > 1:
        raise DomainError("Версия маршрута может содержать только один следующий шаг", 422)
    keys = [step["key"] for step in steps]
    if len(set(keys)) != len(keys):
        raise DomainError("Идентификаторы шагов повторяются", 422)
    graph = {step["key"]: step.get("depends_on", []) for step in steps}
    visited, active = set(), set()

    def visit(key):
        if key not in graph:
            raise DomainError("Зависимость ссылается на отсутствующий шаг", 422)
        if key in active:
            raise DomainError("В маршруте обнаружен цикл", 422)
        if key in visited:
            return
        active.add(key)
        for dependency in graph[key]:
            visit(dependency)
        active.remove(key)
        visited.add(key)

    for key in keys:
        visit(key)
    for step in steps:
        if step.get("depends_on") or step.get("unlock_on"):
            raise DomainError("Следующий шаг создаётся после результата, а не заранее", 422)
        requirements = step.get("prerequisites", [])
        if len(requirements) > 3:
            raise DomainError("У одного шага допускается не более трёх подготовительных задач", 422)
        requirement_keys = [item["key"] for item in requirements]
        if len(requirement_keys) != len(set(requirement_keys)) or set(requirement_keys) & set(keys):
            raise DomainError("Коды подготовительных задач должны быть уникальными", 422)
        for item in requirements:
            if item["kind"] != "lab" or item["gate"] not in (
                "before_booking",
                "before_execution",
            ):
                raise DomainError("Недопустимый тип или условие подготовительной задачи", 422)


def evaluate_rules(report: CanonicalReport, ruleset: dict) -> dict:
    """Synthetic teacher used only when building the initial labelled dataset."""
    facts = {f.code: f for f in report.facts}
    context = {"exam_purpose": report.exam_purpose, **{k: f.value for k, f in facts.items()}}
    warnings = list(report.warnings)
    required = ruleset["required_fields"].get(report.modality, [])
    for field in required:
        if field not in context:
            warnings.append(f"Нет обязательного факта: {field}")
    trace, matches = [], []
    for rule in ruleset["rules"]:
        if rule["modality"] != report.modality:
            continue
        checks = []
        for predicate in rule["all"]:
            name, operator = predicate["field"], predicate["op"]
            value = context.get(name)
            expected = predicate.get("value")
            if operator == "exists":
                passed = value is not None
            elif value is None:
                passed = False
            elif operator == "eq":
                passed = value == expected
            elif operator == "in":
                passed = value in expected
            elif operator == "range":
                passed = expected[0] <= value <= expected[1]
            else:
                raise DomainError(f"Неподдержанный оператор: {operator}", 422)
            checks.append(
                {
                    "field": name,
                    "actual": value,
                    "op": operator,
                    "expected": expected,
                    "passed": passed,
                    "source_pointer": facts[name].source_pointer
                    if name in facts
                    else "context.exam_purpose",
                }
            )
        passed = all(c["passed"] for c in checks)
        trace.append({"rule_id": rule["id"], "matched": passed, "checks": checks})
        if passed:
            matches.append(rule)
    if report.modality == "CT_CHEST" and report.exam_purpose == "unknown":
        warnings.append("Неизвестно назначение КТ: выбор пути передан специалисту")
    if len(matches) > 1:
        warnings.append("Несколько несовместимых правил: требуется ручной выбор")
    if not matches and not warnings:
        warnings.append("Для этих фактов нет демонстрационного правила")
    manual = bool(warnings) or len(matches) != 1
    steps = [] if manual else matches[0]["steps"]
    validate_steps(steps)
    return {
        "status": "manual" if manual else "draft",
        "steps": steps,
        "trace": trace,
        "warnings": warnings,
        "ruleset_version": ruleset["version"],
        "rule_status": "HYPOTHESIS",
    }


def evaluate(report: CanonicalReport, ruleset: dict) -> dict:
    """Infer one candidate step; rule predicates are never evaluated at runtime."""
    from app.domain.model_routing import predict_route

    return predict_route(report)


def step_availability(step: dict, results: dict[str, str]) -> str:
    if step["key"] in results:
        return "completed"
    deps = step.get("depends_on", [])
    if not deps:
        return "available"
    if any(key not in results for key in deps):
        return "blocked"
    if all(results[key] in step["unlock_on"] for key in deps):
        return "available"
    return "not_needed"
