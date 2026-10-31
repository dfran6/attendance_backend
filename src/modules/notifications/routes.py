from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.permissions import Principal, require_approved
from src.db.mains import get_session
from src.modules.notifications import service
from src.modules.notifications.schema import NotificationOut, UnreadCount
from src.shared.schemas import Page, PageParams

notification_router = APIRouter()


@notification_router.get("", response_model=Page[NotificationOut])
async def list_notifications(params: PageParams = Depends(), principal: Principal = Depends(require_approved),
                             db: AsyncSession = Depends(get_session)):
    return await service.list_notifications(principal, params, db)


@notification_router.get("/unread-count", response_model=UnreadCount)
async def unread_count(principal: Principal = Depends(require_approved), db: AsyncSession = Depends(get_session)):
    return await service.unread_count(principal, db)


@notification_router.post("/mark-read", response_model=UnreadCount)
async def mark_read(principal: Principal = Depends(require_approved), db: AsyncSession = Depends(get_session)):
    return await service.mark_all_read(principal, db)
