"""
Token-bucket rate limiter backed by Redis.
"""

from __future__ import annotations

import os
import time

import redis.asyncio as redis
import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 1000):
        super().__init__(app)
        self.rpm = requests_per_minute
        self.window = 60
        self._redis: redis.Redis | None = None

    async def _get_redis(self) -> redis.Redis:
        if self._redis is None:
            self._redis = redis.from_url(REDIS_URL, decode_responses=True)
        return self._redis

    async def dispatch(self, request: Request, call_next) -> Response:
        # Use IP or user ID as rate limit key
        user_id = getattr(request.state, "user_id", None)
        client_ip = request.client.host if request.client else "unknown"
        key = f"rl:{user_id or client_ip}:{int(time.time()) // self.window}"

        try:
            r = await self._get_redis()
            current = await r.incr(key)
            if current == 1:
                await r.expire(key, self.window)

            remaining = max(0, self.rpm - current)
            reset_at = (int(time.time()) // self.window + 1) * self.window

            if current > self.rpm:
                logger.warning("rate_limit.exceeded", key=key, count=current)
                return JSONResponse(
                    status_code=429,
                    content={"error": "rate_limit_exceeded", "retry_after": reset_at - int(time.time())},
                    headers={
                        "X-RateLimit-Limit": str(self.rpm),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(reset_at),
                        "Retry-After": str(reset_at - int(time.time())),
                    },
                )

            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(self.rpm)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(reset_at)
            return response

        except Exception:
            # Fail open on Redis errors — don't block traffic
            return await call_next(request)
