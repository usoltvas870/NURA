---
name: celery
description: Celery task patterns for async Python — task definition, chaining, error handling, rate limiting, monitoring, and integration with FastAPI + Redis. Use when working with core/tasks/.
---

# Celery Task Patterns (NURA)

## NURA Setup
```python
# core/tasks/__init__.py
from celery import Celery
from core.config import settings

celery_app = Celery(
    "nura",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
```

## Defining Tasks
```python
from core.tasks import celery_app
from celery import shared_task

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_report(self, user_id: int, report_type: str) -> dict:
    try:
        result = do_work(user_id, report_type)
        return {"status": "completed", "result": result}
    except TemporaryError as exc:
        raise self.retry(exc=exc)
    except PermanentError:
        return {"status": "failed", "error": str(exc)}

# Periodic task with rate limit
@shared_task(rate_limit="10/m")
def send_daily_digest():
    users = get_active_users()
    for user in users:
        generate_report.delay(user.id, "daily")
```

## Calling Tasks
```python
# Async
task = generate_report.delay(user_id=42, report_type="weekly")
task_id = task.id

# Wait for result (in sync context)
result = generate_report.apply_async(args=[42, "weekly"]).get(timeout=30)

# Check status
from celery.result import AsyncResult
task = AsyncResult(task_id)
task.status       # PENDING/STARTED/SUCCESS/FAILURE/RETRY
task.result       # Return value or exception
task.traceback    # If failed
```

## Task Chaining
```python
from celery import chain, group, chord

# Sequential
chain(
    fetch_data.s(url="https://api.example.com"),
    process_data.s(),
    save_results.s(),
).delay()

# Parallel
group(
    scrape_source.s("source_a"),
    scrape_source.s("source_b"),
    scrape_source.s("source_c"),
).delay()

# Parallel + aggregate (chord)
chord(
    [
        analyze_trend.s("trend_1"),
        analyze_trend.s("trend_2"),
    ],
    generate_final_report.s(),
).delay()
```

## Error Handling & Retries
```python
@shared_task(bind=True, max_retries=5, default_retry_delay=30)
def process_payment(self, user_id: int, amount: int) -> dict:
    try:
        return charge_user(user_id, amount)
    except NetworkError as exc:
        countdown = 2 ** self.request.retries * 60  # exponential backoff
        raise self.retry(exc=exc, countdown=countdown)
    except PaymentError as exc:
        # Don't retry — permanent failure
        notify_admin.delay(user_id, str(exc))
        return {"status": "failed", "error": str(exc)}
```

## Task Signals (monitoring)
```python
from celery.signals import task_failure, task_success, task_retry

@task_failure.connect
def handle_task_failure(sender=None, task_id=None, exception=None, **kwargs):
    logger.error(f"Task {task_id} failed: {exception}")

@task_success.connect
def handle_task_success(sender=None, task_id=None, **kwargs):
    logger.info(f"Task {task_id} completed")
```

## Celery Beat (periodic tasks)
```python
# Schedule in config
celery_app.conf.beat_schedule = {
    "clean-expired-sessions": {
        "task": "core.tasks.cleanup.clean_expired_sessions",
        "schedule": crontab(hour=3, minute=0),  # Daily at 3 AM
    },
    "send-daily-digest": {
        "task": "core.tasks.digest.send_daily_digest",
        "schedule": crontab(hour=9, minute=0),  # Daily at 9 AM
    },
}
```

## Integration with FastAPI
```python
from core.tasks.report import generate_report

@router.post("/reports/generate")
async def request_report(user_id: int):
    task = generate_report.delay(user_id=user_id, report_type="full")
    return {"task_id": task.id, "status": "queued"}

@router.get("/reports/status/{task_id}")
async def check_report(task_id: str):
    task = AsyncResult(task_id)
    return {
        "task_id": task_id,
        "status": task.status,
        "result": task.result if task.ready() else None,
    }
```

## Running Workers
```bash
# Basic
celery -A core.tasks worker --loglevel=info

# With concurrency
celery -A core.tasks worker --concurrency=4 -Q default,reports

# Celery beat
celery -A core.tasks beat --loglevel=info

# Flower monitoring
celery -A core.tasks flower --port=5555
```

## Anti-patterns
- ❌ Долгие задачи без retry → всегда указывай max_retries
- ❌ get(timeout) в async контексте → блокирует event loop
- ❌ Тяжёлые import в задачах → lazy import внутри функции
- ❌ Нет мониторинга → используй Flower или Sentry
- ❌ Одна очередь для всего → разделяй на default, reports, payments
