import copy
import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, text

from app.adapters.booking import adapter_for
from app.domain.routing import (
    CanonicalReport,
    DomainError,
    evaluate,
    step_availability,
    validate_steps,
)
from app.persistence.models import (
    Booking,
    Case,
    Command,
    Decision,
    Event,
    OutboxEvent,
    PatientChoice,
    PrerequisiteResult,
    Report,
    Route,
    StepResult,
    now,
    uid,
)

logger = logging.getLogger(__name__)


def digest(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def clinical_content(canonical):
    """Clinical identity, independent of JSON paths and DICOM tree pointers."""
    return {
        "study_uid": canonical["study_uid"],
        "encounter_ref": canonical["encounter_ref"],
        "source_version": canonical["source_version"],
        "modality": canonical["modality"],
        "exam_purpose": canonical["exam_purpose"],
        "conclusion": canonical["conclusion"],
        "synthetic": canonical["synthetic"],
        "facts": sorted(
            (
                {"code": fact["code"], "value": fact["value"], "unit": fact.get("unit")}
                for fact in canonical["facts"]
            ),
            key=lambda fact: fact["code"],
        ),
    }


def get_case(session, case_id, *, lock=True):
    statement = select(Case).where(Case.id == case_id)
    if lock:
        statement = statement.with_for_update()
    case = session.scalar(statement)
    if not case:
        raise DomainError("Случай не найден", 404)
    return case


def latest_route(session, case_id):
    return session.scalar(
        select(Route).where(Route.case_id == case_id).order_by(Route.version.desc()).limit(1)
    )


def route_profile(session, route):
    """Use the technical configuration captured when this route was created."""
    report = session.get(Report, route.report_id) if route else None
    raw = report.raw if report and isinstance(report.raw, dict) else {}
    profile = raw.get("integration_profile")
    if not isinstance(profile, dict) or raw.get("profile_hash") != digest(profile):
        raise DomainError("Снимок профиля маршрута отсутствует или повреждён", 409)
    return profile


def emit(session, case_id, kind, payload=None, queued=False):
    event_id = uid()
    body = payload or {}
    session.add(Event(id=event_id, case_id=case_id, kind=kind, payload=body))
    if queued:
        queued_event = OutboxEvent(id=event_id, case_id=case_id, kind=kind, payload=body)
        session.add(queued_event)
        return queued_event


def lock_transaction_key(session, *parts):
    """Serialize an absent-row lookup on PostgreSQL within the current transaction."""
    if session.get_bind().dialect.name != "postgresql":
        return
    lock_bytes = hashlib.sha256(
        json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()
    ).digest()[:8]
    lock_key = int.from_bytes(lock_bytes, byteorder="big", signed=True)
    session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})


def command(session, scope, token, body, action):
    # A command row does not yet exist for SELECT FOR UPDATE.
    lock_transaction_key(session, "command", scope, token)
    previous = session.scalar(select(Command).where(Command.scope == scope, Command.token == token))
    content_hash = digest(body)
    if previous:
        if previous.content_hash != content_hash:
            raise DomainError("Ключ идемпотентности уже использован с другим запросом")
        return previous.response
    result = action()
    session.add(Command(scope=scope, token=token, content_hash=content_hash, response=result))
    return result


