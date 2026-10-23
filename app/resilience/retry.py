import asyncio
import logging
import random
from typing import Awaitable, Callable, TypeVar

from app.resilience.deadline import DeadlineExceededError, remaining_time

logger = logging.getLogger(__name__)

T = TypeVar("T")


def backoff_delay(attempt: int, base: float, cap: float) -> float:
    return random.uniform(0.0, min(cap, base * (2**attempt)))


async def retry_async(
    func: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay: float = 0.1,
    max_delay: float = 2.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    is_retryable: Callable[[BaseException], bool] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return await func()
        except DeadlineExceededError:
            raise
        except retry_on as exc:
            if is_retryable is not None and not is_retryable(exc):
                raise
            last_exc = exc
            if attempt == max_attempts - 1:
                break

            delay = backoff_delay(attempt, base_delay, max_delay)
            budget = remaining_time()
            if budget is not None and budget <= delay:
                logger.warning("retry: not enough deadline budget left, giving up")
                break

            logger.warning(
                "retry: attempt %d/%d failed (%r), sleeping %.3fs",
                attempt + 1,
                max_attempts,
                exc,
                delay,
            )
            await sleep(delay)

    assert last_exc is not None
    raise last_exc
