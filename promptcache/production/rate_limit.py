"""Redis-backed fixed-window rate limiting with per-surface configuration."""
import logging
import os
from redis import Redis
from redis.exceptions import RedisError

logger = logging.getLogger("promptcache")


class RateLimitExceeded(Exception): pass


class RateLimiter:
    """Fixed-window limiter. Fails open when Redis is unavailable so a Redis
    outage never turns into a hard outage of the gateway itself."""

    def __init__(self, url: str | None = None, limit: int | None = None, window_seconds: int = 60, name: str = "tenant"):
        self.limit = limit if limit is not None else int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
        self.window_seconds = window_seconds
        self.name = name
        resolved_url = url or os.getenv("REDIS_URL") or "redis://localhost:6379/0"
        self.client = Redis.from_url(resolved_url, decode_responses=True)

    def check(self, tenant: str, limit: int | None = None) -> None:
        key = f"promptcache:rate:{self.name}:{tenant}"
        try:
            with self.client.pipeline() as pipe:
                pipe.incr(key); pipe.ttl(key); count, ttl = pipe.execute()
                if ttl < 0: self.client.expire(key, self.window_seconds)
        except RedisError as exc:
            logger.warning("rate limiter unavailable (%s); failing open", exc)
            return
        if count > (limit if limit is not None else self.limit): raise RateLimitExceeded()