def ingest(
    session,
    report: CanonicalReport,
    profile_id,
    source_kind,
    raw,
    *,
    profile,
    ruleset,
    config_release_id=None,
    started_ns=None,
):
    clinic_id = profile["clinic_id"]
    # Two sources may deliver the same new study concurrently with different
    # event IDs. Lock the study identity before checking for the absent Case row.
    lock_transaction_key(session, "study", clinic_id, report.study_uid)
    bound_clinic_id = session.scalar(
        select(Case.clinic_id)
        .join(Report, Report.case_id == Case.id)
        .where(Report.profile_id == profile_id)
        .limit(1)
    )
    if bound_clinic_id and bound_clinic_id != clinic_id:
        raise DomainError("Профиль уже привязан к другой клинике", 409)
    case = session.scalar(
        select(Case)
        .where(Case.clinic_id == clinic_id, Case.study_uid == report.study_uid)
        .with_for_update()
    )
    if not case:
        case = Case(
            profile_id=profile_id,
            clinic_id=clinic_id,
            study_uid=report.study_uid,
            encounter_ref=report.encounter_ref,
            modality=report.modality,
        )
        session.add(case)
        session.flush()
    elif case.encounter_ref != report.encounter_ref or case.modality != report.modality:
        raise DomainError("Исследование уже связано с другим приёмом или модальностью")
    canonical = report.to_dict()
    content_hash = digest(clinical_content(canonical))
    existing = session.scalar(
        select(Report).where(
            Report.case_id == case.id, Report.source_version == report.source_version
        )
    )
    if existing:
        if clinical_content(existing.canonical) != clinical_content(canonical):
            raise DomainError("Версия заключения уже существует с другим содержимым")
        existing_route_id = session.scalar(
            select(Route.id).where(Route.report_id == existing.id).limit(1)
        )
        return {
            "case_id": case.id,
            "report_id": existing.id,
            "route_id": existing_route_id,
            "duplicate": True,
        }
    latest = latest_route(session, case.id)
    if latest:
        previous_report = session.get(Report, latest.report_id)
        if report.source_version <= previous_report.source_version:
            raise DomainError("Получена устаревшая версия заключения")
        if latest.status in ("draft", "manual", "approved"):
            latest.status = "superseded"
    source = Report(
        case_id=case.id,
        profile_id=profile_id,
        source_version=report.source_version,
        content_hash=content_hash,
        source_kind=source_kind,
        canonical=canonical,
        raw={
            "payload": raw,
            "integration_profile": profile,
            "profile_hash": digest(profile),
            "ruleset": ruleset,
            "ruleset_hash": digest(ruleset),
            "config_release_id": config_release_id,
        },
    )
    session.add(source)
    session.flush()
    proposal = evaluate(report, ruleset)
    route = Route(
        case_id=case.id,
        report_id=source.id,
        parent_route_id=latest.id if latest else None,
        version=latest.version + 1 if latest else 1,
        status=proposal["status"],
        ruleset_version=proposal["ruleset_version"],
        steps=copy.deepcopy(proposal["steps"]),
        proposed_steps=copy.deepcopy(proposal["steps"]),
        trace=proposal["trace"],
        warnings=proposal["warnings"],
    )
    session.add(route)
    case.pending_review = True
    case.profile_id = profile_id
    session.flush()
    emit(
        session,
        case.id,
        "result_received",
        {"report_id": source.id, "source_version": report.source_version},
    )
    emit(
        session,
        case.id,
        "route_proposed",
        {"route_id": route.id, "version": route.version, "manual": route.status == "manual"},
    )
    if started_ns is not None:
        source.processing_ms = round((time.perf_counter_ns() - started_ns) / 1_000_000, 3)
    return {"case_id": case.id, "report_id": source.id, "route_id": route.id, "duplicate": False}


def decide(session, case_id, body):
    case = get_case(session, case_id)
    route = latest_route(session, case_id)
    if not route or route.version != body["version"] or route.status not in ("draft", "manual"):
        raise DomainError("Проект изменился или уже обработан. Обновите экран.")
    action, reason = body["action"], body.get("reason", "").strip()
    if route.status == "manual" and action == "approve":
        raise DomainError("При недостатке данных специалист должен задать маршрут и причину", 422)
    if action in ("edit_and_approve", "reject") and not reason:
        raise DomainError("Укажите причину изменения или отклонения", 422)
    before = copy.deepcopy(route.steps)
    if action == "edit_and_approve":
        steps = body.get("steps")
        if steps is None:
            raise DomainError("Не передан исправленный маршрут", 422)
        validate_steps(steps)
        profile = route_profile(session, route)
        for step in steps:
            service_keys = [step["action_type"]] + [
                item["service_key"] for item in step.get("prerequisites", [])
            ]
            if any(key not in profile["services"] for key in service_keys):
                raise DomainError("Для шага или анализа нет кода услуги в профиле клиники", 422)
        route.steps = steps
    session.add(
        Decision(
            route_id=route.id,
            action=action,
            reason_code="none" if action == "approve" else body.get("reason_code", "unspecified"),
            reason=reason,
            original_steps=before,
            final_steps=copy.deepcopy(route.steps),
        )
    )
    route.status = "rejected" if action == "reject" else "approved"
    emit(
        session,
        case.id,
        "route_rejected" if action == "reject" else "approved",
        {"route_id": route.id, "edited": action == "edit_and_approve"},
    )
    if action == "reject":
        # Keep the rejected decision immutable, but make the correction path
        # available during the same encounter without waiting for another SR.
        revision_warning = "Проект отклонён; требуется исправленный маршрут"
        revision = Route(
            case_id=case.id,
            report_id=route.report_id,
            parent_route_id=route.id,
            version=route.version + 1,
            status="manual",
            ruleset_version=route.ruleset_version,
            steps=copy.deepcopy(route.steps),
            proposed_steps=copy.deepcopy(route.steps),
            trace=copy.deepcopy(route.trace),
            warnings=[
                *route.warnings,
                *([] if revision_warning in route.warnings else [revision_warning]),
            ],
        )
        session.add(revision)
        session.flush()
        case.pending_review = True
        emit(
            session,
            case.id,
            "route_proposed",
            {
                "route_id": revision.id,
                "version": revision.version,
                "manual": True,
                "revision_of": route.id,
            },
        )
        return {
            "route_id": route.id,
            "status": route.status,
            "version": route.version,
            "revision_route_id": revision.id,
            "revision_version": revision.version,
        }
    emit(session, case.id, "publish_route", {"route_id": route.id}, queued=True)
    return {"route_id": route.id, "status": route.status, "version": route.version}


OUTBOX_MAX_ATTEMPTS = 5
OUTBOX_BACKOFF_SECONDS = 2


