import base64
import binascii
import time
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.adapters.booking_webhook import verify_booking_webhook
from app.adapters.reports import (
    from_json,
    from_sr,
    load_config,
    load_pair,
    profile_with_rules_release,
)
from app.adapters.source_auth import verify_hmac_source
from app.adapters.synthetic import make_json, make_sr
from app.application import metrics as conversion_metrics
from app.application import quality, service
from app.domain.routing import DomainError, evaluate
from app.persistence.db import database
from app.persistence.models import Booking, Case, Decision, Event, OutboxEvent, Report, Route


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Context(StrictModel):
    encounter_ref: str = Field(min_length=1, max_length=128)
    source_version: int = Field(ge=1, strict=True)
    modality: Literal["MAMMOGRAPHY", "CT_CHEST"]
    exam_purpose: Literal["unknown", "screening", "diagnostic"] = "unknown"


class ReportInput(StrictModel):
    profile_id: str
    context: Context
    report: dict


class SignedDicomInput(StrictModel):
    profile_id: str
    context: Context
    dicom_base64: str = Field(min_length=1, max_length=2_800_000)


class PrerequisiteInput(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,49}$")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)
    kind: Literal["lab"]
    service_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    gate: Literal["before_booking", "before_execution"]


class StepInput(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,49}$")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)
    action_type: Literal["consultation", "followup", "diagnostic_imaging", "procedure"]
    depends_on: list[str] = Field(default_factory=list, max_length=10)
    unlock_on: list[Literal["followup_needed", "resolved"]] = Field(default_factory=list)
    prerequisites: list[PrerequisiteInput] = Field(default_factory=list, max_length=3)


class DecisionInput(StrictModel):
    version: int = Field(ge=1)
    action: Literal["approve", "edit_and_approve", "reject"]
    reason: str = Field(default="", max_length=2000)
    reason_code: Literal[
        "unspecified", "insufficient_context", "route_logic", "service_mapping", "wording", "other"
    ] = "unspecified"
    steps: list[StepInput] | None = Field(default=None, max_length=1)


class BookingInput(StrictModel):
    route_id: str
    step_key: str
    slot: Literal["tomorrow-09:00", "tomorrow-11:30", "tomorrow-15:00", "no-slots"]


class DeclineStepInput(StrictModel):
    route_id: str
    reason_code: Literal["not_ready", "no_time", "cost", "different_clinic", "other"]


class ResumeStepInput(StrictModel):
    route_id: str


class ReconcileBookingInput(StrictModel):
    action: Literal["carry_over"]
    target_route_id: str
    reason: str = Field(min_length=1, max_length=500)


class BookingFeedbackInput(StrictModel):
    case_id: str
    profile_id: str
    external_ref: str = Field(min_length=1, max_length=100)
    status: Literal["confirmed", "rejected", "no_slots", "cancelled", "cancel_rejected"]
    reason: str = Field(default="", max_length=500)


class ResultInput(StrictModel):
    route_id: str
    step_key: str
    outcome: Literal["followup_needed", "resolved", "replan"]
    note: str = Field(default="", max_length=2000)


class PrerequisiteResultInput(StrictModel):
    route_id: str
    booking_id: str
    requirement_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,49}$")
    outcome: Literal["accepted", "rejected"]
    valid_until: datetime | None = None
    source_ref: str | None = Field(default=None, max_length=100)


class OutboxRetryInput(StrictModel):
    reason: str = Field(min_length=1, max_length=500)


class Scenario(StrictModel):
    profile_id: str = Field(default="private", min_length=1, max_length=50)
    modality: Literal["MAMMOGRAPHY", "CT_CHEST"] = "MAMMOGRAPHY"
    scenario: Literal["finding", "normal", "missing", "multiple", "followup", "priority"] = (
        "finding"
    )
    exam_purpose: Literal["unknown", "screening", "diagnostic"] = "diagnostic"


def reviewer(x_demo_role: str = Header(default="")):
    # This is a local synthetic demo role switch, NOT an authentication mechanism for a clinic.
    if x_demo_role != "reviewer":
        raise HTTPException(403, "Экран доступен только роли специалиста в демо")


def key(idempotency_key: str = Header(min_length=1, max_length=128)):
    return idempotency_key


