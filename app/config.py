from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения. Переопределяются переменными окружения / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Deadline -----------------------------------------------------------
    # Общий бюджет времени на обработку одного запроса (секунды).
    request_deadline_seconds: float = 5.0
    # Клиент может сузить дедлайн заголовком, но не расширить сверх этого предела.
    request_deadline_max_seconds: float = 30.0
    # Имя заголовка, через который клиент передаёт свой дедлайн (в секундах).
    deadline_header: str = "X-Request-Timeout"

    # --- Внешний сервис уведомлений (зависимость, которую защищаем) ---------
    # Если не задан, интеграция выключена.
    notification_service_url: str | None = None
    # Таймаут одной попытки.
    notification_timeout_seconds: float = 1.0
    # Общий бюджет на уведомление вместе с повторами; не больше дедлайна запроса.
    notification_budget_seconds: float = 2.0

    # --- Retry --------------------------------------------------------------
    retry_max_attempts: int = 3
    retry_base_delay_seconds: float = 0.1
    retry_max_delay_seconds: float = 2.0

    # --- Circuit breaker ----------------------------------------------------
    cb_failure_threshold: int = 5
    cb_recovery_timeout_seconds: float = 30.0
    cb_half_open_max_calls: int = 1

    # --- Rate limiter -------------------------------------------------------
    rate_limit_enabled: bool = True
    redis_url: str = "redis://localhost:6379/0"
    rate_limit_algorithm: Literal["token_bucket", "fixed_window"] = "token_bucket"
    # Для token bucket: ёмкость ведра (burst) и скорость пополнения (токенов/сек).
    rate_limit_bucket_capacity: int = 10
    rate_limit_refill_per_second: float = 5.0
    # Для fixed window: лимит запросов на окно и длина окна в секундах.
    rate_limit_window_limit: int = 100
    rate_limit_window_seconds: int = 60
    # Что делать, если Redis недоступен: пропускать трафик (fail-open) или нет.
    rate_limit_fail_open: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
