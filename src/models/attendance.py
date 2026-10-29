import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import CheckConstraint, Column, DateTime, Index, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from src.models.base import created_at_field, enum_column, id_field, timestamp_field, updated_at_field
from src.models.enums import (
    AttendanceStatus,
    ExcuseCategory,
    ExcuseStatus,
    SessionStatus,
    VerificationMethod,
)


class CdsSession(SQLModel, table=True):
    __tablename__ = "cds_sessions"
    __table_args__ = (
        Index("ix_cds_sessions_group_start", "group_id", "scheduled_start"),
        # A group can run only one live session at a time.
        Index(
            "uq_cds_sessions_one_active_per_group",
            "group_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        CheckConstraint("scheduled_end > scheduled_start", name="scheduled_window"),
    )

    id: uuid.UUID = id_field()
    group_id: uuid.UUID = Field(foreign_key="cds_groups.id", nullable=False)
    created_by_id: uuid.UUID = Field(foreign_key="users.id", nullable=False)
    title: str = Field(max_length=160, nullable=False)
    description: Optional[str] = Field(default=None, max_length=2000)
    venue: Optional[str] = Field(default=None, max_length=200)
    scheduled_start: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    scheduled_end: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    actual_start: Optional[datetime] = timestamp_field()
    actual_end: Optional[datetime] = timestamp_field()
    # Minutes after actual_start after which a QR check-in is recorded as "late".
    late_after_minutes: int = Field(default=30, nullable=False)
    # Optional geofence. GPS is supporting evidence only, never proof of presence.
    latitude: Optional[float] = Field(default=None)
    longitude: Optional[float] = Field(default=None)
    radius_m: Optional[int] = Field(default=None)
    status: SessionStatus = Field(
        default=SessionStatus.scheduled,
        sa_column=enum_column(SessionStatus, "session_status", index=True, default=SessionStatus.scheduled),
    )
    created_at: datetime = created_at_field()
    updated_at: datetime = updated_at_field()


class QrChallenge(SQLModel, table=True):
    """Issued challenges are recorded for audit; validity is proven by the signed token."""

    __tablename__ = "qr_challenges"

    id: uuid.UUID = id_field()
    session_id: uuid.UUID = Field(foreign_key="cds_sessions.id", nullable=False, index=True)
    issued_by_id: uuid.UUID = Field(foreign_key="users.id", nullable=False)
    issued_at: datetime = created_at_field()
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class AttendanceRecord(SQLModel, table=True):
    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("user_id", "session_id", name="uq_attendance_user_session"),
        Index("ix_attendance_session_status", "session_id", "status"),
    )

    id: uuid.UUID = id_field()
    user_id: uuid.UUID = Field(foreign_key="users.id", nullable=False, index=True)
    session_id: uuid.UUID = Field(foreign_key="cds_sessions.id", nullable=False)
    status: AttendanceStatus = Field(sa_column=enum_column(AttendanceStatus, "attendance_status"))
    method: VerificationMethod = Field(sa_column=enum_column(VerificationMethod, "verification_method"))
    checked_in_at: datetime = created_at_field()
    challenge_id: Optional[uuid.UUID] = Field(default=None, foreign_key="qr_challenges.id", nullable=True)
    recorded_by_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id", nullable=True)
    # Distance from the venue in metres; raw coordinates are not retained.
    distance_m: Optional[int] = Field(default=None)
    created_at: datetime = created_at_field()
    updated_at: datetime = updated_at_field()


class AttendanceCorrection(SQLModel, table=True):
    """Append-only history of manual changes to an attendance record."""

    __tablename__ = "attendance_corrections"

    id: uuid.UUID = id_field()
    attendance_id: uuid.UUID = Field(foreign_key="attendance_records.id", nullable=False, index=True)
    changed_by_id: uuid.UUID = Field(foreign_key="users.id", nullable=False)
    previous_status: Optional[AttendanceStatus] = Field(
        default=None, sa_column=enum_column(AttendanceStatus, "previous_attendance_status", nullable=True)
    )
    new_status: AttendanceStatus = Field(sa_column=enum_column(AttendanceStatus, "attendance_status"))
    reason: str = Field(max_length=500, nullable=False)
    created_at: datetime = created_at_field()


class Excuse(SQLModel, table=True):
    __tablename__ = "excuses"
    __table_args__ = (Index("ix_excuses_group_status", "group_id", "status"),)

    id: uuid.UUID = id_field()
    user_id: uuid.UUID = Field(foreign_key="users.id", nullable=False, index=True)
    group_id: uuid.UUID = Field(foreign_key="cds_groups.id", nullable=False)
    session_id: Optional[uuid.UUID] = Field(default=None, foreign_key="cds_sessions.id", nullable=True)
    start_date: date = Field(nullable=False)
    end_date: date = Field(nullable=False)
    category: ExcuseCategory = Field(sa_column=enum_column(ExcuseCategory, "excuse_category"))
    explanation: str = Field(max_length=2000, nullable=False)
    evidence_key: Optional[str] = Field(default=None, max_length=255)
    evidence_content_type: Optional[str] = Field(default=None, max_length=100)
    status: ExcuseStatus = Field(
        default=ExcuseStatus.submitted,
        sa_column=enum_column(ExcuseStatus, "excuse_status", default=ExcuseStatus.submitted),
    )
    submitted_at: datetime = created_at_field()
    reviewed_by_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id", nullable=True)
    reviewed_at: Optional[datetime] = timestamp_field()
    decision_reason: Optional[str] = Field(default=None, max_length=500)
    updated_at: datetime = updated_at_field()
