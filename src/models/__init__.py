"""All table models, imported here so Alembic's env.py only needs `from src.models import metadata`."""
from sqlmodel import SQLModel

from src.models.attendance import AttendanceCorrection, AttendanceRecord, CdsSession, Excuse, QrChallenge
from src.models.audit import AuditLog, Notification
from src.models.identity import AuthSession, RoleAssignment, User
from src.models.organization import AdminArea, CdsGroup, Membership

metadata = SQLModel.metadata

__all__ = [
    "AdminArea",
    "AttendanceCorrection",
    "AttendanceRecord",
    "AuditLog",
    "AuthSession",
    "CdsGroup",
    "CdsSession",
    "Excuse",
    "Membership",
    "Notification",
    "QrChallenge",
    "RoleAssignment",
    "User",
    "metadata",
]
