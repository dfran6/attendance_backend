
from fastapi import Request, HTTPException

from src.core.redis import redis_client


class RateLimiter():
    def __init__(self, max_requests: int, window: int):
        self.max_requests = max_requests
        self.window = window

    async def __call__(self, request: Request):
        user = request.state.user

        if user:
            identifier = f"user:{user['user_uid']}"
        else:
            identifier = f"ip:{request.client.host}"

        key = f"rate_limit:{identifier}:{request.url.path}"

        count = await redis_client.incr(key)

        if count == 1:
            await redis_client.expire(key, self.window)

        if count > self.max_requests:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Slow down!!"
            )