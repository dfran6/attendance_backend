import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Index, String, text
from sqlmodel import Field, SQLModel

from src.models.base import created_at_field, enum_column, id_field, timestamp_field, updated_at_field
from src.models.enums import AccountStatus, AdminRole


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: uuid.UUID = id_field()
    full_name: str = Field(max_length=120, nullable=False)
    # Stored lower-cased; uniqueness is enforced on the normalised value.
    email: str = Field(sa_column=Column(String(254), unique=True, nullable=False, index=True))
    # Stored upper-cased, e.g. "LA/24A/1234".
    state_code: str = Field(sa_column=Column(String(32), unique=True, nullable=False, index=True))
    phone: Optional[str] = Field(default=None, max_length=32)
    password_hash: str = Field(nullable=False)
    account_status: AccountStatus = Field(
        default=AccountStatus.pending,
        sa_column=enum_column(AccountStatus, "account_status", index=True, default=AccountStatus.pending),
    )
    email_verified_at: Optional[datetime] = timestamp_field()
    last_login_at: Optional[datetime] = timestamp_field()
    created_at: datetime = created_at_field()
    updated_at: datetime = updated_at_field()


class AuthSession(SQLModel, table=True):
    """A refresh-token session. Tokens rotate on every refresh; reuse of a rotated
    token revokes the whole family (theft detection)."""

    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_user_active", "user_id", "revoked_at"),)

    id: uuid.UUID = id_field()
    user_id: uuid.UUID = Field(foreign_key="users.id", nullable=False, ondelete="CASCADE")
    family_id: uuid.UUID = Field(nullable=False, index=True)
    token_hash: str = Field(sa_column=Column(String(64), unique=True, nullable=False))
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    revoked_at: Optional[datetime] = timestamp_field()
    replaced_by_id: Optional[uuid.UUID] = Field(default=None, nullable=True)
    user_agent: Optional[str] = Field(default=None, max_length=255)
    ip_address: Optional[str] = Field(default=None, max_length=64)
    created_at: datetime = created_at_field()


class RoleAssignment(SQLModel, table=True):
    """Administrative roles. LGI is always scoped to an admin area; super_admin has none."""

    __tablename__ = "role_assignments"
    __table_args__ = (
        Index(
            "uq_role_assignments_active",
            "user_id",
            "role",
            "area_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
            sqlite_where=text("revoked_at IS NULL"),
        ),
    )

    id: uuid.UUID = id_field()
    user_id: uuid.UUID = Field(foreign_key="users.id", nullable=False, index=True)
    role: AdminRole = Field(sa_column=enum_column(AdminRole, "admin_role"))
    area_id: Optional[uuid.UUID] = Field(default=None, foreign_key="admin_areas.id", nullable=True, index=True)
    granted_by_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id", nullable=True)
    granted_at: datetime = created_at_field()
    revoked_at: Optional[datetime] = timestamp_field()
    revoked_by_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id", nullable=True)
