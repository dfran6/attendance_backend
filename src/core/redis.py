"""Optional Redis connection. Redis holds only short-lived state (rate limits, OTPs);
nothing authoritative lives here. When REDIS_URL is unset (local dev/tests) these
helpers degrade gracefully and callers must not depend on Redis for correctness."""
from typing import Optional

from redis import asyncio as aioredis

from src.core.config import Config

redis_client: Optional[aioredis.Redis] = (
    aioredis.from_url(Config.REDIS_URL, decode_responses=True) if Config.REDIS_URL else None
)


def get_redis() -> Optional[aioredis.Redis]:
    return redis_client


async def store_otp(email: str, otp: str, expiry: int = 300) -> None:
    if redis_client is None:
        raise RuntimeError("Redis is required for OTP storage")
    await redis_client.set(f"otp:{email}", otp, ex=expiry)


async def verify_otp(email: str, otp: str) -> bool:
    """Single-use: the OTP is deleted on successful verification."""
    if redis_client is None:
        return False
    key = f"otp:{email}"
    stored = await redis_client.get(key)
    if stored and stored == otp:
        await redis_client.delete(key)
        return True
    return False
