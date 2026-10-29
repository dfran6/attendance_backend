from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.permissions import Principal, get_principal
from src.db.mains import get_session
from src.modules.users import service
from src.modules.users.schema import MeResponse, UpdateMeRequest

user_router = APIRouter()


@user_router.get("/me", response_model=MeResponse)
async def get_me(principal: Principal = Depends(get_principal), session: AsyncSession = Depends(get_session)):
    """Available to pending users too, so the client can route them to the approval screen."""
    return await service.build_me(principal.user, session, principal)


@user_router.patch("/me", response_model=MeResponse)
async def patch_me(data: UpdateMeRequest, principal: Principal = Depends(get_principal),
                   session: AsyncSession = Depends(get_session)):
    user = await service.update_me(principal, data, session)
    return await service.build_me(user, session, principal)
