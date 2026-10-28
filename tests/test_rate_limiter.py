import httpx
import pytest
from fakeredis import FakeAsyncRedis
from fastapi import Depends, FastAPI
from redis.exceptions import ConnectionError as RedisConnectionError

from app.config import Settings
from app.dependencies import get_rate_limiter
from app.interfaces.rate_limit import rate_limit
from app.resilience import (
    FixedWindowRateLimiter,
    TokenBucketRateLimiter,
    build_rate_limiter,
)


class FakeClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
async def redis():
    r = FakeAsyncRedis()
    yield r
    await r.flushall()
    await r.aclose()


async def test_token_bucket_allows_burst_then_blocks(redis):
    clock = FakeClock()
    rl = TokenBucketRateLimiter(redis, capacity=3, refill_per_second=1, clock=clock)
    results = [await rl.check("ip") for _ in range(4)]
    assert [r.allowed for r in results] == [True, True, True, False]
    assert results[0].remaining == 2
    assert results[3].retry_after == pytest.approx(1.0)


async def test_token_bucket_refills_over_time(redis):
    clock = FakeClock()
    rl = TokenBucketRateLimiter(redis, capacity=2, refill_per_second=1, clock=clock)
    await rl.check("ip")
    await rl.check("ip")
    assert (await rl.check("ip")).allowed is False
    clock.now += 1.0
    assert (await rl.check("ip")).allowed is True
    assert (await rl.check("ip")).allowed is False
    clock.now += 100
    assert (await rl.check("ip")).remaining == 1


async def test_token_bucket_keys_are_independent(redis):
    rl = TokenBucketRateLimiter(redis, capacity=1, refill_per_second=0.1)
    assert (await rl.check("a")).allowed is True
    assert (await rl.check("a")).allowed is False
    assert (await rl.check("b")).allowed is True


async def test_fixed_window_blocks_after_limit_and_resets(redis):
    clock = FakeClock(now=600.0)
    rl = FixedWindowRateLimiter(redis, limit=2, window_seconds=60, clock=clock)
    assert (await rl.check("ip")).allowed is True
    assert (await rl.check("ip")).allowed is True
    blocked = await rl.check("ip")
    assert blocked.allowed is False
    assert blocked.remaining == 0
    assert blocked.retry_after >= 1
    clock.now += 60
    assert (await rl.check("ip")).allowed is True


async def test_fixed_window_sets_ttl_on_counter(redis):
    rl = FixedWindowRateLimiter(redis, limit=5, window_seconds=60)
    await rl.check("ip")
    keys = await redis.keys("rl:fw:ip:*")
    assert len(keys) == 1
    assert 0 < await redis.ttl(keys[0]) <= 60


def test_factory_defaults_to_token_bucket(redis):
    s = Settings(_env_file=None)
    assert isinstance(build_rate_limiter(s, redis), TokenBucketRateLimiter)


def test_factory_can_select_fixed_window(redis):
    s = Settings(_env_file=None, rate_limit_algorithm="fixed_window")
    assert isinstance(build_rate_limiter(s, redis), FixedWindowRateLimiter)


def _app(limiter) -> FastAPI:
    app = FastAPI()

    @app.get("/ping", dependencies=[Depends(rate_limit)])
    async def ping():
        return {"ok": True}

    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    return app


async def _get(app: FastAPI, n: int):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        return [await c.get("/ping") for _ in range(n)]


async def test_api_returns_429_with_retry_after(redis):
    rl = TokenBucketRateLimiter(redis, capacity=2, refill_per_second=0.5)
    r1, r2, r3 = await _get(_app(rl), 3)
    assert r1.status_code == r2.status_code == 200
    assert r1.headers["X-RateLimit-Remaining"] == "1"
    assert r3.status_code == 429
    assert int(r3.headers["Retry-After"]) >= 1


async def test_api_fails_open_when_redis_is_down():
    class BrokenLimiter:
        async def check(self, key):
            raise RedisConnectionError("redis is down")

    (r,) = await _get(_app(BrokenLimiter()), 1)
    assert r.status_code == 200