def _process_queued_event(session, event):
    if event.kind == "publish_route":
        case = get_case(session, event.case_id)
        route = session.get(Route, event.payload["route_id"])
        if not route or route.case_id != case.id:
            raise DomainError("Некорректная ссылка на маршрут в outbox")
        current = latest_route(session, case.id)
        if route.status == "approved" and current and current.id == route.id:
            if case.published_route_id:
                session.get(Route, case.published_route_id).status = "superseded"
            route.status = "published"
            case.published_route_id, case.pending_review = route.id, False
            for booking in previous_bookings(session, case):
                emit(
                    session,
                    case.id,
                    "booking_reconciliation_required",
                    {"booking_id": booking["id"], "route_id": route.id},
                )
            emit(session, case.id, "published", {"route_id": route.id})
            emit(
                session,
                case.id,
                "notification_simulated",
                {"text": "В кабинете доступен подтверждённый маршрут.", "delivery": "demo_only"},
            )
    elif event.kind == "submit_booking_simulated":
        case = get_case(session, event.case_id)
        booking = session.get(Booking, event.payload["booking_id"])
        if not booking:
            raise DomainError("Некорректная ссылка на запись в outbox")
        route = session.get(Route, booking.route_id)
        if not route or route.case_id != case.id:
            raise DomainError("Запись относится к другому случаю")
        if booking.status == "requested":
            booking.status = "awaiting_confirmation"
            emit(
                session,
                case.id,
                "booking_submission_simulated",
                {"booking_id": booking.id, "external_ref": booking.external_ref},
            )
    elif event.kind == "submit_cancellation_simulated":
        case = get_case(session, event.case_id)
        booking = session.get(Booking, event.payload["booking_id"])
        route = session.get(Route, booking.route_id) if booking else None
        if not route or route.case_id != case.id:
            raise DomainError("Некорректная ссылка на отменяемую запись в outbox")
        if booking.status == "cancel_requested":
            emit(
                session,
                case.id,
                "booking_cancellation_submission_simulated",
                {"booking_id": booking.id, "external_ref": booking.external_ref},
            )
    else:
        raise DomainError("Неизвестный тип outbox-события")


def _outbox_error_code(error):
    # Do not persist exception messages: source reports and connector errors may contain patient data.
    if isinstance(error, KeyError):
        return "missing_payload_field"
    if isinstance(error, DomainError):
        return "invalid_event_reference_or_kind"
    return type(error).__name__[:100]


def dispatch_once(session, limit=50):
    current_time = datetime.now(timezone.utc)
    events = session.scalars(
        select(OutboxEvent)
        .where(
            OutboxEvent.processed.is_(False),
            OutboxEvent.failed_at.is_(None),
            or_(
                OutboxEvent.next_attempt_at.is_(None),
                OutboxEvent.next_attempt_at <= current_time.isoformat(timespec="microseconds"),
            ),
        )
        .order_by(OutboxEvent.created_at, OutboxEvent.id)
        .with_for_update(skip_locked=True)
        .limit(limit)
    ).all()
    processed = 0
    for event in events:
        try:
            # A malformed event cannot roll back good events in this worker batch.
            with session.begin_nested():
                _process_queued_event(session, event)
                event.processed = True
                event.next_attempt_at = None
                event.last_error = None
        except Exception as error:
            failure_time = datetime.now(timezone.utc)
            event.attempts += 1
            event.last_error = _outbox_error_code(error)
            if event.attempts >= OUTBOX_MAX_ATTEMPTS:
                event.failed_at = failure_time.isoformat(timespec="microseconds")
                event.next_attempt_at = None
                event_kind = "outbox_failed"
            else:
                delay = min(OUTBOX_BACKOFF_SECONDS * 2 ** (event.attempts - 1), 60)
                event.next_attempt_at = (failure_time + timedelta(seconds=delay)).isoformat(
                    timespec="microseconds"
                )
                event_kind = "outbox_retry_scheduled"
            emit(
                session,
                event.case_id,
                event_kind,
                {"event_id": event.id, "event_kind": event.kind, "attempts": event.attempts},
            )
            logger.log(
                logging.ERROR if event.failed_at else logging.WARNING,
                "outbox_event=%s attempts=%s error_code=%s",
                event.id,
                event.attempts,
                event.last_error,
            )
        else:
            processed += 1
    return processed


def retry_outbox_event(session, event_id, reason):
    event = session.scalar(select(OutboxEvent).where(OutboxEvent.id == event_id).with_for_update())
    if not event:
        raise DomainError("Outbox-событие не найдено", 404)
    if event.processed or not event.failed_at:
        raise DomainError("Повторный запуск доступен только для события со статусом failed")
    reason = reason.strip()
    if not reason:
        raise DomainError("Укажите причину повторного запуска", 422)
    get_case(session, event.case_id)
    event.attempts = 0
    event.next_attempt_at = None
    event.failed_at = None
    event.last_error = None
    emit(session, event.case_id, "outbox_retry_requested", {"event_id": event.id, "reason": reason})
    return {"event_id": event.id, "status": "queued"}


