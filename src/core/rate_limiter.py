"""Fixed-window rate limiting as a FastAPI dependency.

Uses Redis when configured so limits hold across workers. Without Redis (dev/tests only;
production config refuses to start without it) an in-process counter is used.
"""
import time
from collections import defaultdict
from typing import Dict, Tuple

from fastapi import Request

from src.core.exceptions import AppError, ErrorCode
from src.core.redis import get_redis

_memory: Dict[str, Tuple[int, float]] = defaultdict(lambda: (0, 0.0))


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _hit(key: str, window: int) -> int:
    redis = get_redis()
    if redis is not None:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window)
        return int(count)
    count, reset_at = _memory[key]
    now = time.monotonic()
    if now >= reset_at:
        count, reset_at = 0, now + window
    count += 1
    _memory[key] = (count, reset_at)
    return count


def reset_memory_limits() -> None:
    _memory.clear()


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int, scope: str):
        self.max_requests = max_requests
        self.window = window_seconds
        self.scope = scope

    async def __call__(self, request: Request) -> None:
        await self.check(f"ip:{client_ip(request)}")

    async def check(self, identity: str) -> None:
        """Limit by an arbitrary identity, e.g. a user id when many users share one IP."""
        key = f"rl:{self.scope}:{identity}"
        if await _hit(key, self.window) > self.max_requests:
            raise AppError(
                429,
                ErrorCode.RATE_LIMITED,
                "Too many attempts. Please wait a moment and try again.",
                {"retryAfterSeconds": self.window},
            )
