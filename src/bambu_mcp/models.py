"""SQLAlchemy persistence models for printers, artifacts, and durable workflows."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class JobState(StrEnum):
    CREATED = "CREATED"
    INGESTED = "INGESTED"
    INSPECTED = "INSPECTED"
    SLICED = "SLICED"
    VALIDATED = "VALIDATED"
    PREFLIGHTED = "PREFLIGHTED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    UPLOADING = "UPLOADING"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Printer(Base):
    __tablename__ = "printers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    serial: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    host: Mapped[str] = mapped_column(String(255))
    model: Mapped[str] = mapped_column(String(64), default="X2D")
    firmware: Mapped[str | None] = mapped_column(String(64), nullable=True)
    encrypted_access_code: Mapped[str] = mapped_column(Text)
    developer_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    hardware_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    state: Mapped[JobState] = mapped_column(
        Enum(JobState, native_enum=False),
        default=JobState.CREATED,
        index=True,
    )
    printer_id: Mapped[str] = mapped_column(ForeignKey("printers.id"), index=True)
    source_artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"))
    output_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.id"),
        nullable=True,
    )
    plan_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    steps: Mapped[list[JobStep]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobStep.id",
    )


class JobStep(Base):
    __tablename__ = "job_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    from_state: Mapped[str] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[Job] = relationship(back_populates="steps")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    plan_digest: Mapped[str] = mapped_column(String(64), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    actor: Mapped[str] = mapped_column(String(120), default="mcp-client")
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    outcome: Mapped[str] = mapped_column(String(32))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