def result_map(session, route_id):
    return {
        r.step_key: r.outcome
        for r in session.scalars(select(StepResult).where(StepResult.route_id == route_id)).all()
    }


def prerequisite_result_map(session, route_id):
    """Use the latest readiness decision; a correction can revoke acceptance."""
    rows = session.scalars(
        select(PrerequisiteResult)
        .where(PrerequisiteResult.route_id == route_id)
        .order_by(PrerequisiteResult.created_at.desc(), PrerequisiteResult.id.desc())
    ).all()
    result = {}
    for row in rows:
        result.setdefault(row.requirement_key, row)
    return result


def prerequisite_ready(requirement, evidence):
    if not evidence or evidence.outcome != "accepted":
        return False
    if evidence.valid_until:
        expires = datetime.fromisoformat(evidence.valid_until)
        if expires <= datetime.now(timezone.utc):
            return False
    return True


def route_action(route, key):
    for step in route.steps:
        if step["key"] == key:
            return step, False
        for requirement in step.get("prerequisites", []):
            if requirement["key"] == key:
                return requirement, True
    return None, False


def route_view(session, route, patient=False):
    if not route:
        return None
    result = result_map(session, route.id)
    evidence = prerequisite_result_map(session, route.id)
    bookings = session.scalars(
        select(Booking)
        .where(func.coalesce(Booking.reconciled_route_id, Booking.route_id) == route.id)
        .order_by(Booking.created_at)
    ).all()
    choices = {
        choice.step_key: choice
        for choice in session.scalars(
            select(PatientChoice).where(PatientChoice.route_id == route.id)
        ).all()
    }
    steps = []
    for step in route.steps:
        state = step_availability(step, result)
        booked = [b for b in bookings if b.step_key == step["key"]]
        booking = booked[-1] if booked else None
        entry = {
            **step,
            "availability": state,
            "booking": booking_view(session, booking) if booking else None,
        }
        preparations = []
        for requirement in step.get("prerequisites", []):
            prepared = evidence.get(requirement["key"])
            lab_bookings = [b for b in bookings if b.step_key == requirement["key"]]
            lab_booking = lab_bookings[-1] if lab_bookings else None
            preparations.append(
                {
                    **requirement,
                    "readiness": "ready"
                    if prerequisite_ready(requirement, prepared)
                    else "expired"
                    if prepared and prepared.outcome == "accepted"
                    else "rejected"
                    if prepared and prepared.outcome == "rejected"
                    else "pending",
                    "valid_until": prepared.valid_until if prepared else None,
                    "booking": booking_view(session, lab_booking) if lab_booking else None,
                }
            )
        entry["prerequisites"] = preparations
        entry["booking_gate_open"] = all(
            prerequisite_ready(item, evidence.get(item["key"]))
            for item in step.get("prerequisites", [])
            if item["gate"] == "before_booking"
        )
        entry["execution_gate_open"] = all(
            prerequisite_ready(item, evidence.get(item["key"]))
            for item in step.get("prerequisites", [])
        )
        if step["key"] in choices:
            entry["choice"] = choice_view(choices[step["key"]])
        if not patient or state != "blocked":
            steps.append(entry)
    data = {
        "id": route.id,
        "version": route.version,
        "status": route.status,
        "parent_route_id": route.parent_route_id,
        "trigger_result_id": route.trigger_result_id,
        "steps": steps,
        "rule_status": "HYPOTHESIS",
    }
    if not patient:
        data.update(
            {
                "trace": route.trace,
                "warnings": route.warnings,
                "ruleset_version": route.ruleset_version,
                "proposed_steps": route.proposed_steps,
                "results": result,
            }
        )
    return data


def choice_view(choice):
    if not choice:
        return None
    return {
        "status": choice.status,
        "reason_code": choice.reason_code,
        "updated_at": choice.updated_at,
    }


def actionable_patient_step(session, case_id, route_id, step_key):
    case = get_case(session, case_id)
    if case.pending_review or case.published_route_id != route_id:
        raise DomainError("Действие доступно только для текущего подтверждённого маршрута")
    route = session.get(Route, route_id)
    if not route or route.status != "published":
        raise DomainError("Текущий маршрут ещё не опубликован")
    step = next((item for item in route.steps if item["key"] == step_key), None)
    if not step or step_availability(step, result_map(session, route.id)) != "available":
        raise DomainError("Этот шаг ещё недоступен или уже завершён")
    return case, route


