import uuid
from datetime import timedelta

from core.repositories.report_lifecycle import ReportGenerationErrorCategory
from core.services.report_generation_dispatcher import (
    PublishResult,
    ReportGenerationDispatcher,
)

_WORKER_TASK_NAME = "core.tasks.process_report_generation_job"

try:
    from kombu.exceptions import (
        ConnectionError as KombuConnectionError,
        EncodeError,
        OperationalError as KombuOperationalError,
        SerializationError,
    )
except ImportError:
    KombuConnectionError = ()
    EncodeError = ()
    KombuOperationalError = ()
    SerializationError = ()

try:
    from celery.exceptions import NotRegistered
except ImportError:
    NotRegistered = ()

_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    KombuOperationalError,
    TimeoutError,
    ConnectionError,
    OSError,
)

_TERMINAL_EXCEPTIONS: tuple[type[BaseException], ...] = tuple(
    filter(
        bool,
        (EncodeError, SerializationError, TypeError),
    )
)


class CeleryReportGenerationPublisher:
    """Production adapter — calls Celery .send_task, no DB access.

    Safe classification:
      - Retryable: broker/transport/timeout/unknown errors.
      - Terminal: proven serialization/configuration errors only.
    """

    async def publish(
        self, *, job_id: uuid.UUID, report_id: uuid.UUID, task_id: str
    ) -> PublishResult:
        from core.tasks import celery_app

        if _WORKER_TASK_NAME not in celery_app.tasks:
            return PublishResult.terminal(
                ReportGenerationErrorCategory.DISPATCH_FAILED
            )

        try:
            celery_app.send_task(
                _WORKER_TASK_NAME,
                kwargs={
                    "job_id": str(job_id),
                    "report_id": str(report_id),
                },
                task_id=task_id,
            )
        except _TERMINAL_EXCEPTIONS:
            return PublishResult.terminal(
                ReportGenerationErrorCategory.UNKNOWN_INTERNAL
            )
        except _RETRYABLE_EXCEPTIONS:
            return PublishResult.retryable(
                ReportGenerationErrorCategory.DISPATCH_FAILED
            )
        except Exception:
            return PublishResult.retryable(
                ReportGenerationErrorCategory.DISPATCH_FAILED
            )
        return PublishResult.accepted()


def build_dispatcher(
    *,
    base_retry_delay: timedelta = timedelta(seconds=30),
    max_retry_delay: timedelta = timedelta(minutes=5),
) -> ReportGenerationDispatcher:
    from core.database import get_async_sessionmaker

    session_factory = get_async_sessionmaker()
    publisher = CeleryReportGenerationPublisher()
    return ReportGenerationDispatcher(
        session_factory,
        publisher,
        base_retry_delay=base_retry_delay,
        max_retry_delay=max_retry_delay,
    )
