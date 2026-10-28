from redis.asyncio import Redis

from app.adapters.notifier import NotificationClient
from app.config import get_settings
from app.resilience import RateLimiter, build_rate_limiter

_notifier: NotificationClient | None = None
_redis: Redis | None = None
_rate_limiter: RateLimiter | None = None


def get_notifier() -> NotificationClient:
    global _notifier
    if _notifier is None:
        _notifier = NotificationClient(get_settings())
    return _notifier


def get_rate_limiter() -> RateLimiter | None:
    global _redis, _rate_limiter
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return None
    if _rate_limiter is None:
        _redis = Redis.from_url(
            settings.redis_url, socket_timeout=0.25, socket_connect_timeout=0.25
        )
        _rate_limiter = build_rate_limiter(settings, _redis)
    return _rate_limiter


async def close_resources() -> None:
    global _notifier, _redis, _rate_limiter
    if _notifier is not None:
        await _notifier.aclose()
    if _redis is not None:
        await _redis.aclose()
    _notifier = _redis = _rate_limiter = None