def decline_step(session, case_id, step_key, body):
    case, route = actionable_patient_step(session, case_id, body["route_id"], step_key)
    active_booking = session.scalar(
        select(Booking).where(
            func.coalesce(Booking.reconciled_route_id, Booking.route_id) == route.id,
            Booking.step_key == step_key,
            Booking.status.in_(
                ["requested", "awaiting_confirmation", "confirmed", "cancel_requested"]
            ),
        )
    )
    if active_booking:
        raise DomainError("Сначала отмените действующую запись или дождитесь ответа на запрос")
    choice = session.scalar(
        select(PatientChoice).where(
            PatientChoice.route_id == route.id, PatientChoice.step_key == step_key
        )
    )
    if choice and choice.status == "declined":
        raise DomainError("Отказ от этого шага уже сохранён")
    if not choice:
        choice = PatientChoice(route_id=route.id, step_key=step_key, status="declined")
        session.add(choice)
    choice.status = "declined"
    choice.reason_code = body["reason_code"]
    choice.updated_at = now()
    emit(
        session,
        case.id,
        "step_declined",
        {"route_id": route.id, "step_key": step_key, "reason_code": choice.reason_code},
    )
    return choice_view(choice)


def resume_step(session, case_id, step_key, body):
    case, route = actionable_patient_step(session, case_id, body["route_id"], step_key)
    choice = session.scalar(
        select(PatientChoice).where(
            PatientChoice.route_id == route.id, PatientChoice.step_key == step_key
        )
    )
    if not choice or choice.status != "declined":
        raise DomainError("Для этого шага нет действующего отказа")
    choice.status = "resumed"
    choice.reason_code = None
    choice.updated_at = now()
    emit(session, case.id, "step_resumed", {"route_id": route.id, "step_key": step_key})
    return choice_view(choice)


def booking_view(session, b):
    route = session.get(Route, b.route_id)
    report = session.get(Report, route.report_id)
    data = {
        k: getattr(b, k)
        for k in [
            "id",
            "step_key",
            "status",
            "slot",
            "service_id",
            "external_ref",
            "status_reason",
            "reconciled_route_id",
        ]
    }
    return {**data, "profile_id": report.profile_id}


def effective_booking_route_id(booking):
    return booking.reconciled_route_id or booking.route_id


def previous_bookings(session, case):
    rows = session.execute(
        select(Booking, Route)
        .join(Route, Booking.route_id == Route.id)
        .where(
            Route.case_id == case.id,
            func.coalesce(Booking.reconciled_route_id, Booking.route_id) != case.published_route_id,
            Booking.status.in_(
                ["requested", "awaiting_confirmation", "confirmed", "cancel_requested"]
            ),
        )
        .order_by(Booking.created_at)
    ).all()
    result = []
    for booking, original_route in rows:
        effective_route = session.get(Route, effective_booking_route_id(booking))
        result.append(
            {
                **booking_view(session, booking),
                "route_version": effective_route.version,
                "original_route_version": original_route.version,
                "title": next(
                    (
                        action["title"]
                        for action in [
                            *effective_route.steps,
                            *[
                                item
                                for step in effective_route.steps
                                for item in step.get("prerequisites", [])
                            ],
                        ]
                        if action["key"] == booking.step_key
                    ),
                    booking.step_key,
                ),
            }
        )
    return result


def reconcile_booking(session, case_id, booking_id, body):
    case = get_case(session, case_id)
    if case.pending_review or case.published_route_id != body["target_route_id"]:
        raise DomainError("Сначала подтвердите и опубликуйте текущий маршрут")
    booking = session.scalar(select(Booking).where(Booking.id == booking_id).with_for_update())
    source = session.get(Route, booking.route_id) if booking else None
    if not source or source.case_id != case.id:
        raise DomainError("Запись не найдена", 404)
    if booking.status not in ("requested", "awaiting_confirmation", "confirmed"):
        raise DomainError("Согласовать можно только действующую запись")
    from_route_id = effective_booking_route_id(booking)
    if from_route_id == case.published_route_id:
        raise DomainError("Запись уже относится к текущему маршруту")
    reason = body["reason"].strip()
    if not reason:
        raise DomainError("Укажите причину сохранения записи", 422)
    target = session.get(Route, case.published_route_id)
    if not target or target.status != "published":
        raise DomainError("Текущий маршрут ещё не опубликован")
    step, is_preparation = route_action(target, booking.step_key)
    if not step or (
        not is_preparation
        and step_availability(step, result_map(session, target.id)) != "available"
    ):
        raise DomainError("В новом маршруте нет доступного соответствующего шага")
    evidence = prerequisite_result_map(session, target.id)
    if not is_preparation and any(
        not prerequisite_ready(item, evidence.get(item["key"]))
        for item in step.get("prerequisites", [])
        if item["gate"] == "before_booking"
    ):
        raise DomainError("До сохранения записи нужен результат подготовки")
    service_key = step["service_key"] if is_preparation else step["action_type"]
    service_id = route_profile(session, target)["services"].get(service_key)
    if service_id != booking.service_id:
        raise DomainError("Код услуги изменился; старую запись нужно согласовать отдельно")
    duplicate = session.scalar(
        select(Booking).where(
            func.coalesce(Booking.reconciled_route_id, Booking.route_id) == target.id,
            Booking.step_key == booking.step_key,
            Booking.status.in_(
                ["requested", "awaiting_confirmation", "confirmed", "cancel_requested"]
            ),
        )
    )
    if duplicate:
        raise DomainError("На этот шаг уже есть запись по новому маршруту")
    booking.reconciled_route_id = target.id
    emit(
        session,
        case.id,
        "booking_reconciled",
        {
            "booking_id": booking.id,
            "from_route_id": from_route_id,
            "to_route_id": target.id,
            "reason": reason,
        },
    )
    return booking_view(session, booking)


