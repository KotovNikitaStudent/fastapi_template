"""Клиент внешнего сервиса уведомлений, защищённый паттернами отказоустойчивости.

Порядок слоёв (снаружи внутрь):
    deadline (бюджет на уведомление, не шире дедлайна запроса)
      └─ retry (backoff + jitter, только transient-ошибки)
           └─ circuit breaker (каждая попытка проходит через него)
                └─ HTTP-вызов с таймаутом попытки

Retry стоит снаружи breaker-а: breaker видит каждую неудачную попытку и,
разомкнувшись, мгновенно прерывает дальнейшие повторы (CircuitBreakerOpenError
не входит в retry_on).

Уведомление вторично по отношению к созданию задачи, поэтому при любом сбое
деградируем мягко: логируем и возвращаем False, а задачу не теряем.
Исключение — исчерпание дедлайна самого запроса: оно пробрасывается наружу.
"""

import asyncio
import logging
from typing import Awaitable, Callable

import httpx

from app.config import Settings
from app.core.entities import Task
from app.resilience import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    DeadlineExceededError,
    current_deadline,
    deadline_scope,
    remaining_time,
    retry_async,
)

logger = logging.getLogger(__name__)


class TransientNotificationError(Exception):
    """Временный сбой зависимости (5xx / 429): имеет смысл повторить."""


class PermanentNotificationError(Exception):
    """Зависимость отклонила запрос (4xx): повтор не поможет и breaker не трогаем."""


# Ошибки, которые считаем сбоем самой зависимости.
_DEPENDENCY_FAILURES = (httpx.TransportError, TransientNotificationError)


class NotificationClient:
    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
        breaker: CircuitBreaker | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._http = http_client or httpx.AsyncClient()
        self._owns_http = http_client is None
        self._sleep = sleep
        self.breaker = breaker or CircuitBreaker(
            name="notification-service",
            failure_threshold=settings.cb_failure_threshold,
            recovery_timeout=settings.cb_recovery_timeout_seconds,
            half_open_max_calls=settings.cb_half_open_max_calls,
            expected_exceptions=_DEPENDENCY_FAILURES,
        )

    @property
    def enabled(self) -> bool:
        return bool(self._settings.notification_service_url)

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def notify_task_created(self, task: Task) -> bool:
        """True — уведомление доставлено; False — пропущено или деградировали."""
        if not self.enabled:
            return False

        s = self._settings
        try:
            async with deadline_scope(s.notification_budget_seconds):
                await retry_async(
                    lambda: self.breaker.call(lambda: self._send(task)),
                    max_attempts=s.retry_max_attempts,
                    base_delay=s.retry_base_delay_seconds,
                    max_delay=s.retry_max_delay_seconds,
                    retry_on=_DEPENDENCY_FAILURES,
                    sleep=self._sleep,
                )
            return True
        except CircuitBreakerOpenError:
            logger.warning("notification skipped: circuit is open (task %s)", task.id)
        except DeadlineExceededError:
            outer = current_deadline()
            if outer is not None and outer.expired:
                raise  # бюджет самого запроса кончился — это уже 504
            logger.warning("notification budget exhausted (task %s)", task.id)
        except (*_DEPENDENCY_FAILURES, PermanentNotificationError) as exc:
            logger.warning("notification failed (task %s): %r", task.id, exc)
        return False

    async def _send(self, task: Task) -> None:
        per_attempt = self._settings.notification_timeout_seconds
        budget = remaining_time()
        if budget is not None:
            per_attempt = min(per_attempt, budget)

        response = await self._http.post(
            self._settings.notification_service_url,
            json={"event": "task.created", "task_id": task.id, "title": task.title},
            # Повтор POST безопасен только при идемпотентности на стороне получателя.
            headers={"Idempotency-Key": f"task-created-{task.id}"},
            timeout=per_attempt,
        )
        if response.status_code >= 500 or response.status_code == 429:
            raise TransientNotificationError(f"status {response.status_code}")
        if response.status_code >= 400:
            raise PermanentNotificationError(f"status {response.status_code}")
