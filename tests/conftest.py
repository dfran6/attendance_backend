"""Test harness: isolated SQLite database (synthetic data only), recreated for every test.

Environment is set before any `src` import because settings and the engine are built at import time.
"""
import os
import tempfile
import uuid
from datetime import timedelta
from typing import Optional

_DB_FILE = os.path.join(tempfile.gettempdir(), f"cds_attend_test_{os.getpid()}.db")
os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": f"sqlite+aiosqlite:///{_DB_FILE}",
        "JWT_SECRET": "test-secret-key-that-is-long-enough-0123456789",
        "JWT_ALGORITHM": "HS256",
        "REDIS_URL": "",
        "COOKIE_SECURE": "false",
    }
)

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from src.core.rate_limiter import reset_memory_limits  # noqa: E402
from src.core.security import hash_password  # noqa: E402
from src.db.mains import AsyncSessionLocal, async_engine  # noqa: E402
from src.main import app  # noqa: E402
from src.models import AdminArea, CdsGroup, CdsSession, Membership, RoleAssignment, User  # noqa: E402
from src.models.base import utc_now  # noqa: E402
from src.models.enums import AccountStatus, AdminRole, MembershipRole, MembershipStatus, SessionStatus  # noqa: E402

PASSWORD = "Corper2024pass"


@pytest.fixture(autouse=True)
async def _database():
    reset_memory_limits()
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    yield
    await async_engine.dispose()


@pytest.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


class ApiClient(httpx.AsyncClient):
    """Behaves like the browser app: fetches a CSRF token and sends it on unsafe requests."""

    async def prime_csrf(self) -> None:
        token = (await self.get("/api/v1/auth/csrf")).json()["csrfToken"]
        self.headers["X-CSRF-Token"] = token

    async def login(self, identifier: str, password: str = PASSWORD) -> httpx.Response:
        if "X-CSRF-Token" not in self.headers:
            await self.prime_csrf()
        return await self.post("/api/v1/auth/login", json={"identifier": identifier, "password": password})


@pytest.fixture
def make_client():
    clients = []

    async def _make() -> ApiClient:
        c = ApiClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
        clients.append(c)
        return c

    yield _make


@pytest.fixture
async def client(make_client) -> ApiClient:
    c = await make_client()
    await c.prime_csrf()
    return c


class Factory:
    def __init__(self, session):
        self.s = session
        self._n = 0

    def _next(self) -> int:
        self._n += 1
        return self._n

    async def area(self, name: str = "Ikeja") -> AdminArea:
        n = self._next()
        area = AdminArea(name=f"{name} {n}", code=f"AREA{n}", state="Lagos")
        self.s.add(area)
        await self.s.commit()
        return area

    async def group(self, area: AdminArea, name: str = "Health", active: bool = True) -> CdsGroup:
        n = self._next()
        group = CdsGroup(area_id=area.id, name=f"{name} {n}", code=f"GRP{n}", is_active=active)
        self.s.add(group)
        await self.s.commit()
        return group

    async def user(self, status: AccountStatus = AccountStatus.approved, **kw) -> User:
        n = self._next()
        user = User(
            full_name=kw.get("full_name", f"Corps Member {n}"),
            email=kw.get("email", f"user{n}@example.com"),
            state_code=kw.get("state_code", f"LA/24A/{1000 + n}"),
            password_hash=hash_password(PASSWORD),
            account_status=status,
        )
        self.s.add(user)
        await self.s.commit()
        return user

    async def member(self, group: CdsGroup, *, role: MembershipRole = MembershipRole.member,
                     status: MembershipStatus = MembershipStatus.approved) -> User:
        account = AccountStatus.approved if status == MembershipStatus.approved else AccountStatus.pending
        user = await self.user(status=account)
        self.s.add(Membership(user_id=user.id, group_id=group.id, role=role, status=status))
        await self.s.commit()
        return user

    async def lgi(self, area: AdminArea) -> User:
        user = await self.user()
        self.s.add(RoleAssignment(user_id=user.id, role=AdminRole.lgi, area_id=area.id))
        await self.s.commit()
        return user

    async def cds_session(self, group: CdsGroup, creator: User, *, status: SessionStatus = SessionStatus.scheduled,
                          starts_in: timedelta = timedelta(minutes=30), started_ago: Optional[timedelta] = None,
                          geofence: Optional[tuple] = None, late_after_minutes: int = 30) -> CdsSession:
        start = utc_now() + starts_in
        cds = CdsSession(group_id=group.id, created_by_id=creator.id, title="Thursday CDS", venue="LGA Hall",
                         scheduled_start=start, scheduled_end=start + timedelta(hours=3), status=status,
                         late_after_minutes=late_after_minutes)
        if started_ago is not None or status == SessionStatus.active:
            cds.actual_start = utc_now() - (started_ago or timedelta(0))
        if geofence:
            cds.latitude, cds.longitude, cds.radius_m = geofence
        self.s.add(cds)
        await self.s.commit()
        return cds

    async def super_admin(self) -> User:
        user = await self.user()
        self.s.add(RoleAssignment(user_id=user.id, role=AdminRole.super_admin))
        await self.s.commit()
        return user


@pytest.fixture
def factory(db) -> Factory:
    return Factory(db)


async def membership_id_for(db, user_id: uuid.UUID) -> uuid.UUID:
    from sqlmodel import select

    return (await db.exec(select(Membership.id).where(Membership.user_id == user_id))).first()