def create_app(url=None):
    load_pair()
    app = FastAPI(title="Patient pathway · Synthetic demo", version="0.1.0")
    engine, factory = database(url)
    app.state.engine, app.state.sessions = engine, factory

    def db():
        with factory.begin() as session:
            yield session

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, error: DomainError):
        return JSONResponse(status_code=error.status, content={"detail": error.message})

    @app.exception_handler(IntegrityError)
    async def integrity_error(request: Request, error: IntegrityError):
        return JSONResponse(
            status_code=409,
            content={"detail": "Конкурирующее изменение: обновите состояние и повторите запрос"},
        )

    @app.get("/health")
    def health(session=Depends(db, scope="function")):
        session.execute(text("SELECT 1"))
        return {"status": "ok", "mode": "synthetic_demo"}

    @app.get("/api/v1/profiles", dependencies=[Depends(reviewer)])
    def profiles():
        return load_config("profiles.json")

    @app.get("/api/v1/cases", dependencies=[Depends(reviewer)])
    def cases(session=Depends(db, scope="function")):
        rows = session.scalars(select(Case).order_by(Case.created_at.desc())).all()
        result = []
        for c in rows:
            route = service.latest_route(session, c.id)
            report = session.get(Report, route.report_id)
            result.append(
                {
                    "id": c.id,
                    "profile_id": c.profile_id,
                    "clinic_id": c.clinic_id,
                    "modality": c.modality,
                    "created_at": c.created_at,
                    "status": route.status,
                    "pending_review": c.pending_review,
                    "conclusion": report.canonical["conclusion"],
                }
            )
        return result

    @app.get("/api/v1/operations/outbox", dependencies=[Depends(reviewer)])
    def outbox_status(session=Depends(db, scope="function")):
        rows = session.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.processed.is_(False))
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .limit(100)
        ).all()
        return {
            "total_unprocessed": session.scalar(
                select(func.count(OutboxEvent.id)).where(OutboxEvent.processed.is_(False))
            ),
            "total_failed": session.scalar(
                select(func.count(OutboxEvent.id)).where(
                    OutboxEvent.processed.is_(False), OutboxEvent.failed_at.is_not(None)
                )
            ),
            "events": [
                {
                    "id": e.id,
                    "case_id": e.case_id,
                    "kind": e.kind,
                    "status": "failed"
                    if e.failed_at
                    else "retry_scheduled"
                    if e.next_attempt_at
                    else "queued",
                    "attempts": e.attempts,
                    "next_attempt_at": e.next_attempt_at,
                    "failed_at": e.failed_at,
                    "last_error": e.last_error,
                }
                for e in rows
            ],
        }

    @app.post("/api/v1/operations/outbox/{event_id}/retry", dependencies=[Depends(reviewer)])
    def retry_outbox(
        event_id: str,
        body: OutboxRetryInput,
        token=Depends(key),
        session=Depends(db, scope="function"),
    ):
        return service.command(
            session,
            f"outbox-retry:{event_id}",
            token,
            body.model_dump(),
            lambda: service.retry_outbox_event(session, event_id, body.reason),
        )

    @app.get("/api/v1/cases/{case_id}", dependencies=[Depends(reviewer)])
    def case_detail(case_id: str, session=Depends(db, scope="function")):
        c = service.get_case(session, case_id, lock=False)
        route = service.latest_route(session, case_id)
        report = session.get(Report, route.report_id)
        history = session.scalars(
            select(Route).where(Route.case_id == case_id).order_by(Route.version)
        ).all()
        events = session.scalars(
            select(Event).where(Event.case_id == case_id).order_by(Event.created_at.desc())
        ).all()
        decisions = session.scalars(
            select(Decision)
            .join(Route)
            .where(Route.case_id == case_id)
            .order_by(Decision.created_at)
        ).all()
        return {
            "id": c.id,
            "modality": c.modality,
            "profile_id": c.profile_id,
            "clinic_id": c.clinic_id,
            "created_at": c.created_at,
            "status": route.status,
            "conclusion": report.canonical["conclusion"],
            "patient_token": c.patient_token,
            "pending_review": c.pending_review,
            "report": report.canonical,
            "source_kind": report.source_kind,
            "source_profile_id": report.profile_id,
            "proposal": service.route_view(session, route),
            "previous_bookings": service.previous_bookings(session, c),
            "published_route": service.route_view(session, session.get(Route, c.published_route_id))
            if c.published_route_id
            else None,
            "history": [
                {
                    "id": h.id,
                    "version": h.version,
                    "status": h.status,
                    "profile_id": session.get(Report, h.report_id).profile_id,
                }
                for h in history
            ],
            "events": [
                {"id": e.id, "kind": e.kind, "created_at": e.created_at, "payload": e.payload}
                for e in events
            ],
            "decisions": [
                {
                    "action": d.action,
                    "reason_code": d.reason_code,
                    "reason": d.reason,
                    "original_steps": d.original_steps,
                    "final_steps": d.final_steps,
                }
                for d in decisions
            ],
        }

    @app.post("/api/v1/reports/json", dependencies=[Depends(reviewer)])
    def receive_json(body: ReportInput, session=Depends(db, scope="function")):
        profile, ruleset, release_id = profile_with_rules_release(body.profile_id)
        if profile["input"] != "json":
            raise DomainError("Для профиля требуется DICOM SR", 422)
        started_ns = time.perf_counter_ns()
        report = from_json(body.report, body.context.model_dump(), profile)
        return service.ingest(
            session,
            report,
            body.profile_id,
            "json",
            body.report,
            profile=profile,
            ruleset=ruleset,
            config_release_id=release_id,
            started_ns=started_ns,
        )

    async def verified_report_body(
        request, schema, header_profile_id, event_id, timestamp, signature
    ):
        if request.url.query:
            raise DomainError("Параметры URL не поддерживаются подписанным входом", 400)
        if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
            raise DomainError("Для подписанного входа требуется application/json", 415)
        request_body = await request.body()
        if len(request_body) > 3_000_000:
            raise DomainError("Лимит подписанного сообщения — 3 МБ", 413)
        profile, ruleset, release_id = profile_with_rules_release(header_profile_id)
        if not profile.get("report_ingress"):
            raise DomainError("Профиль не принимает подписанные HTTP-отчёты", 403)
        verify_hmac_source(
            profile["report_ingress"],
            header_profile_id,
            event_id,
            timestamp,
            signature,
            request.url.path,
            request_body,
        )
        try:
            body = schema.model_validate_json(request_body)
        except ValidationError as exc:
            raise DomainError("Некорректное тело подписанного отчёта", 422) from exc
        if body.profile_id != header_profile_id:
            raise DomainError("Профиль источника не совпадает с телом события", 401)
        return body, profile, ruleset, release_id

    @app.post("/api/v1/integrations/reports/json")
    async def signed_json_report(
        request: Request,
        x_source_profile: str = Header(min_length=1, max_length=50),
        x_event_id: str = Header(min_length=1, max_length=128),
        x_timestamp: str = Header(min_length=1, max_length=20),
        x_signature: str = Header(min_length=1, max_length=64),
        session=Depends(db, scope="function"),
    ):
        body, profile, ruleset, release_id = await verified_report_body(
            request,
            ReportInput,
            x_source_profile,
            x_event_id,
            x_timestamp,
            x_signature,
        )
        if profile["input"] != "json":
            raise DomainError("Для профиля требуется DICOM SR", 422)

        def ingest():
            started_ns = time.perf_counter_ns()
            report = from_json(body.report, body.context.model_dump(), profile)
            return service.ingest(
                session,
                report,
                body.profile_id,
                "signed_json",
                {"report": body.report, "ingress_event_id": x_event_id},
                profile=profile,
                ruleset=ruleset,
                config_release_id=release_id,
                started_ns=started_ns,
            )

        return service.command(
            session,
            f"report-source:{body.profile_id}",
            x_event_id,
            body.model_dump(),
            ingest,
        )

    @app.post("/api/v1/integrations/reports/dicom")
    async def signed_dicom_report(
        request: Request,
        x_source_profile: str = Header(min_length=1, max_length=50),
        x_event_id: str = Header(min_length=1, max_length=128),
        x_timestamp: str = Header(min_length=1, max_length=20),
        x_signature: str = Header(min_length=1, max_length=64),
        session=Depends(db, scope="function"),
    ):
        body, profile, ruleset, release_id = await verified_report_body(
            request,
            SignedDicomInput,
            x_source_profile,
            x_event_id,
            x_timestamp,
            x_signature,
        )
        if profile["input"] != "dicom":
            raise DomainError("Для профиля требуется JSON", 422)
        try:
            content = base64.b64decode(body.dicom_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise DomainError("Некорректный DICOM в base64", 422) from exc
        if len(content) > 2_000_000:
            raise DomainError("Лимит демонстрационного SR — 2 МБ", 413)

        def ingest():
            started_ns = time.perf_counter_ns()
            report = from_sr(content, body.context.model_dump(), profile)
            return service.ingest(
                session,
                report,
                body.profile_id,
                "signed_dicom",
                {"base64": body.dicom_base64, "ingress_event_id": x_event_id},
                profile=profile,
                ruleset=ruleset,
                config_release_id=release_id,
                started_ns=started_ns,
            )

        return service.command(
            session,
            f"report-source:{body.profile_id}",
            x_event_id,
            body.model_dump(),
            ingest,
        )

    @app.post("/api/v1/profiles/{profile_id}/preview", dependencies=[Depends(reviewer)])
    def preview(profile_id: str, body: ReportInput):
        if profile_id != body.profile_id:
            raise DomainError("Профиль запроса не совпадает", 422)
        profile, ruleset, release_id = profile_with_rules_release(profile_id)
        if profile["input"] != "json":
            raise DomainError("Для профиля требуется DICOM SR", 422)
        report = from_json(body.report, body.context.model_dump(), profile)
        return {
            **report.to_dict(),
            "profile_version": profile["version"],
            "config_release_id": release_id,
            "route_preview": evaluate(report, ruleset),
        }

    @app.post("/api/v1/profiles/{profile_id}/preview-sr", dependencies=[Depends(reviewer)])
    async def preview_sr(
        file: UploadFile,
        profile_id: str,
        modality: Literal["MAMMOGRAPHY", "CT_CHEST"],
        encounter_ref: str = Query(min_length=1, max_length=128),
        source_version: int = Query(default=1, ge=1),
        exam_purpose: Literal["unknown", "screening", "diagnostic"] = "unknown",
    ):
        profile, ruleset, release_id = profile_with_rules_release(profile_id)
        if profile["input"] != "dicom":
            raise DomainError("Для профиля требуется JSON", 422)
        content = await file.read(2_000_001)
        if len(content) > 2_000_000:
            raise DomainError("Лимит демонстрационного SR — 2 МБ", 413)
        context = Context(
            encounter_ref=encounter_ref,
            modality=modality,
            source_version=source_version,
            exam_purpose=exam_purpose,
        )
        report = from_sr(content, context.model_dump(), profile)
        return {
            **report.to_dict(),
            "profile_version": profile["version"],
            "config_release_id": release_id,
            "route_preview": evaluate(report, ruleset),
        }

    @app.post("/api/v1/reports/dicom", dependencies=[Depends(reviewer)])
    async def receive_sr(
        file: UploadFile,
        profile_id: str,
        modality: Literal["MAMMOGRAPHY", "CT_CHEST"],
        encounter_ref: str = Query(min_length=1, max_length=128),
        source_version: int = Query(default=1, ge=1),
        exam_purpose: Literal["unknown", "screening", "diagnostic"] = "unknown",
        session=Depends(db, scope="function"),
    ):
        content = await file.read(2_000_001)
        if len(content) > 2_000_000:
            raise DomainError("Лимит демонстрационного SR — 2 МБ", 413)
        profile, ruleset, release_id = profile_with_rules_release(profile_id)
        if profile["input"] != "dicom":
            raise DomainError("Для профиля требуется JSON", 422)
        context = Context(
            encounter_ref=encounter_ref,
            modality=modality,
            source_version=source_version,
            exam_purpose=exam_purpose,
        )
        started_ns = time.perf_counter_ns()
        report = from_sr(content, context.model_dump(), profile)
        return service.ingest(
            session,
            report,
            profile_id,
            "dicom",
            {"base64": base64.b64encode(content).decode()},
            profile=profile,
            ruleset=ruleset,
            config_release_id=release_id,
            started_ns=started_ns,
        )

    def ingest_demo(session, body, study=None, encounter=None, version=1):
        profile, ruleset, release_id = profile_with_rules_release(body["profile_id"])
        if not profile.get("demo_scenarios", False):
            raise DomainError(
                "Для профиля нет синтетического генератора; используйте предпросмотр своего входа",
                422,
            )
        allowed = {
            "CT_CHEST": {"normal", "finding", "multiple"},
            "MAMMOGRAPHY": {"normal", "followup", "finding", "priority", "missing"},
        }
        if body["scenario"] not in allowed[body["modality"]]:
            raise DomainError("Ситуация не подходит для выбранного исследования", 422)
        raw = make_json(body["modality"], body["scenario"], study)
        context = {
            "modality": body["modality"],
            "source_version": version,
            "encounter_ref": encounter or f"demo-{raw['studyIUID'][-12:]}",
            "exam_purpose": body["exam_purpose"],
        }
        if profile["input"] == "json":
            started_ns = time.perf_counter_ns()
            report, source = from_json(raw, context, profile), raw
        else:
            content = make_sr(raw, body["modality"])
            started_ns = time.perf_counter_ns()
            report, source = (
                from_sr(content, context, profile),
                {"base64": base64.b64encode(content).decode()},
            )
        return service.ingest(
            session,
            report,
            body["profile_id"],
            profile["input"],
            source,
            profile=profile,
            ruleset=ruleset,
            config_release_id=release_id,
            started_ns=started_ns,
        )

    @app.post("/api/v1/demo/cases", dependencies=[Depends(reviewer)])
    def demo_case(body: Scenario, token=Depends(key), session=Depends(db, scope="function")):
        data = body.model_dump()
        return service.command(
            session, "demo-create", token, data, lambda: ingest_demo(session, data)
        )

    @app.post("/api/v1/cases/{case_id}/demo-revision", dependencies=[Depends(reviewer)])
    def revision(
        case_id: str, body: Scenario, token=Depends(key), session=Depends(db, scope="function")
    ):
        c = service.get_case(session, case_id)
        latest = session.get(Report, service.latest_route(session, case_id).report_id)
        data = {**body.model_dump(), "profile_id": c.profile_id, "modality": c.modality}
        return service.command(
            session,
            f"revision:{case_id}",
            token,
            data,
            lambda: ingest_demo(
                session, data, c.study_uid, c.encounter_ref, latest.source_version + 1
            ),
        )

    @app.post("/api/v1/cases/{case_id}/decisions", dependencies=[Depends(reviewer)])
    def decision(
        case_id: str, body: DecisionInput, token=Depends(key), session=Depends(db, scope="function")
    ):
        service.get_case(session, case_id)
        return service.command(
            session,
            f"decision:{case_id}",
            token,
            body.model_dump(),
            lambda: service.decide(session, case_id, body.model_dump()),
        )

    @app.post(
        "/api/v1/cases/{case_id}/bookings/{booking_id}/reconcile",
        dependencies=[Depends(reviewer)],
    )
    def reconcile_booking(
        case_id: str,
        booking_id: str,
        body: ReconcileBookingInput,
        token=Depends(key),
        session=Depends(db, scope="function"),
    ):
        return service.command(
            session,
            f"booking-reconcile:{booking_id}",
            token,
            body.model_dump(),
            lambda: service.reconcile_booking(session, case_id, booking_id, body.model_dump()),
        )

    def patient_case(session, case_id, patient_token, *, lock=False):
        c = service.get_case(session, case_id, lock=lock)
        if patient_token != c.patient_token:
            raise DomainError("Нет доступа к этому случаю", 403)
        return c

    @app.get("/api/v1/patient/cases/{case_id}")
    def patient(
        case_id: str,
        x_patient_token: str = Header(default=""),
        session=Depends(db, scope="function"),
    ):
        c = patient_case(session, case_id, x_patient_token)
        route = session.get(Route, c.published_route_id) if c.published_route_id else None
        return {
            "case_id": c.id,
            "pending_review": c.pending_review,
            "route": service.route_view(session, route, patient=True),
            "previous_bookings": service.previous_bookings(session, c),
        }

    @app.post("/api/v1/patient/cases/{case_id}/shown")
    def shown(
        case_id: str,
        x_patient_token: str = Header(default=""),
        session=Depends(db, scope="function"),
    ):
        c = patient_case(session, case_id, x_patient_token, lock=True)
        if c.published_route_id:
            scope = f"shown:{c.published_route_id}"

            def record():
                service.emit(session, case_id, "shown", {"route_id": c.published_route_id})
                return {"recorded": True}

            return service.command(session, scope, "once", {}, record)
        return {"recorded": False}

    @app.post("/api/v1/patient/cases/{case_id}/bookings")
    def booking(
        case_id: str,
        body: BookingInput,
        x_patient_token: str = Header(default=""),
        token=Depends(key),
        session=Depends(db, scope="function"),
    ):
        patient_case(session, case_id, x_patient_token)
        return service.command(
            session,
            f"book:{case_id}",
            token,
            body.model_dump(),
            lambda: service.book(session, case_id, body.model_dump()),
        )

    @app.post("/api/v1/patient/cases/{case_id}/steps/{step_key}/decline")
    def decline_step(
        case_id: str,
        step_key: str,
        body: DeclineStepInput,
        x_patient_token: str = Header(default=""),
        token=Depends(key),
        session=Depends(db, scope="function"),
    ):
        patient_case(session, case_id, x_patient_token)
        return service.command(
            session,
            f"decline:{case_id}:{step_key}",
            token,
            body.model_dump(),
            lambda: service.decline_step(session, case_id, step_key, body.model_dump()),
        )

    @app.post("/api/v1/patient/cases/{case_id}/steps/{step_key}/resume")
    def resume_step(
        case_id: str,
        step_key: str,
        body: ResumeStepInput,
        x_patient_token: str = Header(default=""),
        token=Depends(key),
        session=Depends(db, scope="function"),
    ):
        patient_case(session, case_id, x_patient_token)
        return service.command(
            session,
            f"resume:{case_id}:{step_key}",
            token,
            body.model_dump(),
            lambda: service.resume_step(session, case_id, step_key, body.model_dump()),
        )

    @app.post("/api/v1/patient/cases/{case_id}/bookings/{booking_id}/cancel")
    def cancel(
        case_id: str,
        booking_id: str,
        x_patient_token: str = Header(default=""),
        token=Depends(key),
        session=Depends(db, scope="function"),
    ):
        patient_case(session, case_id, x_patient_token)
        return service.command(
            session,
            f"cancel:{case_id}",
            token,
            {"booking_id": booking_id},
            lambda: service.cancel_booking(session, case_id, booking_id),
        )

    @app.post("/api/v1/demo/bookings/{booking_id}/feedback", dependencies=[Depends(reviewer)])
    def booking_feedback(
        booking_id: str,
        body: BookingFeedbackInput,
        token=Depends(key),
        session=Depends(db, scope="function"),
    ):
        service.get_case(session, body.case_id)
        return service.command(
            session,
            f"booking-feedback:{booking_id}",
            token,
            body.model_dump(),
            lambda: service.booking_feedback(session, body.case_id, booking_id, body.model_dump()),
        )

    @app.post("/api/v1/integrations/bookings/{booking_id}/feedback")
    async def signed_booking_feedback(
        request: Request,
        booking_id: str,
        x_source_profile: str = Header(min_length=1, max_length=50),
        x_event_id: str = Header(min_length=1, max_length=128),
        x_timestamp: str = Header(min_length=1, max_length=20),
        x_signature: str = Header(min_length=1, max_length=64),
        session=Depends(db, scope="function"),
    ):
        booking = session.get(Booking, booking_id)
        route = session.get(Route, booking.route_id) if booking else None
        case = session.get(Case, route.case_id) if route else None
        report = session.get(Report, route.report_id) if route else None
        if not case or not report or report.profile_id != x_source_profile:
            raise DomainError("Источник статуса не соответствует записи", 403)
        raw_body = await request.body()
        if len(raw_body) > 16_384:
            raise DomainError("Лимит обратного статуса записи — 16 КБ", 413)
        verify_booking_webhook(
            service.route_profile(session, route),
            x_source_profile,
            x_event_id,
            x_timestamp,
            x_signature,
            request.url.path,
            raw_body,
        )
        try:
            body = BookingFeedbackInput.model_validate_json(raw_body)
        except ValidationError as exc:
            raise DomainError("Некорректное тело обратного статуса записи", 422) from exc
        if body.profile_id != x_source_profile:
            raise DomainError("Профиль источника не совпадает с телом события", 401)
        if body.case_id != case.id:
            raise DomainError("Источник статуса не соответствует записи", 403)
        command_body = {"booking_id": booking_id, **body.model_dump()}
        return service.command(
            session,
            f"booking-source:{x_source_profile}",
            x_event_id,
            command_body,
            lambda: service.booking_feedback(session, body.case_id, booking_id, body.model_dump()),
        )

    @app.post("/api/v1/cases/{case_id}/results", dependencies=[Depends(reviewer)])
    def result(
        case_id: str, body: ResultInput, token=Depends(key), session=Depends(db, scope="function")
    ):
        service.get_case(session, case_id)
        return service.command(
            session,
            f"result:{case_id}",
            token,
            body.model_dump(),
            lambda: service.record_result(session, case_id, body.model_dump()),
        )

    @app.get("/api/v1/cases/{case_id}/steps/{step_key}/clearance", dependencies=[Depends(reviewer)])
    def step_clearance(
        case_id: str,
        step_key: str,
        route_id: str = Query(min_length=1),
        session=Depends(db, scope="function"),
    ):
        return service.step_clearance(session, case_id, route_id, step_key)

    @app.post("/api/v1/cases/{case_id}/prerequisite-results", dependencies=[Depends(reviewer)])
    def prerequisite_result(
        case_id: str,
        body: PrerequisiteResultInput,
        token=Depends(key),
        session=Depends(db, scope="function"),
    ):
        return service.command(
            session,
            f"prerequisite-result:{case_id}",
            token,
            body.model_dump(mode="json"),
            lambda: service.record_prerequisite_result(
                session, case_id, body.model_dump(mode="json")
            ),
        )

    @app.get("/api/v1/metrics", dependencies=[Depends(reviewer)])
    def metrics(
        attribution_days: int = Query(default=7, ge=1, le=30),
        shown_from: datetime | None = Query(default=None),
        shown_before: datetime | None = Query(default=None),
        session=Depends(db, scope="function"),
    ):
        if any(value is not None and value.tzinfo is None for value in (shown_from, shown_before)):
            raise DomainError("Границы когорты должны содержать часовой пояс", 422)
        shown_from = shown_from.astimezone(timezone.utc) if shown_from else None
        shown_before = shown_before.astimezone(timezone.utc) if shown_before else None
        if shown_from and shown_before and shown_from >= shown_before:
            raise DomainError("Начало когорты должно быть раньше конца", 422)
        kinds = [
            "result_received",
            "route_proposed",
            "approved",
            "published",
            "shown",
            "booking_confirmed",
            "step_declined",
            "step_resumed",
            "action_completed",
        ]
        counts = {
            kind: session.scalar(
                select(func.count(func.distinct(Event.case_id))).where(Event.kind == kind)
            )
            for kind in kinds
        }
        conversion_events = session.scalars(
            select(Event).where(
                Event.kind.in_(
                    [
                        "shown",
                        "booking_requested",
                        "booking_confirmed",
                        "step_declined",
                        "step_resumed",
                    ]
                )
            )
        ).all()
        booking_routes = dict(session.execute(select(Booking.id, Booking.route_id)).all())
        conversion = conversion_metrics.booking_conversion(
            conversion_events,
            booking_routes,
            attribution_days=attribution_days,
            shown_from=shown_from,
            shown_before=shown_before,
        )
        choices = conversion_metrics.patient_choice_analysis(
            conversion_events,
            attribution_days=attribution_days,
            shown_from=shown_from,
            shown_before=shown_before,
        )
        latency = conversion_metrics.routing_latency(
            session.scalars(select(Report).where(Report.processing_ms.is_not(None))).all()
        )
        stage_events = session.scalars(
            select(Event).where(
                Event.kind.in_(["route_proposed", "approved", "route_rejected", "published"])
            )
        ).all()
        stage_latency = conversion_metrics.workflow_latency(stage_events)
        return {
            "synthetic": True,
            "unit": "unique_cases",
            "counts": counts,
            "booking_conversion": conversion["booking_conversion"],
            "conversion_details": conversion,
            "patient_choices": choices,
            "routing_latency": latency,
            "workflow_latency": stage_latency,
            "uplift": None,
            "uplift_status": "no_control_group",
        }

    @app.get("/api/v1/quality/rule-review", dependencies=[Depends(reviewer)])
    def rule_review(session=Depends(db, scope="function")):
        rows = session.execute(
            select(Decision, Route, Case, Report)
            .join(Route, Decision.route_id == Route.id)
            .join(Case, Route.case_id == Case.id)
            .join(Report, Route.report_id == Report.id)
        ).all()
        return quality.aggregate_decisions(rows)

    return app


app = create_app()
