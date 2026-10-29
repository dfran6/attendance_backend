"""Shared column helpers for all table models.

Enums are stored as VARCHAR + CHECK constraint (native_enum=False) so new values can
be added with an ordinary migration instead of ALTER TYPE.
"""
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Type

from sqlalchemy import Column, DateTime
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

# Deterministic constraint names, so future migrations can alter/drop them by name.
SQLModel.metadata.naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Normalise datetimes read back from drivers that drop tzinfo (e.g. SQLite)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def enum_column(enum_type: Type[Enum], name: str, *, index: bool = False, nullable: bool = False, default=None) -> Column:
    return Column(
        SAEnum(
            enum_type,
            name=name,
            native_enum=False,
            create_constraint=True,
            length=32,
            values_callable=lambda e: [m.value for m in e],
            validate_strings=True,
        ),
        nullable=nullable,
        index=index,
        default=default,
    )


def id_field():
    return Field(default_factory=uuid.uuid4, primary_key=True)


def created_at_field():
    return Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False, default=utc_now))


def updated_at_field():
    return Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now),
    )


def timestamp_field(*, nullable: bool = True, index: bool = False):
    return Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=nullable, index=index))
