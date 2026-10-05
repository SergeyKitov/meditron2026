from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class Base(DeclarativeBase):
    pass


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        UniqueConstraint("profile_id", "study_uid"),
        UniqueConstraint("clinic_id", "study_uid", name="uq_cases_clinic_study"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    profile_id: Mapped[str] = mapped_column(String(50))
    clinic_id: Mapped[str] = mapped_column(String(50))
    study_uid: Mapped[str] = mapped_column(String(128))
    encounter_ref: Mapped[str] = mapped_column(String(128))
    patient_token: Mapped[str] = mapped_column(String(36), default=uid)
    modality: Mapped[str] = mapped_column(String(30))
    published_route_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    pending_review: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class Report(Base):
    __tablename__ = "source_reports"
    __table_args__ = (UniqueConstraint("case_id", "source_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    profile_id: Mapped[str] = mapped_column(String(50))
    source_version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    source_kind: Mapped[str] = mapped_column(String(20))
    processing_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    canonical: Mapped[dict] = mapped_column(JSON)
    raw: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class Route(Base):
    __tablename__ = "route_versions"
    __table_args__ = (UniqueConstraint("case_id", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("source_reports.id"))
    parent_route_id: Mapped[str | None] = mapped_column(
        ForeignKey("route_versions.id"), nullable=True
    )
    trigger_result_id: Mapped[str | None] = mapped_column(
        ForeignKey("step_results.id"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    ruleset_version: Mapped[str] = mapped_column(String(60))
    proposed_steps: Mapped[list] = mapped_column(JSON)
    steps: Mapped[list] = mapped_column(JSON)
    trace: Mapped[list] = mapped_column(JSON)
    warnings: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class Decision(Base):
    __tablename__ = "clinical_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    route_id: Mapped[str] = mapped_column(ForeignKey("route_versions.id"), unique=True)
    action: Mapped[str] = mapped_column(String(30))
    reason_code: Mapped[str] = mapped_column(
        String(40), default="unspecified", server_default="unspecified"
    )
    reason: Mapped[str] = mapped_column(String(2000))
    original_steps: Mapped[list] = mapped_column(JSON)
    final_steps: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    route_id: Mapped[str] = mapped_column(ForeignKey("route_versions.id"), index=True)
    reconciled_route_id: Mapped[str | None] = mapped_column(
        ForeignKey("route_versions.id", name="fk_bookings_reconciled_route_id_route_versions"),
        index=True,
        nullable=True,
    )
    step_key: Mapped[str] = mapped_column(String(50))
    service_id: Mapped[str] = mapped_column(String(100))
    slot: Mapped[str] = mapped_column(String(100))
    slot_key: Mapped[str | None] = mapped_column(String(250), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    external_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class StepResult(Base):
    __tablename__ = "step_results"
    __table_args__ = (UniqueConstraint("route_id", "step_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    route_id: Mapped[str] = mapped_column(ForeignKey("route_versions.id"))
    step_key: Mapped[str] = mapped_column(String(50))
    outcome: Mapped[str] = mapped_column(String(30))
    note: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class PrerequisiteResult(Base):
    """Append-only readiness evidence for a lab task, not laboratory values."""

    __tablename__ = "prerequisite_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    route_id: Mapped[str] = mapped_column(ForeignKey("route_versions.id"), index=True)
    booking_id: Mapped[str] = mapped_column(ForeignKey("bookings.id"), index=True)
    requirement_key: Mapped[str] = mapped_column(String(50))
    outcome: Mapped[str] = mapped_column(String(20))
    valid_until: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class PatientChoice(Base):
    __tablename__ = "patient_choices"
    __table_args__ = (UniqueConstraint("route_id", "step_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    route_id: Mapped[str] = mapped_column(ForeignKey("route_versions.id"), index=True)
    step_key: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20))
    reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    updated_at: Mapped[str] = mapped_column(String(40), default=now)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(60), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[str] = mapped_column(ForeignKey("events.id"), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    failed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class Command(Base):
    __tablename__ = "commands"
    __table_args__ = (UniqueConstraint("scope", "token"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    scope: Mapped[str] = mapped_column(String(150))
    token: Mapped[str] = mapped_column(String(128))
    content_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)