def book(session, case_id, body):
    case = get_case(session, case_id)
    if case.pending_review or case.published_route_id != body["route_id"]:
        raise DomainError("Запись доступна только для текущего подтверждённого маршрута")
    if previous_bookings(session, case):
        raise DomainError(
            "Осталась запись по прежнему маршруту. Сначала согласуйте её с клиникой или отмените."
        )
    route = session.get(Route, case.published_route_id)
    step, is_preparation = route_action(route, body["step_key"])
    if not step or (
        not is_preparation and step_availability(step, result_map(session, route.id)) != "available"
    ):
        raise DomainError("Этот шаг ещё недоступен или уже завершён")
    evidence = prerequisite_result_map(session, route.id)
    if is_preparation and any(
        step in main.get("prerequisites", []) and main["key"] in result_map(session, route.id)
        for main in route.steps
    ):
        raise DomainError("Основной шаг уже завершён")
    if is_preparation and prerequisite_ready(step, evidence.get(step["key"])):
        raise DomainError("Подготовительный анализ уже готов")
    if not is_preparation and any(
        not prerequisite_ready(item, evidence.get(item["key"]))
        for item in step.get("prerequisites", [])
        if item["gate"] == "before_booking"
    ):
        raise DomainError("До записи нужен результат подготовительного анализа")
    declined = session.scalar(
        select(PatientChoice).where(
            PatientChoice.route_id == route.id,
            PatientChoice.step_key == step["key"],
            PatientChoice.status == "declined",
        )
    )
    if declined:
        raise DomainError("Вы отказались от шага. Возобновите его перед записью")
    existing = session.scalar(
        select(Booking).where(
            func.coalesce(Booking.reconciled_route_id, Booking.route_id) == route.id,
            Booking.step_key == step["key"],
            Booking.status.in_(
                ["requested", "awaiting_confirmation", "confirmed", "cancel_requested"]
            ),
        )
    )
    if existing:
        raise DomainError("На этот шаг уже есть запрос записи или подтверждённая запись")
    # The demo has three fixed slots. Parallel tasks may be arranged independently,
    # but the same patient cannot attend two services at the same time.
    active_bookings = session.scalars(
        select(Booking)
        .join(Route, Booking.route_id == Route.id)
        .where(
            Route.case_id == case.id,
            Booking.status.in_(
                ["requested", "awaiting_confirmation", "confirmed", "cancel_requested"]
            ),
        )
    ).all()
    if any(other.slot == body["slot"] for other in active_bookings):
        raise DomainError("У пациента уже есть запись на это время")
    slot_rank = {"tomorrow-09:00": 1, "tomorrow-11:30": 2, "tomorrow-15:00": 3}
    if body["slot"] in slot_rank:
        if is_preparation:
            main = next(
                (
                    candidate
                    for candidate in route.steps
                    if step in candidate.get("prerequisites", [])
                ),
                None,
            )
            if (
                main
                and step["gate"] == "before_execution"
                and any(
                    other.step_key == main["key"]
                    and other.slot in slot_rank
                    and slot_rank[body["slot"]] >= slot_rank[other.slot]
                    for other in active_bookings
                )
            ):
                raise DomainError("Анализ должен быть запланирован до основного шага")
        elif any(
            item["gate"] == "before_execution"
            and not prerequisite_ready(item, evidence.get(item["key"]))
            and any(
                other.step_key == item["key"]
                and other.slot in slot_rank
                and slot_rank[other.slot] >= slot_rank[body["slot"]]
                for other in active_bookings
            )
            for item in step.get("prerequisites", [])
        ):
            raise DomainError("Основной шаг должен быть запланирован после анализа")
    profile = route_profile(session, route)
    service_key = step["service_key"] if is_preparation else step["action_type"]
    service_id = profile["services"].get(service_key)
    slot_key = f"{case.clinic_id}:{service_id}:{body['slot']}"
    if session.scalar(select(Booking).where(Booking.slot_key == slot_key)):
        raise DomainError("Выбранное время уже занято")
    available = service_id is not None and body["slot"] != "no-slots"
    booking = Booking(
        route_id=route.id,
        step_key=step["key"],
        service_id=service_id or "unmapped",
        slot=body["slot"],
        slot_key=slot_key if available else None,
        status="requested" if available else "no_slots",
    )
    session.add(booking)
    session.flush()
    if available:
        receipt = adapter_for(profile).prepare(booking.id)
        booking.status, booking.external_ref = receipt.status, receipt.external_ref
    emit(session, case.id, "booking_requested", {"booking_id": booking.id, "route_id": route.id})
    if not available:
        emit(
            session,
            case.id,
            "coordinator_task_created",
            {"booking_id": booking.id, "route_id": route.id},
        )
    elif receipt.needs_dispatch:
        emit(session, case.id, "submit_booking_simulated", {"booking_id": booking.id}, queued=True)
    else:
        emit(
            session, case.id, "booking_confirmed", {"booking_id": booking.id, "route_id": route.id}
        )
    return booking_view(session, booking)


