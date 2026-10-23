import logging
import math

from fastapi import Depends, HTTPException, Request, Response, status
from redis.exceptions import RedisError

from app.config import Settings, get_settings
from app.dependencies import get_rate_limiter
from app.resilience import RateLimiter

logger = logging.getLogger(__name__)


def client_key(request: Request) -> str:
    # За reverse proxy здесь нужен реальный IP клиента (X-Forwarded-For от
    # доверенного прокси, например через uvicorn --proxy-headers).
    return request.client.host if request.client else "unknown"


async def rate_limit(
    request: Request,
    response: Response,
    limiter: RateLimiter | None = Depends(get_rate_limiter),
    settings: Settings = Depends(get_settings),
) -> None:
    """Dependency: 429 + Retry-After, если клиент превысил лимит."""
    if limiter is None:
        return

    try:
        result = await limiter.check(client_key(request))
    except (RedisError, OSError) as exc:
        if settings.rate_limit_fail_open:
            logger.error("rate limiter unavailable, failing open: %r", exc)
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiter unavailable",
        ) from exc

    headers = {
        "X-RateLimit-Limit": str(result.limit),
        "X-RateLimit-Remaining": str(result.remaining),
    }
    if not result.allowed:
        headers["Retry-After"] = str(max(1, math.ceil(result.retry_after)))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
            headers=headers,
        )
    response.headers.update(headers)
