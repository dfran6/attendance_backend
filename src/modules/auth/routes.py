import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response, status
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.config import Config
from src.core.csrf import CSRF_COOKIE
from src.core.permissions import ACCESS_COOKIE
from src.core.rate_limiter import RateLimiter
from src.core.security import TokenExpired, TokenInvalid, decode_access_token, new_csrf_token
from src.db.mains import get_session
from src.modules.auth.schema import CsrfResponse, LoginRequest, RegisterRequest
from src.modules.auth.service import IssuedTokens, auth_service
from src.modules.users.schema import MeResponse
from src.modules.users.service import build_me
from src.shared.schemas import Message

auth_router = APIRouter()

REFRESH_COOKIE = "cds_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"

login_limiter = RateLimiter(max_requests=10, window_seconds=60, scope="login")
register_limiter = RateLimiter(max_requests=5, window_seconds=300, scope="register")
refresh_limiter = RateLimiter(max_requests=60, window_seconds=60, scope="refresh")


def _cookie_kwargs() -> dict:
    return {"secure": Config.COOKIE_SECURE, "samesite": Config.COOKIE_SAMESITE, "domain": Config.COOKIE_DOMAIN}


def _set_auth_cookies(response: Response, tokens: IssuedTokens) -> None:
    response.set_cookie(ACCESS_COOKIE, tokens.access_token, httponly=True, path="/",
                        max_age=Config.ACCESS_TOKEN_EXPIRE_MINUTES * 60, **_cookie_kwargs())
    response.set_cookie(REFRESH_COOKIE, tokens.refresh_token, httponly=True, path=REFRESH_COOKIE_PATH,
                        max_age=Config.REFRESH_TOKEN_EXPIRE_DAYS * 86400, **_cookie_kwargs())


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/", **_cookie_kwargs())
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, **_cookie_kwargs())


@auth_router.get("/csrf", response_model=CsrfResponse)
async def csrf(response: Response):
    """Issue a CSRF token (cookie + body). Call once on app load and after it is rejected."""
    token = new_csrf_token()
    response.set_cookie(CSRF_COOKIE, token, httponly=False, path="/", max_age=86400, **_cookie_kwargs())
    return CsrfResponse(csrf_token=token)


@auth_router.post("/register", response_model=MeResponse, status_code=status.HTTP_201_CREATED,
                  dependencies=[Depends(register_limiter)])
async def register(data: RegisterRequest, request: Request, response: Response,
                   session: AsyncSession = Depends(get_session)):
    """Creates a pending account and a pending membership request, and signs the user in
    so they can see their approval status."""
    user, tokens = await auth_service.register(data, request, session)
    _set_auth_cookies(response, tokens)
    return await build_me(user, session)


@auth_router.post("/login", response_model=MeResponse, dependencies=[Depends(login_limiter)])
async def login(data: LoginRequest, request: Request, response: Response,
                session: AsyncSession = Depends(get_session)):
    user, tokens = await auth_service.login(data, request, session)
    _set_auth_cookies(response, tokens)
    return await build_me(user, session)


@auth_router.post("/refresh", response_model=Message, dependencies=[Depends(refresh_limiter)])
async def refresh(request: Request, response: Response, session: AsyncSession = Depends(get_session)):
    tokens = await auth_service.refresh(request.cookies.get(REFRESH_COOKIE), request, session)
    _set_auth_cookies(response, tokens)
    return Message(message="Session refreshed.")


@auth_router.post("/logout", response_model=Message)
async def logout(request: Request, response: Response, session: AsyncSession = Depends(get_session)):
    """Idempotent: always clears cookies, and revokes the server-side session when identifiable."""
    session_id: Optional[uuid.UUID] = None
    access = request.cookies.get(ACCESS_COOKIE)
    if access:
        try:
            session_id = uuid.UUID(decode_access_token(access)["sid"])
        except (TokenExpired, TokenInvalid, KeyError, ValueError):
            session_id = None
    await auth_service.logout(request.cookies.get(REFRESH_COOKIE), session_id, request, session)
    _clear_auth_cookies(response)
    return Message(message="Signed out.")