def booking_feedback(session, case_id, booking_id, body):
    case = get_case(session, case_id)
    booking = session.scalar(select(Booking).where(Booking.id == booking_id).with_for_update())
    if not booking:
        raise DomainError("Запись не найдена", 404)
    route = session.get(Route, booking.route_id)
    report = session.get(Report, route.report_id)
    if route.case_id != case.id or report.profile_id != body["profile_id"]:
        raise DomainError("Источник статуса не соответствует записи", 403)
    if booking.external_ref != body["external_ref"]:
        raise DomainError("Внешний идентификатор записи не совпадает", 409)
    status, reason = body["status"], body["reason"].strip()
    if booking.status == "awaiting_confirmation":
        if status not in ("confirmed", "rejected", "no_slots"):
            raise DomainError("Ответ отмены не соответствует текущему состоянию записи")
        if status in ("rejected", "no_slots") and not reason:
            raise DomainError("Укажите причину отказа или отсутствия слотов", 422)
        booking.status = status
        if status != "confirmed":
            booking.slot_key = None
        event_kind = {
            "confirmed": "booking_confirmed",
            "rejected": "booking_rejected",
            "no_slots": "coordinator_task_created",
        }[status]
    elif booking.status == "cancel_requested":
        if status not in ("cancelled", "cancel_rejected"):
            raise DomainError("Ответ записи не соответствует запросу отмены")
        if status == "cancel_rejected" and not reason:
            raise DomainError("Укажите причину отказа в отмене", 422)
        booking.status = "confirmed" if status == "cancel_rejected" else "cancelled"
        if status == "cancelled":
            booking.slot_key = None
        event_kind = (
            "booking_cancellation_rejected" if status == "cancel_rejected" else "booking_cancelled"
        )
    else:
        raise DomainError("Обратный статус не соответствует текущему состоянию записи")
    booking.status_reason = reason or None
    emit(
        session,
        case.id,
        event_kind,
        {"booking_id": booking.id, "route_id": effective_booking_route_id(booking)},
    )
    return booking_view(session, booking)


def cancel_booking(session, case_id, booking_id):
    get_case(session, case_id)
    booking = session.scalar(select(Booking).where(Booking.id == booking_id).with_for_update())
    if not booking or session.get(Route, booking.route_id).case_id != case_id:
        raise DomainError("Запись не найдена", 404)
    if booking.status != "confirmed":
        raise DomainError("Отменить можно только действующую запись")
    profile = route_profile(session, session.get(Route, booking.route_id))
    if profile["booking_mode"] == "deferred_simulator":
        booking.status, booking.status_reason = "cancel_requested", None
        emit(session, case_id, "booking_cancellation_requested", {"booking_id": booking.id})
        emit(
            session,
            case_id,
            "submit_cancellation_simulated",
            {"booking_id": booking.id},
            queued=True,
        )
    else:
        booking.status, booking.slot_key = "cancelled", None
        emit(session, case_id, "booking_cancelled", {"booking_id": booking.id})
    return booking_view(session, booking)


def record_prerequisite_result(session, case_id, body):
    """Record a verified readiness decision without storing laboratory values."""
    get_case(session, case_id)
    route = session.get(Route, body["route_id"])
    booking = session.get(Booking, body["booking_id"])
    if not route or route.case_id != case_id or not booking:
        raise DomainError("Подготовительная задача или запись не найдена", 404)
    if (
        effective_booking_route_id(booking) != route.id
        or booking.step_key != body["requirement_key"]
    ):
        raise DomainError("Результат не относится к этой подготовительной задаче")
    requirement, is_preparation = route_action(route, body["requirement_key"])
    if not is_preparation or requirement is None:
        raise DomainError("Подготовительная задача не найдена в маршруте", 422)
    if booking.status not in ("confirmed", "completed"):
        raise DomainError("Нужна подтверждённая сдача анализа до регистрации результата")
    valid_until = body.get("valid_until")
    if valid_until:
        expires = datetime.fromisoformat(valid_until)
        if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
            raise DomainError(
                "Срок действия результата должен быть в будущем и с часовым поясом", 422
            )
    if body["outcome"] == "rejected" and valid_until:
        raise DomainError("Непринятый результат не может иметь срок действия", 422)
    evidence = PrerequisiteResult(
        route_id=route.id,
        booking_id=booking.id,
        requirement_key=requirement["key"],
        outcome=body["outcome"],
        valid_until=valid_until,
        source_ref=body.get("source_ref") or None,
    )
    session.add(evidence)
    booking.status, booking.slot_key = "completed", None
    session.flush()
    emit(
        session,
        case_id,
        "prerequisite_result_received",
        {
            "route_id": route.id,
            "requirement_key": requirement["key"],
            "outcome": evidence.outcome,
            "evidence_id": evidence.id,
        },
    )
    if evidence.outcome == "rejected":
        emit(
            session,
            case_id,
            "preparation_review_required",
            {"route_id": route.id, "requirement_key": requirement["key"]},
        )
    return {"status": evidence.outcome, "evidence_id": evidence.id}


