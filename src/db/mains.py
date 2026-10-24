from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from src.core.config import Config


async_engine = create_async_engine(
    Config.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,      #Tests connections before using them to prevent crashes
    pool_recycle=1800,       # Automatically refreshes dead or sleeping connections
    connect_args={
        "command_timeout": 60, # Gives Neon up to 60 seconds to wake up before failing
        "timeout": 60   
    }
)

async def init_db() -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


AsyncSessionLocal = sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session