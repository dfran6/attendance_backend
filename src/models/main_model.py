from datetime import date, datetime, timezone
from enum import Enum
from typing import List, Optional
import uuid
import sqlalchemy.dialects.postgresql as pg



from sqlalchemy import Column, Enum as SAEnum
from sqlmodel import Field, Relationship, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def enum_column(enum_type: type[Enum], name: str) -> SAEnum:
    return SAEnum(enum_type, name=name, native_enum=True, validate_strings=True)


class UserRole(str, Enum):
    super_admin = "super_admin"
    admin = "admin"
    excos = "excos"
    corper = "corper"



class UserStatus(str, Enum):
    active = "active"
    pending = "pending"
    rejected = "rejected"
    banned = "suspended"
    
class Excuse_status(str, Enum):
    accepted = "accepted"
    pending = "pending"
    rejected = "rejected"


class User(SQLModel, table=True):
    __tablename__ = "users"

    uid: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    state_code: str = Field(unique=True, index=True, nullable=False)
    email: str = Field(unique=True, index=True, nullable=False)
    full_name: str = Field(nullable=False)
    phone: Optional[str] = Field(default=None)
    role: UserRole = Field(sa_column=Column(enum_column(UserRole, "user_role_enum"), nullable=False, index=True))
    is_active: bool = Field(default=True, nullable=False)
    password_hash: str = Field(nullable=False, exclude=True)
    status: UserStatus = Field(default=UserStatus.pending, sa_column=Column(enum_column(UserStatus, "user_status_enum"), nullable=False, index=True, default=UserStatus.active))
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False, index=True)
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False)
    )
    last_login: Optional[datetime] = Field(
        default=None,
        sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=True)
    )
    deactivated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=True)
    )


class Group(SQLModel, table = True):
    __tablename__ = "groups"
    
    id: uuid.UUID = Field(unique=True, primary_key=True, default_factory= uuid.uuid4())
    name:str = Field(unique=True)
    description: str = Field(nullable=True)
    is_active:bool = Field(default=True)
    created_by_id: uuid.UUID = Field(foreign_key="users.uid", nullable=False)
    created_at: datetime = Field(
            default_factory=datetime.utcnow,
            sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False, index=True)
        )
    updated_at : datetime = Field(default_factory=datetime.utcnow, sa_column=Column(pg.TIMESTAMP(timezone=True)))
    
    corpers: list["User"] = Relationship(back_populates="group")
    
class Memberships(SQLModel, table=True):
    __tablename__ = "memberships"
    
    id: uuid.UUID = Field(unique=True, primary_key=True, default_factory= uuid.uuid4())
    user_id: uuid.UUID = Field(foreign_key="users.uid", nullable=False)
    group_id: uuid.UUID = Field(foreign_key="groups.id", nullable=False)
    joined_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False))
    
class Moderator_assignment(SQLModel, table=True):
    __tablename__ = "moderator_assignments"
    
    id: uuid.UUID = Field(unique=True, primary_key=True, default_factory= uuid.uuid4())
    moderator_id: uuid.UUID = Field(foreign_key="users.uid", nullable=False)
    group_id: uuid.UUID = Field(foreign_key="groups.id", nullable=False)
    assigned_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False))

class Registration_links(SQLModel, table=True):
    __tablename__ = "registration_links"
    
    id: uuid.UUID = Field(unique=True, primary_key=True, default_factory= uuid.uuid4())
    link: str = Field(unique=True, nullable=False)
    group_id: uuid.UUID = Field(foreign_key="groups.id", nullable=False)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False))
    expires_at: datetime = Field(sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False))
    
class Attendance(SQLModel, table=True):
    __tablename__ = "attendance"
    
    id: uuid.UUID = Field(unique=True, primary_key=True, default_factory= uuid.uuid4())
    user_id: uuid.UUID = Field(foreign_key="users.uid", nullable=False)
    session_id: uuid.UUID = Field(foreign_key="sessions.id", nullable=False)
    attended_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False))

class Attendance_Session(SQLModel, table=True):
    __tablename__ = "sessions"
    
    id: uuid.UUID = Field(unique=True, primary_key=True, default_factory= uuid.uuid4())
    group_id: uuid.UUID = Field(foreign_key="groups.id", nullable=False)
    session_date: date = Field(nullable=False)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False))

class Checkin_attempts(SQLModel, table=True):
    __tablename__ = "checkin_attempts"
    
    id: uuid.UUID = Field(unique=True, primary_key=True, default_factory= uuid.uuid4())
    user_id: uuid.UUID = Field(foreign_key="users.uid", nullable=False)
    session_id: uuid.UUID = Field(foreign_key="sessions.id", nullable=False)
    attempt_time: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False))

class Excuse(SQLModel, table=True):
    __tablename__ = "excuses"
    
    id: uuid.UUID = Field(unique=True, primary_key=True, default_factory= uuid.uuid4())
    user_id: uuid.UUID = Field(foreign_key="users.uid", nullable=False)
    session_id: uuid.UUID = Field(foreign_key="sessions.id", nullable=False)
    reason: str = Field(nullable=False)
    submitted_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False))
    status: str = Field(default="pending", nullable=False)  # pending, approved, rejected

class Attendance_corrections(SQLModel, table=True):
    __tablename__ = "attendance_corrections"
    
    id: uuid.UUID = Field(unique=True, primary_key=True, default_factory= uuid.uuid4())
    user_id: uuid.UUID = Field(foreign_key="users.uid", nullable=False)
    session_id: uuid.UUID = Field(foreign_key="sessions.id", nullable=False)
    correction_reason: str = Field(nullable=False)
    submitted_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False))
    status: str = Field(default="pending", nullable=False)  # pending, approved, rejected

class Audit_events(SQLModel, table=True):
    __tablename__ = "audit_events"
    
    id: uuid.UUID = Field(unique=True, primary_key=True, default_factory= uuid.uuid4())
    user_id: uuid.UUID = Field(foreign_key="users.uid", nullable=False)
    event_type: str = Field(nullable=False)
    event_description: str = Field(nullable=False)
    event_time: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False))
    
class Reports(SQLModel, table=True):
    __tablename__ = "reports"
    
    id: uuid.UUID = Field(unique=True, primary_key=True, default_factory= uuid.uuid4())
    report_type: str = Field(nullable=False)
    report_description: str = Field(nullable=False)
    reported_by_id: uuid.UUID = Field(foreign_key="users.uid", nullable=False)
    reported_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False))