import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, Index, String, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from src.models.base import created_at_field, enum_column, id_field, timestamp_field, updated_at_field
from src.models.enums import MembershipRole, MembershipStatus


class AdminArea(SQLModel, table=True):
    """A Local Government Area — the jurisdiction an LGI oversees."""

    __tablename__ = "admin_areas"

    id: uuid.UUID = id_field()
    name: str = Field(max_length=120, nullable=False)
    code: str = Field(sa_column=Column(String(32), unique=True, nullable=False))
    state: str = Field(max_length=64, nullable=False)
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = created_at_field()


class CdsGroup(SQLModel, table=True):
    __tablename__ = "cds_groups"
    __table_args__ = (UniqueConstraint("area_id", "name", name="uq_cds_groups_area_name"),)

    id: uuid.UUID = id_field()
    area_id: uuid.UUID = Field(foreign_key="admin_areas.id", nullable=False, index=True)
    name: str = Field(max_length=120, nullable=False)
    code: str = Field(sa_column=Column(String(32), unique=True, nullable=False))
    description: Optional[str] = Field(default=None, max_length=500)
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = created_at_field()
    updated_at: datetime = updated_at_field()


class Membership(SQLModel, table=True):
    """A user's membership of a CDS group. History is kept: rejected/revoked rows stay.
    A user may hold at most one pending-or-approved membership at a time."""

    __tablename__ = "memberships"
    __table_args__ = (
        Index(
            "uq_memberships_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'approved')"),
            sqlite_where=text("status IN ('pending', 'approved')"),
        ),
        Index("ix_memberships_group_status", "group_id", "status"),
    )

    id: uuid.UUID = id_field()
    user_id: uuid.UUID = Field(foreign_key="users.id", nullable=False, index=True)
    group_id: uuid.UUID = Field(foreign_key="cds_groups.id", nullable=False)
    role: MembershipRole = Field(
        default=MembershipRole.member,
        sa_column=enum_column(MembershipRole, "membership_role", default=MembershipRole.member),
    )
    status: MembershipStatus = Field(
        default=MembershipStatus.pending,
        sa_column=enum_column(MembershipStatus, "membership_status", default=MembershipStatus.pending),
    )
    decided_by_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id", nullable=True)
    decided_at: Optional[datetime] = timestamp_field()
    decision_reason: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime = created_at_field()
    updated_at: datetime = updated_at_field()