def step_clearance(session, case_id, route_id, step_key):
    """Read-only readiness gate for a clinic executor before performing a service."""
    case = get_case(session, case_id, lock=False)
    route = session.get(Route, route_id)
    if not route or route.case_id != case_id:
        raise DomainError("Маршрут не найден", 404)
    step, is_preparation = route_action(route, step_key)
    if not step or is_preparation:
        raise DomainError("Основной шаг не найден", 404)
    reasons = []
    if case.pending_review or case.published_route_id != route.id or route.status != "published":
        reasons.append("route_not_current")
    if step_key in result_map(session, route.id):
        reasons.append("step_already_completed")
    confirmed = session.scalar(
        select(Booking.id).where(
            func.coalesce(Booking.reconciled_route_id, Booking.route_id) == route.id,
            Booking.step_key == step_key,
            Booking.status == "confirmed",
        )
    )
    if not confirmed:
        reasons.append("booking_not_confirmed")
    evidence = prerequisite_result_map(session, route.id)
    missing = [
        item["key"]
        for item in step.get("prerequisites", [])
        if not prerequisite_ready(item, evidence.get(item["key"]))
    ]
    if missing:
        reasons.append("preparation_not_ready")
    return {"ready": not reasons, "reasons": reasons, "missing_prerequisites": missing}


def record_result(session, case_id, body):
    case = get_case(session, case_id)
    route = session.get(Route, body["route_id"])
    if not route or route.case_id != case_id:
        raise DomainError("Маршрут не найден", 404)
    step, is_preparation = route_action(route, body["step_key"])
    if not step or is_preparation:
        raise DomainError("Результат относится только к основному шагу", 422)
    evidence = prerequisite_result_map(session, route.id)
    missing = [
        item["title"]
        for item in step.get("prerequisites", [])
        if not prerequisite_ready(item, evidence.get(item["key"]))
    ]
    if missing:
        raise DomainError("Нет действительного результата подготовки: " + ", ".join(missing))
    booking = session.scalar(
        select(Booking).where(
            func.coalesce(Booking.reconciled_route_id, Booking.route_id) == route.id,
            Booking.step_key == body["step_key"],
            Booking.status == "confirmed",
        )
    )
    if not booking:
        raise DomainError("Нет действующей записи для результата")
    if body["step_key"] in result_map(session, route.id):
        raise DomainError("Результат шага уже зарегистрирован")
    result = StepResult(
        route_id=route.id, step_key=body["step_key"], outcome=body["outcome"], note=body["note"]
    )
    session.add(result)
    booking.status, booking.slot_key = "completed", None
    session.flush()
    emit(session, case_id, "action_completed", {"route_id": route.id, "step_key": body["step_key"]})
    emit(
        session,
        case_id,
        "step_result_received",
        {
            "result_id": result.id,
            "route_id": route.id,
            "step_key": body["step_key"],
            "outcome": body["outcome"],
        },
    )
    previous_route_result = case.published_route_id != route.id
    review_already_pending = case.pending_review
    next_route_id = None
    if (
        body["outcome"] in ("followup_needed", "replan")
        or previous_route_result
        or review_already_pending
    ):
        latest = latest_route(session, case_id)
        if latest.status in ("draft", "manual", "approved"):
            latest.status = "superseded"
        warning = (
            "Результат по прежней версии пути требует пересмотра текущего маршрута."
            if previous_route_result
            else "Новый результат получен во время проверки маршрута. Нужен повторный выбор специалиста."
            if review_already_pending
            else "Получен результат шага. Следующий шаг выбирается заново специалистом."
        )
        pending = Route(
            case_id=case_id,
            report_id=latest.report_id,
            parent_route_id=route.id,
            trigger_result_id=result.id,
            version=latest.version + 1,
            status="manual",
            ruleset_version=latest.ruleset_version,
            steps=[],
            proposed_steps=[],
            trace=[],
            warnings=[warning],
        )
        session.add(pending)
        case.pending_review = True
        session.flush()
        next_route_id = pending.id
        emit(
            session,
            case_id,
            "route_proposed",
            {
                "route_id": pending.id,
                "manual": True,
                "trigger_result_id": result.id,
                "trigger_route_id": route.id,
            },
        )
    else:
        emit(session, case_id, "cycle_closed", {"route_id": route.id, "result_id": result.id})
    return {
        "status": "recorded",
        "pending_review": case.pending_review,
        "next_route_id": next_route_id,
    }
