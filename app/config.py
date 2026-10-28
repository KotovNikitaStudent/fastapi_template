from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    request_deadline_seconds: float = 5.0
    request_deadline_max_seconds: float = 30.0
    deadline_header: str = "X-Request-Timeout"

    notification_service_url: str | None = None
    notification_timeout_seconds: float = 1.0
    notification_budget_seconds: float = 2.0

    retry_max_attempts: int = 3
    retry_base_delay_seconds: float = 0.1
    retry_max_delay_seconds: float = 2.0

    cb_failure_threshold: int = 5
    cb_recovery_timeout_seconds: float = 30.0
    cb_half_open_max_calls: int = 1

    rate_limit_enabled: bool = True
    redis_url: str = "redis://localhost:6379/0"
    rate_limit_algorithm: Literal["token_bucket", "fixed_window"] = "token_bucket"
    rate_limit_bucket_capacity: int = 10
    rate_limit_refill_per_second: float = 5.0
    rate_limit_window_limit: int = 100
    rate_limit_window_seconds: int = 60
    rate_limit_fail_open: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
