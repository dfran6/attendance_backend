import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlmodel import or_, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.config import Config
from src.core.exceptions import AppError, ErrorCode, conflict, forbidden, unauthorized
from src.core.security import (
    create_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    password_needs_rehash,
    verify_password,
)
from src.models import AuthSession, CdsGroup, Membership, User
from src.models.base import as_utc, utc_now
from src.models.enums import AccountStatus
from src.modules.audit import service as audit
from src.modules.auth.schema import LoginRequest, RegisterRequest, normalize_email, normalize_state_code

# Two tabs refreshing at once both present the same token; the loser must not be
# treated as a theft attempt. Within this window a rotated token is refused but the
# family is left intact, and the client retries with the newer cookie.
REFRESH_REUSE_GRACE = timedelta(seconds=15)
UTC_PLUS_ONE = timezone(timedelta(hours=1))


class IssuedTokens:
    def __init__(self, access_token: str, refresh_token: str, auth_session: AuthSession):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.auth_session = auth_session


class AuthService:
    async def get_user_by_statecode(self, statecode: str, session: AsyncSession) -> Optional[User]:
        result = await session.exec(select(User).where(User.state_code == normalize_state_code(statecode)))
        return result.first()

    async def get_user_by_identifier(self, identifier: str, session: AsyncSession) -> Optional[User]:
        identifier = identifier.strip()
        result = await session.exec(
            select(User).where(
                or_(User.email == normalize_email(identifier), User.state_code == normalize_state_code(identifier))
            )
        )
        return result.first()

    # ---- registration ---------------------------------------------------------------

    async def register(self, data: RegisterRequest, request: Request, session: AsyncSession) -> Tuple[User, IssuedTokens]:
        group = await session.get(CdsGroup, data.group_id)
        if group is None or not group.is_active:
            raise AppError(422, ErrorCode.VALIDATION_ERROR, "Some fields are invalid.",
                           {"fields": {"groupId": "Select an active CDS group."}})

        # Friendly pre-checks; the unique constraints below are the real guarantee.
        existing = (
            await session.exec(select(User).where(or_(User.email == data.email, User.state_code == data.state_code)))
        ).all()
        for u in existing:
            if u.email == data.email:
                raise conflict("An account with this email already exists.", ErrorCode.EMAIL_TAKEN,
                               {"fields": {"email": "This email is already registered."}})
            raise conflict("An account with this state code already exists.", ErrorCode.STATE_CODE_TAKEN,
                           {"fields": {"stateCode": "This state code is already registered."}})

        user = User(
            full_name=data.full_name,
            email=data.email,
            state_code=data.state_code,
            phone=data.phone,
            password_hash=hash_password(data.password),
            account_status=AccountStatus.pending,
        )
        session.add(user)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            raise conflict("An account with these details already exists.")

        session.add(Membership(user_id=user.id, group_id=group.id))
        audit.record(session, "auth.registered", actor_id=user.id, target_type="user", target_id=user.id,
                     group_id=group.id, area_id=group.area_id, request=request)
        tokens = await self._issue(user, request, session)
        await session.commit()
        return user, tokens

    # ---- login / sessions -----------------------------------------------------------

    async def login(self, data: LoginRequest, request: Request, session: AsyncSession) -> Tuple[User, IssuedTokens]:
        user = await self.get_user_by_identifier(data.identifier, session)
        # verify_password runs against a dummy hash for unknown users (constant-ish timing).
        if not verify_password(data.password, user.password_hash if user else None) or user is None:
            audit.record(session, "auth.login_failed", actor_id=user.id if user else None, request=request,
                         context={"reason": "bad_credentials"})
            await session.commit()
            raise unauthorized("Incorrect email/state code or password.", ErrorCode.INVALID_CREDENTIALS)

        if user.account_status == AccountStatus.suspended:
            audit.record(session, "auth.login_blocked", actor_id=user.id, request=request,
                         context={"reason": "suspended"})
            await session.commit()
            raise forbidden("This account has been suspended.", ErrorCode.ACCOUNT_SUSPENDED)

        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(data.password)
        user.last_login_at = utc_now()
        session.add(user)
        tokens = await self._issue(user, request, session)
        audit.record(session, "auth.login", actor_id=user.id, request=request)
        await session.commit()
        return user, tokens

    async def refresh(self, raw_token: Optional[str], request: Request, session: AsyncSession) -> IssuedTokens:
        if not raw_token:
            raise unauthorized("Your session has expired.", ErrorCode.SESSION_EXPIRED)

        current = (
            await session.exec(
                select(AuthSession).where(AuthSession.token_hash == hash_token(raw_token)).with_for_update()
            )
        ).first()
        if current is None:
            raise unauthorized("Your session has expired.", ErrorCode.SESSION_EXPIRED)

        now = utc_now()
        if current.revoked_at is not None:
            rotated_recently = current.replaced_by_id is not None and now - as_utc(current.revoked_at) < REFRESH_REUSE_GRACE
            if not rotated_recently:
                # A rotated token was replayed: assume theft and end every session in the family.
                await session.execute(
                    update(AuthSession)
                    .where(AuthSession.family_id == current.family_id, AuthSession.revoked_at.is_(None))
                    .values(revoked_at=now)
                )
                audit.record(session, "auth.refresh_reuse_detected", actor_id=current.user_id, request=request,
                             target_type="auth_session_family", target_id=current.family_id)
                await session.commit()
            raise unauthorized("Your session has expired.", ErrorCode.SESSION_EXPIRED)

        if as_utc(current.expires_at) <= now:
            raise unauthorized("Your session has expired.", ErrorCode.SESSION_EXPIRED)

        user = await session.get(User, current.user_id)
        if user is None or user.account_status == AccountStatus.suspended:
            current.revoked_at = now
            session.add(current)
            await session.commit()
            raise unauthorized("Your session has ended.", ErrorCode.SESSION_EXPIRED)

        tokens = await self._issue(user, request, session, family_id=current.family_id)
        current.revoked_at = now
        current.replaced_by_id = tokens.auth_session.id
        session.add(current)
        await session.commit()
        return tokens

    async def logout(self, raw_refresh: Optional[str], session_id: Optional[uuid.UUID], request: Request,
                     session: AsyncSession) -> None:
        conditions = []
        if raw_refresh:
            conditions.append(AuthSession.token_hash == hash_token(raw_refresh))
        if session_id:
            conditions.append(AuthSession.id == session_id)
        if not conditions:
            return
        current = (await session.exec(select(AuthSession).where(or_(*conditions)))).first()
        if current is None:
            return
        await session.execute(
            update(AuthSession)
            .where(AuthSession.family_id == current.family_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=utc_now())
        )
        audit.record(session, "auth.logout", actor_id=current.user_id, request=request)
        await session.commit()

    async def _issue(self, user: User, request: Request, session: AsyncSession,
                     family_id: Optional[uuid.UUID] = None) -> IssuedTokens:
        raw = new_refresh_token()
        auth_session = AuthSession(
            user_id=user.id,
            family_id=family_id or uuid.uuid4(),
            token_hash=hash_token(raw),
            expires_at=datetime.now(UTC_PLUS_ONE) + timedelta(days=Config.REFRESH_TOKEN_EXPIRE_DAYS),
            user_agent=(request.headers.get("user-agent") or "")[:255] or None,
            ip_address=request.client.host if request.client else None,
        )
        session.add(auth_session)
        await session.flush()
        return IssuedTokens(create_access_token(user.id, auth_session.id), raw, auth_session)


auth_service = AuthService()
