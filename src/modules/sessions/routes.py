import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.permissions import Principal, require_approved
from src.core.rate_limiter import RateLimiter
from src.db.mains import get_session
from src.models.enums import SessionStatus
from src.modules.sessions import service
from src.modules.sessions.schema import ChallengeOut, SessionCreate, SessionOut, SessionUpdate
from src.shared.schemas import Page, PageParams

session_router = APIRouter()

# The executive's screen asks for a new code every ~15s; this leaves generous headroom.
challenge_limiter = RateLimiter(max_requests=30, window_seconds=60, scope="qr-challenge")


@session_router.get("", response_model=Page[SessionOut])
async def list_sessions(
    group_id: Optional[uuid.UUID] = Query(None, alias="groupId"),
    status_filter: Optional[SessionStatus] = Query(None, alias="status"),
    params: PageParams = Depends(),
    principal: Principal = Depends(require_approved),
    db: AsyncSession = Depends(get_session),
):
    """Sessions in groups the caller belongs to or manages, newest first."""
    return await service.list_sessions(principal, group_id, status_filter, params, db)


@session_router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(data: SessionCreate, request: Request, principal: Principal = Depends(require_approved),
                         db: AsyncSession = Depends(get_session)):
    return await service.create_session(data, principal, request, db)


@session_router.get("/{session_id}", response_model=SessionOut)
async def get_session_detail(session_id: uuid.UUID, principal: Principal = Depends(require_approved),
                             db: AsyncSession = Depends(get_session)):
    return await service.get_session(session_id, principal, db)


@session_router.patch("/{session_id}", response_model=SessionOut)
async def update_session(session_id: uuid.UUID, data: SessionUpdate, request: Request,
                         principal: Principal = Depends(require_approved), db: AsyncSession = Depends(get_session)):
    return await service.update_session(session_id, data, principal, request, db)


def _transition_route(action: str):
    async def handler(session_id: uuid.UUID, request: Request, principal: Principal = Depends(require_approved),
                      db: AsyncSession = Depends(get_session)):
        return await service.transition(session_id, action, principal, request, db)

    handler.__name__ = f"{action}_session"
    return handler


for _action in ("start", "close", "archive", "cancel"):
    session_router.add_api_route(f"/{{session_id}}/{_action}", _transition_route(_action), methods=["POST"],
                                 response_model=SessionOut, name=f"{_action}_session")


@session_router.post("/{session_id}/challenges", response_model=ChallengeOut, status_code=status.HTTP_201_CREATED)
async def issue_challenge(session_id: uuid.UUID, principal: Principal = Depends(require_approved),
                          db: AsyncSession = Depends(get_session)):
    await challenge_limiter.check(f"user:{principal.id}")
    return await service.issue_challenge(session_id, principal, db)
