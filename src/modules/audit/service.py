import uuid
from typing import Any, Dict, Optional

from fastapi import Request
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.logging import request_id_var
from src.models import AuditLog


def record(
    session: AsyncSession,
    action: str,
    *,
    actor_id: Optional[uuid.UUID] = None,
    target_type: Optional[str] = None,
    target_id: Optional[Any] = None,
    group_id: Optional[uuid.UUID] = None,
    area_id: Optional[uuid.UUID] = None,
    request: Optional[Request] = None,
    context: Optional[Dict[str, Any]] = None,
) -> AuditLog:
    """Adds an audit row to the caller's transaction, so it commits (or rolls back)
    atomically with the action it describes."""
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        group_id=group_id,
        area_id=area_id,
        request_id=request_id_var.get(),
        ip_address=request.client.host if request is not None and request.client else None,
        context=context or {},
    )
    session.add(entry)
    return entry
