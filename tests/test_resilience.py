import asyncio

import httpx
import pytest
from fastapi import FastAPI

from app.adapters.notifier import NotificationClient
from app.config import Settings
from app.core.entities import Task
from app.interfaces.middleware import DeadlineMiddleware
from app.resilience import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
    DeadlineExceededError,
    deadline_scope,
    remaining_time,
    retry_async,
)


async def test_deadline_cancels_slow_work():
    with pytest.raises(DeadlineExceededError):
        async with deadline_scope(0.05):
            await asyncio.sleep(1)


async def test_nested_deadline_can_only_narrow():
    async with deadline_scope(0.5):
        async with deadline_scope(10):
            assert remaining_time() <= 0.5
        async with deadline_scope(0.1):
            assert remaining_time() <= 0.1


async def test_deadline_is_cleared_after_scope():
    async with deadline_scope(1):
        pass
    assert remaining_time() is None


async def test_deadline_does_not_mask_foreign_timeout_error():
    with pytest.raises(TimeoutError):
        async with deadline_scope(5):
            raise TimeoutError("socket timeout")


async def test_deadline_middleware_returns_504():
    app = FastAPI()
    app.add_middleware(DeadlineMiddleware)

    @app.get("/slow")
    async def slow():
        await asyncio.sleep(1)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/slow", headers={"X-Request-Timeout": "0.05"})
    assert r.status_code == 504


async def _no_sleep(_: float) -> None:
    return None


async def test_retry_succeeds_after_transient_errors():
    calls = 0

    async def flaky():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ConnectionError("boom")
        return "ok"

    result = await retry_async(
        flaky, max_attempts=3, retry_on=(ConnectionError,), sleep=_no_sleep
    )
    assert result == "ok" and calls == 3


async def test_retry_gives_up_after_max_attempts():
    calls = 0

    async def always_fails():
        nonlocal calls
        calls += 1
        raise ConnectionError("boom")

    with pytest.raises(ConnectionError):
        await retry_async(
            always_fails, max_attempts=3, retry_on=(ConnectionError,), sleep=_no_sleep
        )
    assert calls == 3


async def test_retry_does_not_retry_non_transient_errors():
    calls = 0

    async def bad_request():
        nonlocal calls
        calls += 1
        raise ValueError("4xx")

    with pytest.raises(ValueError):
        await retry_async(
            bad_request, max_attempts=5, retry_on=(ConnectionError,), sleep=_no_sleep
        )
    assert calls == 1


async def test_retry_stops_when_deadline_budget_is_too_small():
    calls = 0

    async def always_fails():
        nonlocal calls
        calls += 1
        raise ConnectionError("boom")

    async with deadline_scope(0.5):
        with pytest.raises(ConnectionError):
            await retry_async(
                always_fails,
                max_attempts=10,
                base_delay=100,  # любая пауза заведомо больше бюджета
                max_delay=100,
                retry_on=(ConnectionError,),
                sleep=_no_sleep,
            )
    assert calls == 1


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def _fail():
    raise ConnectionError("down")


async def _ok():
    return "ok"


def _breaker(clock: FakeClock) -> CircuitBreaker:
    return CircuitBreaker(
        "t",
        failure_threshold=3,
        recovery_timeout=10,
        expected_exceptions=(ConnectionError,),
        clock=clock,
    )


async def test_breaker_opens_after_threshold_and_rejects_calls():
    cb = _breaker(FakeClock())
    for _ in range(3):
        with pytest.raises(ConnectionError):
            await cb.call(_fail)
    assert cb.state is CircuitState.OPEN
    with pytest.raises(CircuitBreakerOpenError):
        await cb.call(_ok)


async def test_breaker_half_open_success_closes():
    clock = FakeClock()
    cb = _breaker(clock)
    for _ in range(3):
        with pytest.raises(ConnectionError):
            await cb.call(_fail)
    clock.now = 10
    assert cb.state is CircuitState.HALF_OPEN
    assert await cb.call(_ok) == "ok"
    assert cb.state is CircuitState.CLOSED


async def test_breaker_half_open_failure_reopens():
    clock = FakeClock()
    cb = _breaker(clock)
    for _ in range(3):
        with pytest.raises(ConnectionError):
            await cb.call(_fail)
    clock.now = 10
    with pytest.raises(ConnectionError):
        await cb.call(_fail)
    assert cb.state is CircuitState.OPEN
    with pytest.raises(CircuitBreakerOpenError):
        await cb.call(_ok)


async def test_breaker_success_resets_failure_count():
    cb = _breaker(FakeClock())
    for _ in range(2):
        with pytest.raises(ConnectionError):
            await cb.call(_fail)
    await cb.call(_ok)
    for _ in range(2):
        with pytest.raises(ConnectionError):
            await cb.call(_fail)
    assert cb.state is CircuitState.CLOSED


async def test_breaker_ignores_unexpected_exceptions():
    cb = _breaker(FakeClock())

    async def bad_request():
        raise ValueError("not a dependency failure")

    for _ in range(5):
        with pytest.raises(ValueError):
            await cb.call(bad_request)
    assert cb.state is CircuitState.CLOSED


def _task() -> Task:
    return Task(id=1, title="t", description="d", completed=False, created_at=None)


def _settings(**kw) -> Settings:
    base = dict(
        notification_service_url="http://notify.local/events",
        retry_max_attempts=3,
        cb_failure_threshold=3,
        cb_recovery_timeout_seconds=30,
    )
    base.update(kw)
    return Settings(_env_file=None, **base)


def _client(handler, **settings_kw) -> NotificationClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return NotificationClient(_settings(**settings_kw), http, sleep=_no_sleep)


async def test_notifier_retries_5xx_then_succeeds():
    statuses = iter([503, 500, 200])
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers["Idempotency-Key"])
        return httpx.Response(next(statuses))

    n = _client(handler)
    assert await n.notify_task_created(_task()) is True
    assert calls == ["task-created-1"] * 3


async def test_notifier_does_not_retry_4xx():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400)

    n = _client(handler)
    assert await n.notify_task_created(_task()) is False
    assert calls == 1
    assert n.breaker.state is CircuitState.CLOSED


async def test_notifier_opens_circuit_and_stops_calling_dependency():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("down")

    n = _client(handler)
    assert await n.notify_task_created(_task()) is False
    assert n.breaker.state is CircuitState.OPEN
    assert calls == 3
    assert await n.notify_task_created(_task()) is False
    assert calls == 3


async def test_notifier_disabled_without_url():
    n = NotificationClient(_settings(notification_service_url=None), sleep=_no_sleep)
    assert await n.notify_task_created(_task()) is False
    await n.aclose()


async def test_notifier_reraises_when_request_deadline_is_exhausted():
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200)

    n = _client(slow, notification_timeout_seconds=5, notification_budget_seconds=5)
    with pytest.raises(DeadlineExceededError):
        async with deadline_scope(0.05):
            await n.notify_task_created(_task())


async def test_notifier_degrades_when_only_its_own_budget_is_exhausted():
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200)

    n = _client(slow, notification_timeout_seconds=5, notification_budget_seconds=0.05)
    async with deadline_scope(5):
        assert await n.notify_task_created(_task()) is False
