import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from redis.asyncio import Redis

if TYPE_CHECKING:
    from app.config import Settings


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: float


class RateLimiter(ABC):
    @abstractmethod
    async def check(self, key: str) -> RateLimitResult:
        pass


_TOKEN_BUCKET_LUA = """
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])

local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then
  tokens = capacity
  ts = now
end

local elapsed = math.max(0, now - ts)
tokens = math.min(capacity, tokens + elapsed * rate)

local allowed = 0
local retry_after = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  retry_after = (1 - tokens) / rate
end

redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'ts', tostring(now))
redis.call('EXPIRE', KEYS[1], ttl)
return {allowed, tostring(tokens), tostring(retry_after)}
"""

_FIXED_WINDOW_LUA = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
local ttl = redis.call('TTL', KEYS[1])
if ttl < 0 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
  ttl = tonumber(ARGV[1])
end
return {count, ttl}
"""


class TokenBucketRateLimiter(RateLimiter):
    def __init__(
        self,
        redis: Redis,
        capacity: int,
        refill_per_second: float,
        prefix: str = "rl:tb:",
        clock: Callable[[], float] = time.time,
    ) -> None:
        if capacity < 1 or refill_per_second <= 0:
            raise ValueError("capacity must be >= 1 and refill_per_second > 0")
        self._redis = redis
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._prefix = prefix
        self._clock = clock
        self._script = redis.register_script(_TOKEN_BUCKET_LUA)
        self._ttl = max(1, int(capacity / refill_per_second) + 1)

    async def check(self, key: str) -> RateLimitResult:
        allowed, tokens, retry_after = await self._script(
            keys=[self._prefix + key],
            args=[self.capacity, self.refill_per_second, self._clock(), self._ttl],
        )
        return RateLimitResult(
            allowed=bool(int(allowed)),
            limit=self.capacity,
            remaining=int(float(tokens)),
            retry_after=float(retry_after),
        )


class FixedWindowRateLimiter(RateLimiter):
    def __init__(
        self,
        redis: Redis,
        limit: int,
        window_seconds: int,
        prefix: str = "rl:fw:",
        clock: Callable[[], float] = time.time,
    ) -> None:
        if limit < 1 or window_seconds < 1:
            raise ValueError("limit and window_seconds must be >= 1")
        self._redis = redis
        self.limit = limit
        self.window_seconds = window_seconds
        self._prefix = prefix
        self._clock = clock
        self._script = redis.register_script(_FIXED_WINDOW_LUA)

    async def check(self, key: str) -> RateLimitResult:
        window = int(self._clock() // self.window_seconds)
        count, ttl = await self._script(
            keys=[f"{self._prefix}{key}:{window}"],
            args=[self.window_seconds],
        )
        count, ttl = int(count), int(ttl)
        allowed = count <= self.limit
        return RateLimitResult(
            allowed=allowed,
            limit=self.limit,
            remaining=max(0, self.limit - count),
            retry_after=0.0 if allowed else float(max(ttl, 1)),
        )


def build_rate_limiter(settings: "Settings", redis: Redis) -> RateLimiter:
    if settings.rate_limit_algorithm == "fixed_window":
        return FixedWindowRateLimiter(
            redis,
            limit=settings.rate_limit_window_limit,
            window_seconds=settings.rate_limit_window_seconds,
        )
    return TokenBucketRateLimiter(
        redis,
        capacity=settings.rate_limit_bucket_capacity,
        refill_per_second=settings.rate_limit_refill_per_second,
    )
