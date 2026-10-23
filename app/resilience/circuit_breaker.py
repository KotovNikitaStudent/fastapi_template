import asyncio
import enum
import logging
import time
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(str, enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpenError(Exception):
    pass


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
        expected_exceptions: tuple[type[BaseException], ...] = (Exception,),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.expected_exceptions = expected_exceptions
        self._clock = clock

        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._half_open_in_flight = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        if (
            self._state is CircuitState.OPEN
            and self._clock() - self._opened_at >= self.recovery_timeout
        ):
            return CircuitState.HALF_OPEN
        return self._state

    async def _before_call(self) -> bool:
        async with self._lock:
            state = self.state
            if state is CircuitState.OPEN:
                raise CircuitBreakerOpenError(f"circuit '{self.name}' is open")
            if state is CircuitState.HALF_OPEN:
                if self._state is CircuitState.OPEN:
                    self._transition(CircuitState.HALF_OPEN)
                if self._half_open_in_flight >= self.half_open_max_calls:
                    raise CircuitBreakerOpenError(
                        f"circuit '{self.name}' is half-open, probe limit reached"
                    )
                self._half_open_in_flight += 1
                return True
            return False

    async def _on_success(self, probe: bool) -> None:
        async with self._lock:
            if probe:
                self._half_open_in_flight -= 1
                if self._state is CircuitState.HALF_OPEN:
                    self._transition(CircuitState.CLOSED)
            self._failures = 0

    async def _on_failure(self, probe: bool) -> None:
        async with self._lock:
            if probe:
                self._half_open_in_flight -= 1
                if self._state is CircuitState.HALF_OPEN:
                    self._transition(CircuitState.OPEN)
                return
            self._failures += 1
            if (
                self._state is CircuitState.CLOSED
                and self._failures >= self.failure_threshold
            ):
                self._transition(CircuitState.OPEN)

    async def _on_cancel(self, probe: bool) -> None:
        if probe:
            async with self._lock:
                self._half_open_in_flight -= 1

    def _transition(self, new_state: CircuitState) -> None:
        logger.warning(
            "circuit '%s': %s -> %s", self.name, self._state.value, new_state.value
        )
        self._state = new_state
        if new_state is CircuitState.OPEN:
            self._opened_at = self._clock()
        elif new_state is CircuitState.CLOSED:
            self._failures = 0
        elif new_state is CircuitState.HALF_OPEN:
            self._half_open_in_flight = 0

    async def call(self, func: Callable[[], Awaitable[T]]) -> T:
        probe = await self._before_call()
        try:
            result = await func()
        except self.expected_exceptions:
            await self._on_failure(probe)
            raise
        except BaseException:
            await self._on_cancel(probe)
            raise
        await self._on_success(probe)
        return result
