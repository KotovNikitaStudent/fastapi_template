# FastAPI Template project

This is a template project for a FastAPI application with four resilience
patterns around the task service: **deadline, retry, circuit breaker, rate limiter**.

## Where things live

| Pattern         | Code                                  | Applied in                                               |
|-----------------|---------------------------------------|----------------------------------------------------------|
| Deadline        | `app/resilience/deadline.py`          | `DeadlineMiddleware` (every request), notification call  |
| Retry           | `app/resilience/retry.py`             | `app/adapters/notifier.py`                               |
| Circuit breaker | `app/resilience/circuit_breaker.py`   | `app/adapters/notifier.py`                               |
| Rate limiter    | `app/resilience/rate_limiter.py`      | `rate_limit` dependency on the whole API router (Redis)  |

`POST /tasks` creates the task and then notifies an external service
(`NOTIFICATION_SERVICE_URL`). A failing notification never fails the request.
`GET /resilience/status` shows the circuit state.

## Configuration (env vars / `.env`)

See `app/config.py`. Main knobs:

- `REQUEST_DEADLINE_SECONDS` (5), `X-Request-Timeout` header narrows it per request
- `NOTIFICATION_SERVICE_URL` (unset = integration off), `RETRY_MAX_ATTEMPTS`
- `CB_FAILURE_THRESHOLD`, `CB_RECOVERY_TIMEOUT_SECONDS`
- `REDIS_URL`, `RATE_LIMIT_ENABLED`, `RATE_LIMIT_FAIL_OPEN`
- `RATE_LIMIT_ALGORITHM` = `token_bucket` (default) | `fixed_window`
  - token bucket: `RATE_LIMIT_BUCKET_CAPACITY`, `RATE_LIMIT_REFILL_PER_SECOND`
  - fixed window: `RATE_LIMIT_WINDOW_LIMIT`, `RATE_LIMIT_WINDOW_SECONDS`

## Run

```bash
docker run -d -p 6379:6379 redis:7   # needed for the rate limiter
poetry install --with test,code-quality
poetry run python main.py
poetry run pytest                    # tests use fakeredis, no Redis needed
```
