import uuid
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.config import Config


def asyncpg_connect_args(url: str) -> dict:
    """Shared by the app engine and Alembic."""
    if "+asyncpg" not in url:
        return {}
    # Give a serverless Postgres (Neon) up to 60s to wake up.
    args: dict = {"command_timeout": 60, "timeout": 60}
    if "-pooler" in url:
        # Neon's pooler is PgBouncer in transaction mode: prepared statements can't be cached
        # per connection, and their names must be unique across backends.
        args["statement_cache_size"] = 0
        args["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid.uuid4().hex}__"
    return args


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        return {}
    return {
        "pool_pre_ping": True,  # test connections before use
        "pool_recycle": 1800,  # refresh idle connections (Neon suspends idle compute)
        "pool_size": 10,
        "max_overflow": 10,
        "connect_args": asyncpg_connect_args(url),
    }


async_engine = create_async_engine(Config.DATABASE_URL, echo=False, **_engine_kwargs(Config.DATABASE_URL))

AsyncSessionLocal = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """One session per request. Services commit explicitly; anything uncommitted is rolled back."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
