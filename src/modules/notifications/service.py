"""In-app notifications: a lightweight per-user inbox the client polls.

Delivery is best-effort and never blocks the action that triggered it — callers add the
rows to their own transaction, so a notification failure can't roll back a session start.
"""
import uuid
from typing import Sequence

from sqlalchemy import func, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.permissions import Principal
from src.models import Membership, Notification
from src.models.base import as_utc, utc_now
from src.models.enums import MembershipStatus
from src.modules.notifications.schema import NotificationOut, UnreadCount
from src.shared.schemas import Page, PageParams

SESSION_STARTED = "session_started"


def _out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id, type=n.type, title=n.title, body=n.body, entity_type=n.entity_type,
        entity_id=n.entity_id, read_at=as_utc(n.read_at), created_at=as_utc(n.created_at),
    )


async def fan_out_session_started(db: AsyncSession, *, session_id: uuid.UUID, group_id: uuid.UUID, title: str) -> None:
    """Queue a 'check in now' notification for every approved member of the group.

    Rows are added to the caller's session; the caller commits. Idempotency isn't enforced
    at the DB level, so callers must only invoke this once per actual scheduled→active flip.
    """
    recipients: Sequence[uuid.UUID] = (
        await db.exec(
            select(Membership.user_id).where(
                Membership.group_id == group_id, Membership.status == MembershipStatus.approved
            )
        )
    ).all()
    for user_id in recipients:
        db.add(
            Notification(
                recipient_id=user_id, type=SESSION_STARTED, entity_type="session", entity_id=str(session_id),
                title="Attendance is open", body=f"{title} — check in now.",
            )
        )


async def list_notifications(principal: Principal, params: PageParams, db: AsyncSession) -> Page[NotificationOut]:
    base = select(Notification).where(Notification.recipient_id == principal.id)
    total = (await db.exec(select(func.count()).select_from(base.subquery()))).one()
    rows = (
        await db.exec(base.order_by(Notification.created_at.desc()).offset(params.offset).limit(params.page_size))
    ).all()
    return Page(items=[_out(n) for n in rows], total=total, page=params.page, page_size=params.page_size)


async def unread_count(principal: Principal, db: AsyncSession) -> UnreadCount:
    count = (
        await db.exec(
            select(func.count()).select_from(Notification).where(
                Notification.recipient_id == principal.id, Notification.read_at.is_(None)
            )
        )
    ).one()
    return UnreadCount(count=count)


async def mark_all_read(principal: Principal, db: AsyncSession) -> UnreadCount:
    await db.exec(
        update(Notification)
        .where(Notification.recipient_id == principal.id, Notification.read_at.is_(None))
        .values(read_at=utc_now())
    )
    await db.commit()
    return UnreadCount(count=0)
