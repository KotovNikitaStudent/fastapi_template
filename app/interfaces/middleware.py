import json
import logging

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_settings
from app.resilience import DeadlineExceededError, deadline_scope

logger = logging.getLogger(__name__)


class DeadlineMiddleware:
    """Задаёт дедлайн каждому HTTP-запросу и отвечает 504 при его исчерпании.

    Клиент может передать свой бюджет заголовком (по умолчанию X-Request-Timeout,
    секунды): он применяется, если не больше request_deadline_max_seconds.
    Дедлайн лежит в ContextVar, поэтому его видят retry и клиенты зависимостей.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        seconds = self._budget(scope, settings)

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            async with deadline_scope(seconds):
                await self.app(scope, receive, tracking_send)
        except DeadlineExceededError:
            logger.warning("deadline of %.3fs exceeded: %s", seconds, scope["path"])
            if response_started:
                return  # заголовки уже ушли клиенту, статус изменить нельзя
            body = json.dumps({"detail": "Request deadline exceeded"}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 504,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})

    @staticmethod
    def _budget(scope: Scope, settings) -> float:
        default = settings.request_deadline_seconds
        header = settings.deadline_header.lower().encode()
        for name, value in scope["headers"]:
            if name == header:
                try:
                    requested = float(value)
                except ValueError:
                    return default
                if 0 < requested <= settings.request_deadline_max_seconds:
                    return requested
                return default
        return default
