import asyncio
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import AsyncIterator


class DeadlineExceededError(Exception):
    pass


@dataclass(frozen=True)
class Deadline:
    expires_at: float

    @classmethod
    def after(cls, seconds: float) -> "Deadline":
        return cls(expires_at=time.monotonic() + seconds)

    def remaining(self) -> float:
        return max(0.0, self.expires_at - time.monotonic())

    @property
    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def narrow(self, seconds: float) -> "Deadline":
        return Deadline(min(self.expires_at, time.monotonic() + seconds))


_current: ContextVar[Deadline | None] = ContextVar("request_deadline", default=None)


def current_deadline() -> Deadline | None:
    return _current.get()


def remaining_time(default: float | None = None) -> float | None:
    deadline = _current.get()
    return deadline.remaining() if deadline is not None else default


@asynccontextmanager
async def deadline_scope(seconds: float) -> AsyncIterator[Deadline]:
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
