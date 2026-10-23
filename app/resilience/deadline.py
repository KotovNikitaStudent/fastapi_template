"""Deadline: абсолютный срок, к которому запрос обязан завершиться.

В отличие от «таймаута на вызов», дедлайн один на весь запрос: каждый
следующий шаг (повторные попытки, походы в зависимости) получает только
остаток бюджета. Дедлайн хранится в ContextVar, поэтому доступен в любом месте
цепочки вызовов без явной передачи параметров (deadline propagation).
"""

import asyncio
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import AsyncIterator


class DeadlineExceededError(Exception):
    """Бюджет времени на запрос исчерпан."""


@dataclass(frozen=True)
class Deadline:
    expires_at: float  # значение time.monotonic()

    @classmethod
    def after(cls, seconds: float) -> "Deadline":
        return cls(expires_at=time.monotonic() + seconds)

    def remaining(self) -> float:
        return max(0.0, self.expires_at - time.monotonic())

    @property
    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def narrow(self, seconds: float) -> "Deadline":
        """Новый дедлайн не позже текущего: можно сузить, нельзя расширить."""
        return Deadline(min(self.expires_at, time.monotonic() + seconds))


_current: ContextVar[Deadline | None] = ContextVar("request_deadline", default=None)


def current_deadline() -> Deadline | None:
    return _current.get()


def remaining_time(default: float | None = None) -> float | None:
    """Остаток бюджета в секундах или default, если дедлайн не установлен."""
    deadline = _current.get()
    return deadline.remaining() if deadline is not None else default


@asynccontextmanager
async def deadline_scope(seconds: float) -> AsyncIterator[Deadline]:
    """Устанавливает дедлайн и отменяет работу внутри блока по его истечении.

    Вложенный scope может только ужесточить внешний дедлайн.
    Наружу выбрасывается DeadlineExceededError.
    """
    parent = _current.get()
    deadline = parent.narrow(seconds) if parent else Deadline.after(seconds)
    token = _current.set(deadline)
    try:
        if deadline.expired:
            raise DeadlineExceededError("deadline already exceeded")
        timeout_cm = asyncio.timeout_at(
            asyncio.get_running_loop().time() + deadline.remaining()
        )
        try:
            async with timeout_cm:
                yield deadline
        except TimeoutError as exc:
            # Чужой TimeoutError (например, сокета) не маскируем под дедлайн.
            if not timeout_cm.expired():
                raise
            raise DeadlineExceededError("deadline exceeded") from exc
    finally:
        _current.reset(token)
