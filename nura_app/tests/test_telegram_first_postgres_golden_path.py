"""Handler-level PostgreSQL golden path for Telegram start and onboarding."""

from __future__ import annotations

import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import partial
import logging
import os
import secrets
import shutil
import subprocess
import sys
import time
from typing import Any
import uuid
from pathlib import Path

# The documented standalone command must not import an ambient production .env
# before its fixture creates the disposable PostgreSQL and Redis sandbox.
if not os.environ.get("NURA_GOLDEN_PATH_DATABASE_URL"):
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("NURA_DISABLE_DOTENV", "1")

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, Message, Update, User as TelegramUser
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.routes import payment as payment_route
from bot.handlers import chat, onboarding, payment as bot_payment, profile, start, tarot
from bot.states.chat_state import ChatStates
from bot.texts.chat import paywall_text
from bot.states.onboarding_state import OnboardingStates
from core import tasks
from core.celery_async import _reset_runtime_for_tests
from core.config import settings
import core.database as database_module
from core.fallbacks import FALLBACK_FULL, FALLBACK_KITCHEN
from core.models import (
    AttributionLink,
    AttributionTouch,
    ChatMessageUsage,
    DailyTarotDraw,
    DailyTarotDrawState,
    FullReportTelegramDelivery,
    MiniReportGeneration,
    Order,
    OrderStatus,
    PaymentAttempt,
    PaymentEvent,
    Report,
    ReportGenerationJob,
    ReportGenerationJobState,
    ReportGenerationState,
    ReportType,
    TelegramReportDelivery,
    User,
)
from core.repositories.daily_tarot_draw import DailyTarotDrawRepository
from core.repositories.user import UserRepository
from core.services.ai import AIService
from core.services.account_deletion import AccountDeletionService
from core.services.chat_quota import ChatChannel, ChatQuotaService, ChatUsageStatus
from core.services.chat_history import chat_history_key, chat_history_marker_key
from core.services.daily_tarot_application import (
    DailyTarotApplicationService,
    DailyTarotRequest,
)
from core.services.daily_tarot_timezone import local_date_for_timezone
from core.services.matrix import MatrixService
from core.services.report_generation_dispatcher import (
    PublishResult,
    ReportGenerationDispatcher,
)
from core.services.my_reports import MyReportsService
from core.services.report import ReportService
from core.services.full_matrix_checkout import FullMatrixCheckoutService
from core.services.telegram_report_delivery import TelegramDocument
import core.services.telegram_report_delivery as telegram_delivery_module
import core.services.full_report_telegram_delivery as full_delivery_module
import core.loop_specs.report_loop as report_loop


TELEGRAM_ID = 7_777_001
ATTRIBUTION_CODE = "nura_start_01"
BIRTH_DATE = "02.01.2000"
INVALID_BIRTH_DATE = "31.02.2000"
BOT_TOKEN = "42:TEST_ONLY_TOKEN"
DAILY_TAROT_NOW = datetime(2026, 7, 26, 21, 30, tzinfo=timezone.utc)
ZERO_SIDE_EFFECT_MODELS = (
    ChatMessageUsage,
    DailyTarotDraw,
    FullReportTelegramDelivery,
    MiniReportGeneration,
    Order,
    PaymentAttempt,
    PaymentEvent,
    Report,
    ReportGenerationJob,
    TelegramReportDelivery,
)
_STANDALONE_LABEL = "nura.test=telegram-first-standalone"
_sandbox_redis: Redis | None = None
MINI_ANALYSIS = {
    "main_archetype": "Sandbox: спокойная внутренняя сила",
    "core_strength": "Опора <script>не исполняется</script>",
    "emotional_conflict": "Баланс между действием и паузой",
    "relationship_pattern": "Честный диалог и ясные границы",
    "financial_block": "Проверять решения без спешки",
}
FULL_AI_ANALYSIS = {
    key: "Sandbox insight evidence supports thoughtful practical choices today. " * 8
    for key in FALLBACK_FULL
}
FULL_AI_JSON = json.dumps(FULL_AI_ANALYSIS)


class RecordingBotSession(BaseSession):
    """In-memory Telegram transport; no method reaches the network."""

    def __init__(self) -> None:
        super().__init__()
        self.methods: list[TelegramMethod[Any]] = []
        self._message_id = 10_000

    async def close(self) -> None:
        return None

    async def make_request(
        self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None
    ) -> Any:
        self.methods.append(method)
        api_method = method.__api_method__
        if api_method == "getMe":
            return TelegramUser(id=42, is_bot=True, first_name="NURA", username="NuraBot")
        if api_method in {"sendMessage", "editMessageText"}:
            self._message_id += 1
            return Message(
                message_id=self._message_id,
                date=datetime.now(timezone.utc),
                chat=Chat(id=TELEGRAM_ID, type="private"),
                from_user=TelegramUser(id=42, is_bot=True, first_name="NURA"),
                text=method.text,
            ).as_(bot)
        if api_method == "answerCallbackQuery":
            return True
        raise AssertionError(f"unexpected Telegram API method: {api_method}")

    async def stream_content(self, *args: Any, **kwargs: Any):
        yield b""


class RecordingMiniDeliveryAdapter:
    """Fake transport for the production mini-report delivery service."""

    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.documents: list[tuple[int, bytes, str, str]] = []

    async def send_message(self, chat_id: int, text_value: str) -> int:
        self.messages.append((chat_id, text_value))
        return 20_000 + len(self.messages)

    async def send_document(
        self, chat_id: int, content: bytes, filename: str, caption: str
    ) -> TelegramDocument:
        self.documents.append((chat_id, content, filename, caption))
        return TelegramDocument(message_id=30_000 + len(self.documents))


class RecordingFullDeliveryAdapter:
    """Fake only the full-report Telegram transport used by the registered task."""

    instances: list["RecordingFullDeliveryAdapter"] = []

    def __init__(self) -> None:
        self.documents: list[tuple[int, bytes, str, str]] = []
        self.file_id_requests: list[tuple[int, str, str]] = []
        type(self).instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.instances = []

    async def send_document_from_artifact(
        self, chat_id: int, content: bytes, filename: str, caption: str
    ) -> TelegramDocument:
        self.documents.append((chat_id, content, filename, caption))
        return TelegramDocument(
            message_id=40_000 + len(self.documents),
            file_id=f"sandbox-full-file-{len(self.documents)}",
        )

    async def send_document_by_file_id(
        self, chat_id: int, file_id: str, caption: str
    ) -> TelegramDocument:
        self.file_id_requests.append((chat_id, file_id, caption))
        return TelegramDocument(
            message_id=41_000 + len(self.file_id_requests), file_id=file_id
        )


class RecordingYooKassa:
    """The checkout acceptance seam; no provider request leaves the sandbox."""

    def __init__(self) -> None:
        self.created: list[tuple[str, dict[str, Any]]] = []
        self.get_calls = 0

    async def create_payment(
        self, *, idempotency_key: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.created.append((idempotency_key, payload))
        number = len(self.created)
        return {
            "id": f"sandbox-yookassa-{number}",
            "status": "pending",
            "paid": False,
            "amount": {"value": "890.00", "currency": "RUB"},
            "metadata": payload["metadata"],
            "confirmation": {
                "confirmation_url": f"https://yookassa.sandbox/pay/{number}"
            },
        }

    async def get_payment(self, provider_payment_id: str) -> dict[str, Any]:
        self.get_calls += 1
        pytest.fail(f"return URL must not look up provider payment {provider_payment_id}")


class VerifiedWebhookYooKassa:
    """Provider lookup seam for the post-checkout verified webhook segment."""

    def __init__(self, factory: async_sessionmaker[AsyncSession], *, fail_on_lookup: bool = False) -> None:
        self.factory = factory
        self.fail_on_lookup = fail_on_lookup
        self.get_calls = 0
        self.claim_observed_before_lookup = False

    async def create_payment(self, *, idempotency_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        pytest.fail("verified webhook must not create another provider payment")

    async def get_payment(self, provider_payment_id: str) -> dict[str, Any]:
        self.get_calls += 1
        if self.fail_on_lookup:
            pytest.fail("duplicate webhook must not perform another provider lookup")
        async with self.factory() as session:
            event = (await session.execute(select(PaymentEvent))).scalar_one()
            attempt = (await session.execute(select(PaymentAttempt))).scalar_one()
            order = (await session.execute(select(Order))).scalar_one()
            assert event.processing_status == "processing"
            assert event.provider_payment_id == provider_payment_id
            assert attempt.provider_payment_id == provider_payment_id
            self.claim_observed_before_lookup = True
            return {
                "id": provider_payment_id,
                "status": "succeeded",
                "paid": True,
                "amount": {"value": "890.00", "currency": "RUB"},
                "metadata": {"product_code": "full_matrix", "order_id": order.public_id},
                "test": False,
            }


class RefundWebhookYooKassa:
    """Production-shaped full-refund lookup seam for the destructive replay."""

    def __init__(
        self,
        order_public_id: str,
        provider_payment_id: str,
        test_mode: bool,
        *,
        forbidden: bool = False,
    ) -> None:
        self.order_public_id = order_public_id
        self.provider_payment_id = provider_payment_id
        self.test_mode = test_mode
        self.forbidden = forbidden
        self.get_calls = 0
        self.refund_calls = 0

    async def get_payment(self, provider_payment_id: str) -> dict[str, Any]:
        self.get_calls += 1
        if self.forbidden:
            pytest.fail("processed refund replay must not look up YooKassa")
        return {
            "id": provider_payment_id,
            "status": "succeeded",
            "paid": True,
            "amount": {"value": "890.00", "currency": "RUB"},
            "metadata": {
                "product_code": "full_matrix", "order_id": self.order_public_id
            },
            "test": self.test_mode,
        }

    async def get_refund(self, provider_refund_id: str) -> dict[str, Any]:
        self.refund_calls += 1
        if self.forbidden:
            pytest.fail("processed refund replay must not look up YooKassa")
        return {
            "id": provider_refund_id,
            "payment_id": self.provider_payment_id,
            "status": "succeeded",
            "amount": {"value": "890.00", "currency": "RUB"},
        }


class RecordingGenerationPublisher:
    """Production dispatcher seam that records publication without a broker."""

    def __init__(self) -> None:
        self.calls: list[tuple[uuid.UUID, uuid.UUID, str]] = []

    async def publish(
        self, *, job_id: uuid.UUID, report_id: uuid.UUID, task_id: str
    ) -> PublishResult:
        self.calls.append((job_id, report_id, task_id))
        return PublishResult.accepted()


class RecordingDailyTarotAI:
    """Deterministic AI seam that verifies the card was persisted before AI."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        user_id: Any,
        *,
        forbidden: bool = False,
    ) -> None:
        self.factory = factory
        self.user_id = user_id
        self.forbidden = forbidden
        self.calls: list[dict[str, Any]] = []

    async def generate_tarot_daily_card(self, **kwargs: Any) -> str:
        if self.forbidden:
            pytest.fail("restart replay must not call Daily Tarot AI")
        async with self.factory() as session:
            draw = (
                await session.execute(
                    select(DailyTarotDraw).where(
                        DailyTarotDraw.user_id == self.user_id
                    )
                )
            ).scalar_one()
            assert draw.status == DailyTarotDrawState.GENERATING
            assert draw.arcana_number == kwargs["arcana_number"]
            assert draw.interpretation is None
        self.calls.append(kwargs)
        return (
            f"Sandbox card {kwargs['arcana_number']}: спокойный фокус "
            "<script>не исполняется</script>"
        )


class RecordingChatAI:
    """Fake only the external chat AI boundary and retain every production call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def chat_response(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return f"Sandbox chat answer {len(self.calls)}"


def _docker(*args: str) -> str:
    completed = subprocess.run(
        ("docker", *args), text=True, capture_output=True, check=False
    )
    if completed.returncode:
        raise RuntimeError(f"docker_failed:{args[0]}")
    return completed.stdout.strip()


def _wait_for_container(container: str, command: tuple[str, ...], port: str) -> int:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        completed = subprocess.run(
            ("docker", "exec", container, *command), capture_output=True, check=False
        )
        if completed.returncode == 0:
            return int(_docker("port", container, port).rsplit(":", 1)[1])
        time.sleep(0.25)
    raise RuntimeError(f"container_not_ready:{container}")


def _confirmed_absent(
    completed: subprocess.CompletedProcess[str], kind: str
) -> bool:
    if completed.returncode == 0:
        return False
    detail = f"{completed.stdout}\n{completed.stderr}".casefold()
    markers = {
        "container": ("no such object", "no such container"),
        "volume": ("no such volume",),
    }
    return any(marker in detail for marker in markers[kind])


def _owned_volume_names(container: str) -> tuple[str, ...]:
    inspected = subprocess.run(
        (
            "docker",
            "inspect",
            "--format",
            '{{range .Mounts}}{{if eq .Type "volume"}}{{println .Name}}{{end}}{{end}}',
            container,
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    if inspected.returncode:
        return ()
    return tuple(line.strip() for line in inspected.stdout.splitlines() if line.strip())


def _remove_owned_container(container: str) -> bool:
    for _attempt in range(3):
        subprocess.run(
            ("docker", "rm", "--force", "--volumes", container),
            text=True,
            capture_output=True,
            check=False,
        )
        inspected = subprocess.run(
            ("docker", "inspect", container),
            text=True,
            capture_output=True,
            check=False,
        )
        if _confirmed_absent(inspected, "container"):
            return True
        time.sleep(0.25)
    return False


@pytest.fixture(scope="session", autouse=True)
def standalone_golden_path_sandbox() -> Any:
    """Make the documented direct pytest command self-contained when runner env is absent."""
    if os.environ.get("NURA_GOLDEN_PATH_DATABASE_URL"):
        yield
        return
    if shutil.which("docker") is None:
        pytest.fail("golden_path_standalone_requires_docker")

    suffix = uuid.uuid4().hex[:12]
    postgres_name = f"nura-telegram-standalone-pg-{suffix}"
    redis_name = f"nura-telegram-standalone-redis-{suffix}"
    created_containers: list[str] = []
    database = f"nura_{suffix}"
    user = f"nura_{suffix}"
    password = secrets.token_urlsafe(24)
    previous_environment = {
        key: os.environ.get(key)
        for key in (
            "APP_ENV", "NURA_DISABLE_DOTENV", "DATABASE_URL", "NURA_GOLDEN_PATH_DATABASE_URL", "REDIS_URL",
            "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_HOST", "POSTGRES_PORT",
            "NURA_CELERY_BROKER_URL", "NURA_CELERY_RESULT_BACKEND",
        )
    }
    try:
        _docker(
            "run", "--detach", "--name", postgres_name, "--label", _STANDALONE_LABEL,
            "--env", f"POSTGRES_USER={user}", "--env", f"POSTGRES_PASSWORD={password}",
            "--env", f"POSTGRES_DB={database}", "--publish", "127.0.0.1::5432", "postgres:16-alpine",
        )
        created_containers.append(postgres_name)
        postgres_port = _wait_for_container(
            postgres_name, ("pg_isready", "--username", user, "--dbname", database), "5432/tcp"
        )
        _docker(
            "run", "--detach", "--name", redis_name, "--label", _STANDALONE_LABEL,
            "--publish", "127.0.0.1::6379", "redis:7-alpine",
        )
        created_containers.append(redis_name)
        redis_port = _wait_for_container(redis_name, ("redis-cli", "ping"), "6379/tcp")
        database_url = f"postgresql+asyncpg://{user}:{password}@127.0.0.1:{postgres_port}/{database}"
        os.environ.update({
            "APP_ENV": "test",
            "NURA_DISABLE_DOTENV": "1",
            "DATABASE_URL": database_url,
            "NURA_GOLDEN_PATH_DATABASE_URL": database_url,
            "REDIS_URL": f"redis://127.0.0.1:{redis_port}/0",
            "POSTGRES_USER": user,
            "POSTGRES_PASSWORD": password,
            "POSTGRES_DB": database,
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": str(postgres_port),
            "NURA_CELERY_BROKER_URL": f"redis://127.0.0.1:{redis_port}/1",
            "NURA_CELERY_RESULT_BACKEND": f"redis://127.0.0.1:{redis_port}/2",
        })
        migrated = subprocess.run(
            (sys.executable, "-m", "alembic", "upgrade", "head"),
            cwd=Path(__file__).resolve().parents[1], env=os.environ.copy(), check=False,
        )
        if migrated.returncode:
            pytest.fail("golden_path_standalone_migration_failed")
        attribution = subprocess.run(
            (
                sys.executable, "-m", "scripts.attribution_links", "create",
                "--platform", "telegram", "--source", "sandbox", "--campaign", "golden_path",
                "--content-id", "handler_segment", "--topic", "acceptance", "--code", ATTRIBUTION_CODE,
            ),
            cwd=Path(__file__).resolve().parents[1], env=os.environ.copy(), check=False,
        )
        if attribution.returncode:
            pytest.fail("golden_path_standalone_attribution_setup_failed")
        yield
    finally:
        global _sandbox_redis
        _sandbox_redis = None
        cleanup_errors: list[str] = []
        volumes = {
            volume
            for container in created_containers
            for volume in _owned_volume_names(container)
        }
        for container in reversed(created_containers):
            if not _remove_owned_container(container):
                cleanup_errors.append(
                    f"standalone_cleanup_container_unverified:{container}"
                )
        for volume in volumes:
            inspected = subprocess.run(
                ("docker", "volume", "inspect", volume),
                text=True,
                capture_output=True,
                check=False,
            )
            if not _confirmed_absent(inspected, "volume"):
                cleanup_errors.append(
                    f"standalone_cleanup_volume_unverified:{volume}"
                )
        for key, value in previous_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if cleanup_errors:
            pytest.fail(";".join(cleanup_errors))


def _redis_for_sandbox() -> Redis:
    global _sandbox_redis
    if _sandbox_redis is None:
        _sandbox_redis = Redis.from_url(os.environ["REDIS_URL"])
    return _sandbox_redis


async def _durability_snapshot(
    factory: async_sessionmaker[AsyncSession], redis: Redis
) -> dict[str, Any]:
    """Return only durable state: it can be compared across Python processes."""
    async with factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        reports = (await session.execute(select(Report).order_by(Report.report_type))).scalars().all()
        deliveries = (
            await session.execute(
                select(FullReportTelegramDelivery).order_by(
                    FullReportTelegramDelivery.delivery_reason
                )
            )
        ).scalars().all()
        return {
            "counts": {
                model.__name__: await _count(session, model)
                for model in (
                    User, AttributionLink, AttributionTouch, MiniReportGeneration,
                    Report, TelegramReportDelivery, DailyTarotDraw, ChatMessageUsage,
                    Order, PaymentAttempt, PaymentEvent, ReportGenerationJob,
                    FullReportTelegramDelivery,
                )
            },
            "user_id": str(user.id),
            "has_matrix": user.has_matrix,
            "reports": [
                {
                    "id": str(report.id), "type": report.report_type,
                    "state": report.generation_state, "sha256": report.artifact_sha256,
                    "size": report.artifact_size_bytes,
                }
                for report in reports
            ],
            "deliveries": [
                {
                    "id": str(delivery.id), "reason": delivery.delivery_reason,
                    "status": delivery.status,
                    "message_id": delivery.telegram_document_message_id,
                    "file_id": delivery.telegram_file_id,
                }
                for delivery in deliveries
            ],
            "chat_history": (await redis.get(chat_history_key(user.id))).decode(),
        }


@pytest.fixture(autouse=True)
def detach_handler_routers() -> Any:
    """Permit the standalone suite to recreate dispatchers as its process-bound runner does."""
    yield
    global _sandbox_redis
    _sandbox_redis = None
    for router in (
        start.router,
        onboarding.router,
        bot_payment.router,
        profile.router,
        tarot.router,
        chat.router,
    ):
        router._parent_router = None


@pytest_asyncio.fixture
async def postgres_factory() -> async_sessionmaker[AsyncSession]:
    """Use the one PostgreSQL database created and migrated by the acceptance runner."""
    database_url = os.environ.get("NURA_GOLDEN_PATH_DATABASE_URL")
    if not database_url:
        pytest.fail(
            "golden path requires tools/telegram_first_sandbox_acceptance.py "
            "--golden-path-only"
        )
    engine = create_async_engine(database_url, poolclass=NullPool)
    assert engine.dialect.name == "postgresql"
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            assert (await session.execute(text("SELECT current_database()"))).scalar_one()
        yield factory
    finally:
        await engine.dispose()


def _message_update(bot: Bot, text_value: str, update_id: int) -> Update:
    return Update.model_validate(
        {
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "date": 0,
                "chat": {"id": TELEGRAM_ID, "type": "private"},
                "from": {
                    "id": TELEGRAM_ID,
                    "is_bot": False,
                    "first_name": "Sandbox",
                    "username": "nura_sandbox_user",
                },
                "text": text_value,
            },
        },
        context={"bot": bot},
    )


def _callback_update(
    bot: Bot, update_id: int, data: str = "pd_consent_yes"
) -> Update:
    return Update.model_validate(
        {
            "update_id": update_id,
            "callback_query": {
                "id": f"callback-{update_id}",
                "from": {
                    "id": TELEGRAM_ID,
                    "is_bot": False,
                    "first_name": "Sandbox",
                    "username": "nura_sandbox_user",
                },
                "chat_instance": "golden-path",
                "data": data,
                "message": {
                    "message_id": update_id,
                    "date": 0,
                    "chat": {"id": TELEGRAM_ID, "type": "private"},
                    "from": {"id": 42, "is_bot": True, "first_name": "NURA"},
                    "text": "consent",
                },
            },
        },
        context={"bot": bot},
    )


def _dispatcher() -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(start.router)
    dispatcher.include_router(onboarding.router)
    return dispatcher


def _profile_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(profile.router)
    return dispatcher


def _tarot_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(tarot.router)
    return dispatcher


def _chat_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(chat.router)
    return dispatcher


def _payment_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(bot_payment.router)
    return dispatcher


@asynccontextmanager
async def _no_loading(*_args: Any, **_kwargs: Any):
    yield


async def _count(session: AsyncSession, model: type[Any]) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def _assert_zero_side_effect_rows(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        for model in ZERO_SIDE_EFFECT_MODELS:
            assert await _count(session, model) == 0, model.__name__


def _method_count(transport: RecordingBotSession, api_method: str) -> int:
    return sum(method.__api_method__ == api_method for method in transport.methods)


async def _run_registered_task(
    executor: ThreadPoolExecutor, task: Any, *args: str
) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, partial(task.run, *args))


async def _reset_task_runtime(executor: ThreadPoolExecutor) -> None:
    await asyncio.get_running_loop().run_in_executor(
        executor, _reset_runtime_for_tests
    )


@pytest.mark.asyncio
async def test_handler_golden_path_start_consent_and_onboarding(
    postgres_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with postgres_factory() as session:
        assert await _count(session, User) == 0
        assert await _count(session, AttributionLink) == 1
        assert await _count(session, AttributionTouch) == 0
    await _assert_zero_side_effect_rows(postgres_factory)

    monkeypatch.setattr(start, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(onboarding, "get_async_sessionmaker", lambda: postgres_factory)
    matrix_calls: list[str] = []
    real_calculate = MatrixService.calculate

    def calculate_spy(date_value: str):
        matrix_calls.append(date_value)
        return real_calculate(date_value)

    celery_dispatches: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_delay(*args: Any, **kwargs: Any) -> None:
        celery_dispatches.append((args, kwargs))

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(onboarding.MatrixService, "calculate", calculate_spy)
    monkeypatch.setattr(onboarding.generate_mini_report, "delay", fake_delay)
    monkeypatch.setattr(onboarding.asyncio, "sleep", no_sleep)

    transport = RecordingBotSession()
    bot = Bot(token=BOT_TOKEN, session=transport)
    dispatcher = _dispatcher()
    context = dispatcher.fsm.get_context(bot=bot, chat_id=TELEGRAM_ID, user_id=TELEGRAM_ID)
    try:
        with caplog.at_level(logging.INFO):
            await dispatcher.feed_update(
                bot, _message_update(bot, f"/start a_{ATTRIBUTION_CODE}", 1)
            )
            assert await context.get_state() == OnboardingStates.waiting_for_pd_consent.state
            first_answer = next(
                method for method in transport.methods if method.__api_method__ == "sendMessage"
            )
            assert first_answer.reply_markup.inline_keyboard[0][0].callback_data == "pd_consent_yes"
            assert matrix_calls == [] and celery_dispatches == []

            async with postgres_factory() as session:
                user = (await session.execute(select(User))).scalar_one()
                touch = (await session.execute(select(AttributionTouch))).scalar_one()
                link = (await session.execute(select(AttributionLink))).scalar_one()
                assert user.telegram_id == TELEGRAM_ID
                assert user.birth_date is None and user.pd_consent_at is None
                assert touch.user_id == user.id and touch.attribution_link_id == link.id
                assert touch.resolution_status == "resolved" and touch.visit_count == 1
                user_id = user.id
            await _assert_zero_side_effect_rows(postgres_factory)

            await dispatcher.feed_update(bot, _callback_update(bot, 2))
            await dispatcher.feed_update(bot, _callback_update(bot, 3))
            assert await context.get_state() == OnboardingStates.waiting_for_birth_date.state
            assert _method_count(transport, "answerCallbackQuery") == 2
            assert matrix_calls == [] and celery_dispatches == []
            async with postgres_factory() as session:
                user = await session.get(User, user_id)
                assert user is not None and user.pd_consent_at is not None
                assert user.birth_date is None and await _count(session, User) == 1

            await dispatcher.feed_update(bot, _message_update(bot, INVALID_BIRTH_DATE, 4))
            assert await context.get_state() == OnboardingStates.waiting_for_birth_date.state
            assert matrix_calls == [] and celery_dispatches == []
            async with postgres_factory() as session:
                user = await session.get(User, user_id)
                assert user is not None and user.birth_date is None

            await dispatcher.feed_update(bot, _message_update(bot, BIRTH_DATE, 5))
            assert await context.get_state() is None
            assert matrix_calls == [BIRTH_DATE]
            assert celery_dispatches == [
                ((str(user_id), BIRTH_DATE, "nura_sandbox_user"), {})
            ]
            async with postgres_factory() as session:
                user = await session.get(User, user_id)
                assert user is not None and user.birth_date == BIRTH_DATE
                assert user.main_archetype and user.main_archetype_number is not None
                assert await _count(session, User) == 1
                assert await _count(session, AttributionLink) == 1
                assert await _count(session, AttributionTouch) == 1
            await _assert_zero_side_effect_rows(postgres_factory)

            outbound_before_plain_input = len(transport.methods)
            await dispatcher.feed_update(bot, _message_update(bot, BIRTH_DATE, 6))
            assert len(transport.methods) == outbound_before_plain_input
            assert matrix_calls == [BIRTH_DATE] and len(celery_dispatches) == 1

            await dispatcher.feed_update(
                bot, _message_update(bot, f"/start a_{ATTRIBUTION_CODE}", 7)
            )
            assert await context.get_state() is None
            assert matrix_calls == [BIRTH_DATE] and len(celery_dispatches) == 1
            async with postgres_factory() as session:
                assert await _count(session, User) == 1
                touch = (await session.execute(select(AttributionTouch))).scalar_one()
                assert touch.visit_count == 2
            await _assert_zero_side_effect_rows(postgres_factory)
    finally:
        await dispatcher.storage.close()
        await bot.session.close()

    outbound_text = "\n".join(
        str(getattr(method, "text", "")) for method in transport.methods
    )
    assert str(user_id) not in outbound_text
    assert _method_count(transport, "sendDocument") == 0
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert BIRTH_DATE not in log_text
    assert f"/start a_{ATTRIBUTION_CODE}" not in log_text
    assert BOT_TOKEN not in log_text
    assert str(user_id) not in log_text


@pytest.mark.asyncio
async def test_handler_golden_path_survives_fresh_process(
    postgres_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runner executes this test in a second pytest process on the same database."""
    monkeypatch.setattr(start, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(
        onboarding.MatrixService,
        "calculate",
        lambda *_args: pytest.fail("restart /start must not recalculate Matrix"),
    )
    monkeypatch.setattr(
        onboarding.generate_mini_report,
        "delay",
        lambda *_args, **_kwargs: pytest.fail("restart /start must not dispatch a task"),
    )
    transport = RecordingBotSession()
    bot = Bot(token=BOT_TOKEN, session=transport)
    dispatcher = _dispatcher()
    context = dispatcher.fsm.get_context(bot=bot, chat_id=TELEGRAM_ID, user_id=TELEGRAM_ID)
    try:
        await dispatcher.feed_update(
            bot, _message_update(bot, f"/start a_{ATTRIBUTION_CODE}", 101)
        )
        assert await context.get_state() is None
        async with postgres_factory() as session:
            user = (await session.execute(select(User))).scalar_one()
            touch = (await session.execute(select(AttributionTouch))).scalar_one()
            assert user.telegram_id == TELEGRAM_ID
            assert user.birth_date == BIRTH_DATE and user.pd_consent_at is not None
            assert user.main_archetype and user.main_archetype_number is not None
            assert touch.visit_count == 3
            assert await _count(session, User) == 1
            assert await _count(session, AttributionLink) == 1
            assert await _count(session, AttributionTouch) == 1
        await _assert_zero_side_effect_rows(postgres_factory)
        assert _method_count(transport, "sendMessage") == 1
        assert _method_count(transport, "sendDocument") == 0
    finally:
        await dispatcher.storage.close()
        await bot.session.close()


@pytest.mark.asyncio
async def test_mini_report_generation_and_delivery(
    postgres_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Execute registered generation and delivery tasks without a broker."""
    async with postgres_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        assert user.birth_date == BIRTH_DATE and user.pd_consent_at is not None
        assert await _count(session, MiniReportGeneration) == 0
        assert await _count(session, TelegramReportDelivery) == 0
        user_id = user.id
        username = user.username or user.first_name or "user"

    assert tasks.celery_app.tasks["core.tasks.generate_mini_report"].name == (
        tasks.generate_mini_report.name
    )
    assert tasks.celery_app.tasks["core.tasks.deliver_mini_report"].name == (
        tasks.deliver_mini_report.name
    )
    monkeypatch.setattr(tasks, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(database_module, "get_async_sessionmaker", lambda: postgres_factory)

    matrix_calls: list[str] = []
    real_calculate = MatrixService.calculate

    def calculate_spy(date_value: str):
        matrix_calls.append(date_value)
        return real_calculate(date_value)

    ai_calls: list[tuple[str, int]] = []

    async def fake_mini_ai(date_value: str, matrix: Any) -> dict[str, str]:
        ai_calls.append((date_value, matrix.center))
        return dict(MINI_ANALYSIS)

    delivery_dispatches: list[tuple[str, str, str]] = []

    def fake_delivery_delay(user_ref: str, report_ref: str, generation_ref: str) -> None:
        delivery_dispatches.append((user_ref, report_ref, generation_ref))

    pdf_calls: list[int] = []
    real_generate_pdf = ReportService.generate_pdf.__func__

    async def generate_pdf_spy(cls: type[ReportService], html_content: str) -> bytes:
        pdf_calls.append(len(html_content))
        return await real_generate_pdf(cls, html_content)

    adapter = RecordingMiniDeliveryAdapter()
    monkeypatch.setattr(MatrixService, "calculate", calculate_spy)
    monkeypatch.setattr(AIService, "generate_mini_analysis", fake_mini_ai)
    monkeypatch.setattr(tasks.deliver_mini_report, "delay", fake_delivery_delay)
    monkeypatch.setattr(ReportService, "generate_pdf", classmethod(generate_pdf_spy))
    monkeypatch.setattr(
        telegram_delivery_module, "TelegramDocumentAdapter", lambda: adapter
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            with caplog.at_level(logging.INFO):
                first_result = await _run_registered_task(
                    executor,
                    tasks.generate_mini_report,
                    str(user_id),
                    BIRTH_DATE,
                    username,
                )
                assert first_result["kind"] == "completed_new"
                assert len(delivery_dispatches) == 1
                await _run_registered_task(
                    executor, tasks.deliver_mini_report, *delivery_dispatches[0]
                )

                replay_result = await _run_registered_task(
                    executor,
                    tasks.generate_mini_report,
                    str(user_id),
                    BIRTH_DATE,
                    username,
                )
                assert replay_result["kind"] == "completed_reused"
                assert delivery_dispatches == [
                    delivery_dispatches[0],
                    delivery_dispatches[0],
                ]
                await _run_registered_task(
                    executor, tasks.deliver_mini_report, *delivery_dispatches[1]
                )
        finally:
            await _reset_task_runtime(executor)

    assert matrix_calls == [BIRTH_DATE]
    assert ai_calls and len(ai_calls) == 1
    assert len(pdf_calls) == 1
    assert len(adapter.messages) == 1
    assert len(adapter.documents) == 1
    assert "&lt;script&gt;" in adapter.messages[0][1]
    document_chat, document_bytes, filename, _caption = adapter.documents[0]
    assert document_chat == TELEGRAM_ID
    assert document_bytes.startswith(b"%PDF-") and len(document_bytes) > 1024
    assert filename == "NURA-mini-report.pdf"
    assert all(value not in filename for value in (BIRTH_DATE, username, str(user_id)))

    async with postgres_factory() as session:
        generation = (await session.execute(select(MiniReportGeneration))).scalar_one()
        report = (await session.execute(select(Report))).scalar_one()
        delivery = (await session.execute(select(TelegramReportDelivery))).scalar_one()
        assert generation.user_id == user_id
        assert generation.status == "completed" and generation.attempt_count == 1
        assert generation.completed_at is not None and generation.error_code is None
        assert generation.report_id == report.id
        assert report.report_type == ReportType.MINI.value
        assert report.ai_analysis == MINI_ANALYSIS
        assert isinstance(report.matrix_data, dict) and report.matrix_data
        assert report.artifact_bytes == document_bytes
        assert report.artifact_mime_type == "application/pdf"
        assert report.artifact_size_bytes == len(document_bytes)
        assert report.artifact_sha256 and len(report.artifact_sha256) == 64
        assert report.artifact_completed_at is not None
        assert delivery.status == "delivered"
        assert delivery.text_status == "sent"
        assert delivery.document_status == "sent"
        assert delivery.text_message_ids == [20_001]
        assert delivery.document_message_id == 30_001
        assert await _count(session, User) == 1
        assert await _count(session, MiniReportGeneration) == 1
        assert await _count(session, Report) == 1
        assert await _count(session, TelegramReportDelivery) == 1

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert BIRTH_DATE not in log_text
    assert BOT_TOKEN not in log_text
    assert str(user_id) not in log_text
    assert "<script>" not in log_text
    assert all(model not in log_text for model in MINI_ANALYSIS.values())


@pytest.mark.asyncio
async def test_mini_report_restart_and_repeated_access(
    postgres_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use My Reports and manual delivery from a fresh pytest process."""
    async with postgres_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        generation = (await session.execute(select(MiniReportGeneration))).scalar_one()
        report = (await session.execute(select(Report))).scalar_one()
        initial_delivery = (
            await session.execute(select(TelegramReportDelivery))
        ).scalar_one()
        assert generation.status == "completed"
        assert initial_delivery.status == "delivered"
        assert report.artifact_bytes and report.artifact_bytes.startswith(b"%PDF-")
        user_id, report_id = user.id, report.id

    page = await MyReportsService(postgres_factory).list_user_reports(user_id, 0)
    assert page.total == 1 and len(page.items) == 1
    assert page.items[0].report_id == report_id
    assert page.items[0].report_type == ReportType.MINI.value
    assert page.items[0].supports_repeated_delivery is True
    assert str(user_id) not in page.items[0].display_label

    monkeypatch.setattr(profile, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(tasks, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(database_module, "get_async_sessionmaker", lambda: postgres_factory)
    repeated_dispatches: list[tuple[str, str, str, str]] = []

    def fake_repeated_delay(*args: str) -> None:
        repeated_dispatches.append(args)

    monkeypatch.setattr(
        profile.deliver_repeated_mini_report, "delay", fake_repeated_delay
    )
    monkeypatch.setattr(
        AIService,
        "generate_mini_analysis",
        lambda *_args, **_kwargs: pytest.fail("manual resend must not call AI"),
    )
    monkeypatch.setattr(
        MatrixService,
        "calculate",
        lambda *_args, **_kwargs: pytest.fail("manual resend must not call Matrix"),
    )

    adapter = RecordingMiniDeliveryAdapter()
    monkeypatch.setattr(
        telegram_delivery_module, "TelegramDocumentAdapter", lambda: adapter
    )

    async def forbidden_pdf(*_args: Any, **_kwargs: Any) -> bytes:
        pytest.fail("manual resend must reuse the canonical PDF")

    monkeypatch.setattr(ReportService, "generate_pdf", forbidden_pdf)

    transport = RecordingBotSession()
    bot = Bot(token=BOT_TOKEN, session=transport)
    dispatcher = _profile_dispatcher()
    try:
        await dispatcher.feed_update(
            bot, _callback_update(bot, 201, "reports:list:0")
        )
        list_edit = next(
            method
            for method in transport.methods
            if method.__api_method__ == "editMessageText"
        )
        callback_values = [
            button.callback_data
            for row in list_edit.reply_markup.inline_keyboard
            for button in row
            if button.callback_data
        ]
        view_callback = next(
            value for value in callback_values if value.startswith("reports:view:")
        )
        assert len(view_callback.encode("utf-8")) <= 64
        assert str(user_id) not in str(list_edit.text)

        await dispatcher.feed_update(bot, _callback_update(bot, 202, view_callback))
        await dispatcher.feed_update(
            bot, _callback_update(bot, 203, f"reports:send:{report_id.hex}")
        )
    finally:
        await dispatcher.storage.close()
        await bot.session.close()

    assert len(repeated_dispatches) == 1
    assert tasks.celery_app.tasks[
        "core.tasks.deliver_repeated_mini_report"
    ].name == tasks.deliver_repeated_mini_report.name
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            await _run_registered_task(
                executor,
                tasks.deliver_repeated_mini_report,
                *repeated_dispatches[0],
            )
            await _run_registered_task(
                executor,
                tasks.deliver_repeated_mini_report,
                *repeated_dispatches[0],
            )
        finally:
            await _reset_task_runtime(executor)

    assert len(adapter.messages) == 1
    assert len(adapter.documents) == 1
    assert adapter.documents[0][1] == report.artifact_bytes
    assert _method_count(transport, "answerCallbackQuery") == 3

    async with postgres_factory() as session:
        assert await _count(session, User) == 1
        assert await _count(session, MiniReportGeneration) == 1
        assert await _count(session, Report) == 1
        assert await _count(session, TelegramReportDelivery) == 2
        deliveries = (
            await session.execute(select(TelegramReportDelivery))
        ).scalars().all()
        assert all(delivery.status == "delivered" for delivery in deliveries)
        assert await _count(session, DailyTarotDraw) == 0
        assert await _count(session, ChatMessageUsage) == 0
        assert await _count(session, Order) == 0
        assert await _count(session, PaymentAttempt) == 0
        assert await _count(session, PaymentEvent) == 0
        assert await _count(session, ReportGenerationJob) == 0
        assert await _count(session, FullReportTelegramDelivery) == 0
        full_reports = int(
            await session.scalar(
                select(func.count()).select_from(Report).where(
                    Report.report_type == ReportType.FULL.value
                )
            )
            or 0
        )
        assert full_reports == 0


@pytest.mark.asyncio
async def test_daily_tarot_initial_and_same_process_replay(
    postgres_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Create one daily draw through the Telegram handler and replay it."""
    async with postgres_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        assert user.birth_date == BIRTH_DATE and user.pd_consent_at is not None
        assert user.subscription_status != "premium"
        assert user.tarot_subscription is False
        assert await _count(session, MiniReportGeneration) == 1
        assert await _count(session, Report) == 1
        assert await _count(session, TelegramReportDelivery) == 2
        assert await _count(session, DailyTarotDraw) == 0
        assert await _count(session, ChatMessageUsage) == 0
        user_id = user.id

    quota_before = await ChatQuotaService(postgres_factory).state(
        user_id, subscriber=False
    )
    assert settings.chat_free_message_limit == 5
    assert quota_before.messages_left == 5 and quota_before.used == 0

    expected_local_date = local_date_for_timezone(
        DAILY_TAROT_NOW, settings.default_daily_tarot_timezone
    )
    assert expected_local_date.isoformat() == "2026-07-27"
    daily_ai = RecordingDailyTarotAI(postgres_factory, user_id)
    service = DailyTarotApplicationService(
        user_repository=UserRepository(postgres_factory),
        draw_repository=DailyTarotDrawRepository(postgres_factory),
        ai_service=daily_ai,
        now_provider=lambda: DAILY_TAROT_NOW,
    )
    card_selections: list[tuple[Any, Any]] = []
    real_select_card = DailyTarotApplicationService._select_card

    def select_card_spy(selected_user: User, local_date: Any) -> int:
        card_selections.append((selected_user.id, local_date))
        return real_select_card(selected_user, local_date)

    monkeypatch.setattr(tarot, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(tarot, "_daily_tarot_application_service", lambda: service)
    monkeypatch.setattr(tarot, "animated_loading", _no_loading)
    monkeypatch.setattr(
        DailyTarotApplicationService,
        "_select_card",
        staticmethod(select_card_spy),
    )

    transport = RecordingBotSession()
    bot = Bot(token=BOT_TOKEN, session=transport)
    dispatcher = _tarot_dispatcher()
    try:
        with caplog.at_level(logging.INFO):
            await dispatcher.feed_update(
                bot, _callback_update(bot, 301, "tarot_daily_card")
            )
            async with postgres_factory() as session:
                first_draw = (
                    await session.execute(select(DailyTarotDraw))
                ).scalar_one()
                first_snapshot = (
                    first_draw.id,
                    first_draw.arcana_number,
                    first_draw.interpretation,
                    first_draw.timezone_name,
                    first_draw.attempt_count,
                )
            await dispatcher.feed_update(
                bot, _callback_update(bot, 302, "tarot_daily_card")
            )
    finally:
        await dispatcher.storage.close()
        await bot.session.close()

    assert len(daily_ai.calls) == 1
    assert len(card_selections) == 1
    assert card_selections[0] == (user_id, expected_local_date)
    assert _method_count(transport, "answerCallbackQuery") == 2
    edits = [
        method
        for method in transport.methods
        if method.__api_method__ == "editMessageText"
    ]
    assert len(edits) == 2
    assert edits[0].text == edits[1].text
    assert "&lt;script&gt;" in edits[0].text
    assert str(user_id) not in edits[0].text
    callback_data = [
        button.callback_data
        for row in edits[0].reply_markup.inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert callback_data == ["buy_tarot_subscription", "tarot_menu"]

    async with postgres_factory() as session:
        draw = (await session.execute(select(DailyTarotDraw))).scalar_one()
        assert (
            draw.id,
            draw.arcana_number,
            draw.interpretation,
            draw.timezone_name,
            draw.attempt_count,
        ) == first_snapshot
        assert draw.user_id == user_id
        assert draw.local_date == expected_local_date
        assert draw.timezone_name == "Europe/Moscow"
        assert draw.status == DailyTarotDrawState.COMPLETED
        assert draw.completed_at is not None and draw.failed_at is None
        assert draw.error_code is None
        assert await _count(session, DailyTarotDraw) == 1
        assert await _count(session, ChatMessageUsage) == 0
        assert await _count(session, MiniReportGeneration) == 1
        assert await _count(session, Report) == 1
        assert await _count(session, TelegramReportDelivery) == 2

    quota_after = await ChatQuotaService(postgres_factory).state(
        user_id, subscriber=False
    )
    assert quota_after.messages_left == 5 and quota_after.used == 0
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert BIRTH_DATE not in log_text
    assert BOT_TOKEN not in log_text
    assert str(user_id) not in log_text
    assert "<script>" not in log_text


@pytest.mark.asyncio
async def test_daily_tarot_restart_reuses_durable_result(
    postgres_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh process renders the persisted same-day result without AI."""
    async with postgres_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        draw = (await session.execute(select(DailyTarotDraw))).scalar_one()
        assert user.subscription_status != "premium"
        assert user.tarot_subscription is False
        durable_snapshot = (
            draw.id,
            draw.arcana_number,
            draw.interpretation,
            draw.local_date,
            draw.timezone_name,
            draw.attempt_count,
        )
        user_id = user.id

    restart_ai = RecordingDailyTarotAI(
        postgres_factory, user_id, forbidden=True
    )
    restart_service = DailyTarotApplicationService(
        user_repository=UserRepository(postgres_factory),
        draw_repository=DailyTarotDrawRepository(postgres_factory),
        ai_service=restart_ai,
        now_provider=lambda: DAILY_TAROT_NOW,
    )
    monkeypatch.setattr(tarot, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(
        tarot, "_daily_tarot_application_service", lambda: restart_service
    )
    monkeypatch.setattr(tarot, "animated_loading", _no_loading)
    monkeypatch.setattr(
        DailyTarotApplicationService,
        "_select_card",
        staticmethod(lambda *_args: pytest.fail("restart replay must not select a card")),
    )

    transport = RecordingBotSession()
    bot = Bot(token=BOT_TOKEN, session=transport)
    dispatcher = _tarot_dispatcher()
    try:
        await dispatcher.feed_update(
            bot, _callback_update(bot, 401, "tarot_daily_card")
        )
    finally:
        await dispatcher.storage.close()
        await bot.session.close()

    assert restart_ai.calls == []
    assert _method_count(transport, "answerCallbackQuery") == 1
    edits = [
        method
        for method in transport.methods
        if method.__api_method__ == "editMessageText"
    ]
    assert len(edits) == 1
    assert durable_snapshot[2] in edits[0].text.replace("&lt;", "<").replace("&gt;", ">")
    assert str(user_id) not in edits[0].text

    async with postgres_factory() as session:
        draw = (await session.execute(select(DailyTarotDraw))).scalar_one()
        assert (
            draw.id,
            draw.arcana_number,
            draw.interpretation,
            draw.local_date,
            draw.timezone_name,
            draw.attempt_count,
        ) == durable_snapshot
        assert await _count(session, User) == 1
        assert await _count(session, AttributionLink) == 1
        assert await _count(session, AttributionTouch) == 1
        assert await _count(session, MiniReportGeneration) == 1
        assert await _count(session, Report) == 1
        assert await _count(session, TelegramReportDelivery) == 2
        assert await _count(session, DailyTarotDraw) == 1
        assert await _count(session, ChatMessageUsage) == 0
        assert await _count(session, Order) == 0
        assert await _count(session, PaymentAttempt) == 0
        assert await _count(session, PaymentEvent) == 0
        assert await _count(session, ReportGenerationJob) == 0
        assert await _count(session, FullReportTelegramDelivery) == 0
        full_reports = int(
            await session.scalar(
                select(func.count()).select_from(Report).where(
                    Report.report_type == ReportType.FULL.value
                )
            )
            or 0
        )
        assert full_reports == 0

    quota = await ChatQuotaService(postgres_factory).state(
        user_id, subscriber=False
    )
    assert quota.messages_left == 5 and quota.used == 0


@pytest.mark.asyncio
async def test_lifetime_chat_five_telegram_requests_and_replay(
    postgres_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spend the one user's five lifetime messages through the Telegram adapter."""
    async with postgres_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        assert user.subscription_status != "premium"
        assert user.tarot_subscription is False
        assert await _count(session, ChatMessageUsage) == 0
        user_id = user.id

    assert settings.chat_free_message_limit == 5
    assert ChatQuotaService.is_subscriber(
        tarot_subscription=False,
        tarot_subscription_until=None,
        subscription_status="free",
        subscription_until=None,
    ) is False
    quota = await ChatQuotaService(postgres_factory).state(user_id, subscriber=False)
    assert quota.messages_left == 5 and quota.used == 0

    fake_ai = RecordingChatAI()
    monkeypatch.setattr(chat, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(chat, "get_redis", _redis_for_sandbox)
    monkeypatch.setattr(AIService, "chat_response", staticmethod(fake_ai.chat_response))

    transport = RecordingBotSession()
    bot = Bot(token=BOT_TOKEN, session=transport)
    dispatcher = _chat_dispatcher()
    context = dispatcher.fsm.get_context(bot=bot, chat_id=TELEGRAM_ID, user_id=TELEGRAM_ID)
    request_update_ids = (501, 502, 503, 504, 505)
    try:
        await context.set_state(ChatStates.chatting)
        await context.update_data(matrix_data={"source": "mini-report"}, user_name="Sandbox")
        for index, update_id in enumerate(request_update_ids, start=1):
            await dispatcher.feed_update(bot, _message_update(bot, f"chat request {index}", update_id))
            quota = await ChatQuotaService(postgres_factory).state(user_id, subscriber=False)
            assert quota.messages_left == 5 - index and quota.used == index

        await context.set_state(ChatStates.chatting)
        await context.update_data(matrix_data={"source": "mini-report"}, user_name="Sandbox")
        await dispatcher.feed_update(bot, _message_update(bot, "chat request 5", request_update_ids[-1]))
    finally:
        await dispatcher.storage.close()
        await bot.session.close()

    assert len(fake_ai.calls) == 5
    redis = chat.get_redis()
    raw_history = await redis.get(chat_history_key(user_id))
    assert raw_history is not None
    history = json.loads(raw_history)
    assert len(history) == 10
    assert sum(
        item.get("request_key") == chat._telegram_request_key(TELEGRAM_ID, 505)
        for item in history
    ) == 2
    assert await redis.sismember(
        chat_history_marker_key(user_id), chat._telegram_request_key(TELEGRAM_ID, 505)
    ) == 1
    async with postgres_factory() as session:
        usages = (await session.execute(select(ChatMessageUsage))).scalars().all()
        assert len(usages) == 5
        assert {usage.channel for usage in usages} == {"telegram"}
        assert {usage.status for usage in usages} == {ChatUsageStatus.CONSUMED.value}
        assert {usage.request_key for usage in usages} == {
            chat._telegram_request_key(TELEGRAM_ID, update_id)
            for update_id in request_update_ids
        }
        assert all(usage.response_text for usage in usages)
        assert await _count(session, User) == 1
        assert await _count(session, AttributionLink) == 1
        assert await _count(session, AttributionTouch) == 1
        assert await _count(session, MiniReportGeneration) == 1
        assert await _count(session, Report) == 1
        assert await _count(session, TelegramReportDelivery) == 2
        assert await _count(session, DailyTarotDraw) == 1

    quota = await ChatQuotaService(postgres_factory).state(user_id, subscriber=False)
    assert quota.messages_left == 0 and quota.used == 5


@pytest.mark.asyncio
async def test_lifetime_chat_restart_replay_and_sixth_request_are_durable(
    postgres_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh Telegram handler replays durably and blocks the sixth unique request."""
    async with postgres_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        user_id = user.id
        assert await _count(session, ChatMessageUsage) == 5
        assert await _count(session, DailyTarotDraw) == 1
        assert await _count(session, TelegramReportDelivery) == 2

    async def forbidden_chat_ai(**_kwargs: Any) -> str:
        pytest.fail("durable replay and exhausted request must not call chat AI")

    monkeypatch.setattr(chat, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(chat, "get_redis", _redis_for_sandbox)
    monkeypatch.setattr(AIService, "chat_response", staticmethod(forbidden_chat_ai))

    transport = RecordingBotSession()
    bot = Bot(token=BOT_TOKEN, session=transport)
    dispatcher = _chat_dispatcher()
    context = dispatcher.fsm.get_context(bot=bot, chat_id=TELEGRAM_ID, user_id=TELEGRAM_ID)
    try:
        await context.set_state(ChatStates.chatting)
        await context.update_data(matrix_data={"source": "mini-report"}, user_name="Sandbox")
        await dispatcher.feed_update(bot, _message_update(bot, "chat request 5", 505))

        await context.set_state(ChatStates.chatting)
        await context.update_data(matrix_data={"source": "mini-report"}, user_name="Sandbox")
        await dispatcher.feed_update(bot, _message_update(bot, "chat request 6", 506))
        assert await context.get_state() is None
    finally:
        await dispatcher.storage.close()
        await bot.session.close()

    outbound_texts = [
        method.text
        for method in transport.methods
        if method.__api_method__ == "sendMessage"
    ]
    assert any("Sandbox chat answer 5" in text_value for text_value in outbound_texts)
    assert outbound_texts.count(paywall_text()) == 2

    async with postgres_factory() as session:
        usages = (await session.execute(select(ChatMessageUsage))).scalars().all()
        assert len(usages) == 5
        assert {usage.status for usage in usages} == {ChatUsageStatus.CONSUMED.value}
        assert await _count(session, User) == 1
        assert await _count(session, AttributionLink) == 1
        assert await _count(session, AttributionTouch) == 1
        assert await _count(session, MiniReportGeneration) == 1
        assert await _count(session, Report) == 1
        assert await _count(session, TelegramReportDelivery) == 2
        assert await _count(session, DailyTarotDraw) == 1
        assert await _count(session, Order) == 0
        assert await _count(session, PaymentAttempt) == 0
        assert await _count(session, PaymentEvent) == 0
        assert await _count(session, ReportGenerationJob) == 0
        assert await _count(session, FullReportTelegramDelivery) == 0
        full_reports = int(
            await session.scalar(
                select(func.count()).select_from(Report).where(
                    Report.report_type == ReportType.FULL.value
                )
            )
            or 0
        )
        assert full_reports == 0
    quota = await ChatQuotaService(postgres_factory).state(user_id, subscriber=False)
    assert quota.messages_left == 0 and quota.used == 5


@pytest.mark.asyncio
async def test_checkout_get_rejects_unknown_capability(
    postgres_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET checkout is a capability boundary, not merely a length check."""
    app = FastAPI()
    app.state.limiter = payment_route.limiter
    app.include_router(payment_route.router)
    monkeypatch.setattr(
        payment_route, "get_async_sessionmaker", lambda: postgres_factory
    )
    unknown_token = secrets.token_urlsafe(32)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://sandbox.test"
    ) as client:
        response = await client.get(f"/api/v1/payment/full-matrix/checkout/{unknown_token}")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_full_matrix_checkout_is_durable_and_non_activating(
    postgres_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Continue the Telegram-first persona through checkout, but not webhook payment."""
    provider = RecordingYooKassa()
    service = FullMatrixCheckoutService(postgres_factory, provider)
    monkeypatch.setattr(settings, "test_mode", False)
    monkeypatch.setattr(settings, "report_base_url", "https://nura.sandbox")
    monkeypatch.setattr(settings, "yookassa_receipt_enabled", True)
    monkeypatch.setattr(settings, "yookassa_receipt_vat_code", "sandbox_vat")
    monkeypatch.setattr(settings, "yookassa_receipt_payment_mode", "full_prepayment")
    monkeypatch.setattr(settings, "yookassa_receipt_payment_subject", "service")
    monkeypatch.setattr(bot_payment, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(bot_payment, "FullMatrixCheckoutService", lambda _factory: service)
    monkeypatch.setattr(payment_route, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(payment_route, "FullMatrixCheckoutService", lambda _factory: service)

    async with postgres_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        user_id = user.id
        assert user.has_matrix is False
        assert user.subscription_status != "premium"
        assert await _count(session, Order) == 0
        assert await _count(session, PaymentAttempt) == 0
        assert await _count(session, PaymentEvent) == 0
        assert await _count(session, ChatMessageUsage) == 5

    transport = RecordingBotSession()
    bot = Bot(token=BOT_TOKEN, session=transport)
    dispatcher = _payment_dispatcher()
    try:
        await dispatcher.feed_update(bot, _callback_update(bot, 601, "buy_matrix"))
        first_payment_message = next(
            method
            for method in reversed(transport.methods)
            if method.__api_method__ == "editMessageText"
        )
        checkout_url = first_payment_message.reply_markup.inline_keyboard[0][0].url
        assert checkout_url is not None
        checkout_token = checkout_url.rsplit("/", 1)[1]
        assert str(TELEGRAM_ID) not in checkout_token
        assert checkout_token != str(user_id)

        await dispatcher.feed_update(bot, _callback_update(bot, 602, "buy_matrix"))
        repeated_payment_message = next(
            method
            for method in reversed(transport.methods)
            if method.__api_method__ == "editMessageText"
        )
        assert repeated_payment_message.reply_markup.inline_keyboard[0][0].url == checkout_url
    finally:
        await dispatcher.storage.close()
        await bot.session.close()

    async with postgres_factory() as session:
        order = (await session.execute(select(Order))).scalar_one()
        assert order.user_id == user_id
        assert order.product_code == "full_matrix"
        assert order.amount_kopecks == 89_000 and order.currency == "RUB"
        assert order.status == OrderStatus.CREATED
        assert order.checkout_token == checkout_token
        assert await _count(session, PaymentAttempt) == 0
        assert await _count(session, PaymentEvent) == 0

    app = FastAPI()
    app.state.limiter = payment_route.limiter
    app.include_router(payment_route.router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://nura.sandbox"
    ) as client:
        checkout_page = await client.get(
            f"/api/v1/payment/full-matrix/checkout/{checkout_token}"
        )
        assert checkout_page.status_code == 200
        assert "890" in checkout_page.text
        assert "email" in checkout_page.text.lower()

        first_checkout = await client.post(
            f"/api/v1/payment/full-matrix/checkout/{checkout_token}",
            content="email=sandbox.receipt%40example.test",
            headers={"content-type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        assert first_checkout.status_code == 303
        assert first_checkout.headers["location"] == "https://yookassa.sandbox/pay/1"

    fresh_service = FullMatrixCheckoutService(postgres_factory, provider)
    monkeypatch.setattr(
        payment_route, "FullMatrixCheckoutService", lambda _factory: fresh_service
    )
    fresh_app = FastAPI()
    fresh_app.state.limiter = payment_route.limiter
    fresh_app.include_router(payment_route.router)
    async with AsyncClient(
        transport=ASGITransport(fresh_app), base_url="https://nura.sandbox"
    ) as client:
        duplicate_checkout = await client.post(
            f"/api/v1/payment/full-matrix/checkout/{checkout_token}",
            content="email=sandbox.receipt%40example.test",
            headers={"content-type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        assert duplicate_checkout.status_code == 303
        assert duplicate_checkout.headers["location"] == "https://yookassa.sandbox/pay/1"
        returned = await client.get(
            f"/api/v1/payment/full-matrix/return/{checkout_token}"
        )
        assert returned.status_code == 200

    assert len(provider.created) == 1
    provider_key, payload = provider.created[0]
    assert len(provider_key) == 64
    assert payload["amount"] == {"value": "890.00", "currency": "RUB"}
    assert payload["save_payment_method"] is False
    assert payload["receipt"]["customer"] == {"email": "sandbox.receipt@example.test"}
    assert payload["metadata"]["product_code"] == "full_matrix"
    assert provider.get_calls == 0

    async with postgres_factory() as session:
        order = (await session.execute(select(Order))).scalar_one()
        attempt = (await session.execute(select(PaymentAttempt))).scalar_one()
        user = await session.get(User, user_id)
        assert order.status == OrderStatus.PENDING
        assert attempt.order_id == order.id
        assert attempt.status == "pending"
        assert attempt.fiscal_email == "sandbox.receipt@example.test"
        assert attempt.provider_payment_id == "sandbox-yookassa-1"
        assert attempt.confirmation_url == "https://yookassa.sandbox/pay/1"
        assert attempt.idempotency_key == provider_key
        assert user is not None and user.has_matrix is False
        assert await _count(session, PaymentEvent) == 0
        assert await _count(session, Report) == 1
        assert await _count(session, ReportGenerationJob) == 0
        assert await _count(session, FullReportTelegramDelivery) == 0
        assert await _count(session, TelegramReportDelivery) == 2
        assert await _count(session, DailyTarotDraw) == 1
        assert await _count(session, ChatMessageUsage) == 5

    assert (await MyReportsService(postgres_factory).list_user_reports(user_id, 0)).total == 1


@pytest.mark.asyncio
async def test_verified_webhook_activates_checkout_once(
    postgres_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Continue the same checkout through the production webhook HTTP boundary."""
    provider = VerifiedWebhookYooKassa(postgres_factory)
    service = FullMatrixCheckoutService(postgres_factory, provider)
    dispatched: list[str] = []
    monkeypatch.setattr(payment_route, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(payment_route, "FullMatrixCheckoutService", lambda _factory: service)
    monkeypatch.setattr(
        tasks.notify_full_matrix_payment_confirmed,
        "delay",
        lambda public_order_id: dispatched.append(public_order_id),
    )

    async with postgres_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        order = (await session.execute(select(Order))).scalar_one()
        attempt = (await session.execute(select(PaymentAttempt))).scalar_one()
        assert user.has_matrix is False
        assert order.status == OrderStatus.PENDING
        assert attempt.status == "pending"
        assert attempt.provider_payment_id
        assert await _count(session, PaymentEvent) == 0
        assert await _count(session, ReportGenerationJob) == 0
        provider_payment_id = attempt.provider_payment_id

    payload = {
        "event": "payment.succeeded",
        "object": {
            "id": provider_payment_id,
            "metadata": {"product_code": "full_matrix"},
        },
    }
    app = FastAPI()
    app.state.limiter = payment_route.limiter
    app.include_router(payment_route.router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://nura.sandbox"
    ) as client:
        response = await client.post("/api/v1/payment/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "result": "activated", "order_id": order.public_id}
    assert provider.claim_observed_before_lookup is True
    assert provider.get_calls == 1
    assert dispatched == [order.public_id]

    async with postgres_factory() as session:
        user = await session.get(User, user.id)
        order = (await session.execute(select(Order))).scalar_one()
        attempt = (await session.execute(select(PaymentAttempt))).scalar_one()
        event = (await session.execute(select(PaymentEvent))).scalar_one()
        full_report = (
            await session.execute(select(Report).where(Report.report_type == ReportType.FULL.value))
        ).scalar_one()
        job = (await session.execute(select(ReportGenerationJob))).scalar_one()
        assert user is not None and user.has_matrix is True
        assert order.status == OrderStatus.PAID and order.paid_at is not None
        assert order.activated_at is not None and order.report_id == full_report.id
        assert attempt.status == "succeeded" and attempt.paid_at is not None
        assert attempt.fiscal_email == "sandbox.receipt@example.test"
        assert event.provider_event_type == "payment.succeeded"
        assert event.provider_payment_id == provider_payment_id
        assert event.processing_status == "processed" and event.attempt_count == 1
        assert event.claimed_at is not None and event.processed_at is not None
        assert event.error_code is None and event.error_detail is None and event.retryable is False
        assert full_report.user_id == user.id and full_report.order_id == order.id
        assert full_report.payment_state == "payment_confirmed"
        assert full_report.generation_state == "pending_dispatch"
        assert full_report.ai_analysis is None and full_report.artifact_bytes is None
        assert job.report_id == full_report.id and job.state == "pending_dispatch"
        assert await _count(session, Report) == 2
        assert await _count(session, ReportGenerationJob) == 1
        assert await _count(session, FullReportTelegramDelivery) == 0
        assert await _count(session, TelegramReportDelivery) == 2
        assert await _count(session, DailyTarotDraw) == 1
        assert await _count(session, ChatMessageUsage) == 5

@pytest.mark.asyncio
async def test_verified_webhook_fresh_process_replay(
    postgres_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replay the verified webhook in a new interpreter against the same database."""
    if os.environ.get("NURA_GOLDEN_PATH_REPLAY_CHILD") != "1":
        child_env = os.environ.copy()
        child_env["NURA_GOLDEN_PATH_REPLAY_CHILD"] = "1"
        completed = subprocess.run(
            (
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                f"{Path(__file__).name}::test_verified_webhook_fresh_process_replay",
                "-q",
            ),
            cwd=Path(__file__).parent,
            env=child_env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, "fresh_process_webhook_replay_failed"
        return

    provider = VerifiedWebhookYooKassa(postgres_factory, fail_on_lookup=True)
    service = FullMatrixCheckoutService(postgres_factory, provider)
    dispatched: list[str] = []
    monkeypatch.setattr(payment_route, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(payment_route, "FullMatrixCheckoutService", lambda _factory: service)
    monkeypatch.setattr(
        tasks.notify_full_matrix_payment_confirmed,
        "delay",
        lambda public_order_id: dispatched.append(public_order_id),
    )
    async with postgres_factory() as session:
        order = (await session.execute(select(Order))).scalar_one()
        provider_payment_id = (await session.execute(select(PaymentAttempt))).scalar_one().provider_payment_id
    payload = {
        "event": "payment.succeeded",
        "object": {
            "id": provider_payment_id,
            "metadata": {"product_code": "full_matrix"},
        },
    }
    fresh_app = FastAPI()
    fresh_app.state.limiter = payment_route.limiter
    fresh_app.include_router(payment_route.router)
    async with AsyncClient(
        transport=ASGITransport(fresh_app), base_url="https://nura.sandbox"
    ) as client:
        replay = await client.post("/api/v1/payment/webhook", json=payload)

    assert replay.status_code == 200
    assert replay.json() == {"status": "ok", "result": "already_processed"}
    assert provider.get_calls == 0
    assert dispatched == []


@pytest.mark.asyncio
async def test_full_report_generation_uses_existing_job_and_dispatches_delivery_once(
    postgres_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Continue the paid report through dispatcher and registered generation task."""
    async with postgres_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        order = (await session.execute(select(Order))).scalar_one()
        attempt = (await session.execute(select(PaymentAttempt))).scalar_one()
        event = (await session.execute(select(PaymentEvent))).scalar_one()
        mini_report = (
            await session.execute(select(Report).where(Report.report_type == ReportType.MINI.value))
        ).scalar_one()
        full_report = (
            await session.execute(select(Report).where(Report.report_type == ReportType.FULL.value))
        ).scalar_one()
        job = (await session.execute(select(ReportGenerationJob))).scalar_one()
        assert await _count(session, User) == 1
        assert await _count(session, Report) == 2
        assert await _count(session, TelegramReportDelivery) == 2
        assert await _count(session, FullReportTelegramDelivery) == 0
        assert full_report.generation_state == ReportGenerationState.PENDING_DISPATCH
        assert job.state == ReportGenerationJobState.PENDING_DISPATCH
        assert mini_report.artifact_bytes and mini_report.artifact_sha256
        user_id, report_id, job_id = user.id, full_report.id, job.id
        mini_artifact = mini_report.artifact_bytes
        mini_sha256 = mini_report.artifact_sha256
        assert order.status == OrderStatus.PAID
        assert attempt.status == "succeeded" and event.processing_status == "processed"

    publisher = RecordingGenerationPublisher()
    dispatch = await ReportGenerationDispatcher(postgres_factory, publisher).dispatch_batch(
        now=datetime.now(timezone.utc), limit=1
    )
    assert (dispatch.selected, dispatch.claimed, dispatch.published) == (1, 1, 1)
    assert publisher.calls == [(job_id, report_id, publisher.calls[0][2])]

    matrix_calls: list[str] = []
    full_generation_calls: list[tuple[str, str]] = []
    provider_calls: list[str] = []
    pdf_calls: list[str] = []
    delivery_dispatches: list[str] = []
    real_calculate = MatrixService.calculate
    real_full_loop = report_loop.generate_full_report_with_loop
    real_generate_pdf = ReportService.generate_pdf.__func__

    def calculate_spy(birth_date: str) -> Any:
        matrix_calls.append(birth_date)
        return real_calculate(birth_date)

    async def full_loop_spy(birth_date: str, matrix: Any, *, name: str = "user") -> dict:
        full_generation_calls.append((birth_date, name))
        return await real_full_loop(birth_date, matrix, name=name)

    async def fake_ai_chat(*_args: Any, **kwargs: Any) -> str:
        method_name = str(kwargs["method_name"])
        provider_calls.append(method_name)
        if method_name.startswith("full_report_"):
            return FULL_AI_JSON
        pytest.fail(f"unexpected_external_ai_call:{method_name}")

    async def fake_kitchen_ai(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return FALLBACK_KITCHEN

    async def generate_pdf_spy(cls: type[ReportService], html_content: str) -> bytes:
        assert "Sandbox" in html_content
        pdf_calls.append(html_content)
        return await real_generate_pdf(cls, html_content)

    monkeypatch.setattr(tasks, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(database_module, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(MatrixService, "calculate", calculate_spy)
    monkeypatch.setattr(report_loop, "generate_full_report_with_loop", full_loop_spy)
    monkeypatch.setattr(AIService, "chat", fake_ai_chat)
    monkeypatch.setattr(AIService, "generate_kitchen_report", fake_kitchen_ai)
    monkeypatch.setattr(ReportService, "generate_pdf", classmethod(generate_pdf_spy))
    monkeypatch.setattr(
        tasks.deliver_full_report, "delay", lambda delivery_id: delivery_dispatches.append(delivery_id)
    )

    assert tasks.celery_app.tasks["core.tasks.process_report_generation_job"].name == (
        tasks.process_report_generation_job.name
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            result = await _run_registered_task(
                executor, tasks.process_report_generation_job, str(job_id), str(report_id)
            )
        finally:
            await _reset_task_runtime(executor)

    assert result == {"ok": True, "disposition": "completed"}
    assert matrix_calls == [BIRTH_DATE]
    assert full_generation_calls == [(BIRTH_DATE, "Sandbox")]
    assert provider_calls and all(name.startswith("full_report_") for name in provider_calls)
    assert len(pdf_calls) == 1
    assert len(delivery_dispatches) == 1

    async with postgres_factory() as session:
        full_report = await session.get(Report, report_id)
        job = await session.get(ReportGenerationJob, job_id)
        mini_report = (
            await session.execute(select(Report).where(Report.report_type == ReportType.MINI.value))
        ).scalar_one()
        delivery = (await session.execute(select(FullReportTelegramDelivery))).scalar_one()
        assert full_report is not None and job is not None
        assert full_report.generation_state == ReportGenerationState.COMPLETED
        assert full_report.generated_at is not None and full_report.ai_analysis == {
            **FULL_AI_ANALYSIS,
            "dashboard_insights": None,
        }
        assert full_report.artifact_bytes and full_report.artifact_bytes.startswith(b"%PDF-")
        assert full_report.artifact_mime_type == "application/pdf"
        assert full_report.artifact_size_bytes == len(full_report.artifact_bytes)
        assert full_report.artifact_sha256 == hashlib.sha256(full_report.artifact_bytes).hexdigest()
        assert full_report.artifact_completed_at is not None
        assert job.state == ReportGenerationJobState.COMPLETED and job.completed_at is not None
        assert job.last_error_category is None and job.next_attempt_at is None
        assert delivery.report_id == report_id and delivery.id.hex == delivery_dispatches[0].replace("-", "")
        assert mini_report.artifact_bytes == mini_artifact
        assert mini_report.artifact_sha256 == mini_sha256
        assert await _count(session, User) == 1
        assert await _count(session, Order) == 1
        assert await _count(session, PaymentAttempt) == 1
        assert await _count(session, PaymentEvent) == 1
        assert await _count(session, Report) == 2
        assert await _count(session, ReportGenerationJob) == 1
        assert await _count(session, FullReportTelegramDelivery) == 1

    reports = await MyReportsService(postgres_factory).list_user_reports(user_id, 0)
    assert reports.total == 2


@pytest.mark.asyncio
async def test_full_report_generation_fresh_process_replay_is_idempotent(
    postgres_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh interpreter replays the registered task without new side effects."""
    if os.environ.get("NURA_GOLDEN_PATH_REPLAY_CHILD") != "full_generation":
        child_env = os.environ.copy()
        child_env["NURA_GOLDEN_PATH_REPLAY_CHILD"] = "full_generation"
        completed = subprocess.run(
            (
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                f"{Path(__file__).name}::test_full_report_generation_fresh_process_replay_is_idempotent",
                "-q",
            ),
            cwd=Path(__file__).parent,
            env=child_env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, "fresh_process_full_generation_replay_failed"
        return

    async with postgres_factory() as session:
        full_report = (
            await session.execute(select(Report).where(Report.report_type == ReportType.FULL.value))
        ).scalar_one()
        job = (await session.execute(select(ReportGenerationJob))).scalar_one()
        before = (
            full_report.artifact_sha256,
            full_report.artifact_size_bytes,
            full_report.artifact_bytes,
        )
        report_id, job_id = full_report.id, job.id

    async def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("generation_replay_must_not_call_side_effect")

    monkeypatch.setattr(tasks, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(database_module, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(MatrixService, "calculate", forbidden)
    monkeypatch.setattr(AIService, "chat", forbidden)
    monkeypatch.setattr(ReportService, "generate_pdf", classmethod(forbidden))
    monkeypatch.setattr(tasks.deliver_full_report, "delay", forbidden)

    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            result = await _run_registered_task(
                executor, tasks.process_report_generation_job, str(job_id), str(report_id)
            )
        finally:
            await _reset_task_runtime(executor)

    assert result == {"ok": True, "idempotent": True, "disposition": "idempotent_completed"}
    async with postgres_factory() as session:
        full_report = await session.get(Report, report_id)
        job = await session.get(ReportGenerationJob, job_id)
        assert full_report is not None and job is not None
        assert full_report.generation_state == ReportGenerationState.COMPLETED
        assert job.state == ReportGenerationJobState.COMPLETED
        assert (
            full_report.artifact_sha256,
            full_report.artifact_size_bytes,
            full_report.artifact_bytes,
        ) == before
        assert await _count(session, FullReportTelegramDelivery) == 1


@pytest.mark.asyncio
async def test_automatic_full_report_delivery_uses_queued_registered_task(
    postgres_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Continue the generation-owned queued delivery through its registered task."""
    async with postgres_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        order = (await session.execute(select(Order))).scalar_one()
        attempt = (await session.execute(select(PaymentAttempt))).scalar_one()
        event = (await session.execute(select(PaymentEvent))).scalar_one()
        full_report = (
            await session.execute(
                select(Report).where(Report.report_type == ReportType.FULL.value)
            )
        ).scalar_one()
        job = (await session.execute(select(ReportGenerationJob))).scalar_one()
        delivery = (await session.execute(select(FullReportTelegramDelivery))).scalar_one()
        assert delivery.status == "queued" and delivery.attempt_count == 0
        assert delivery.delivery_reason == "automatic" and delivery.request_key == "automatic"
        assert delivery.report_id == full_report.id and delivery.user_id == user.id
        assert full_report.generation_state == ReportGenerationState.COMPLETED
        assert full_report.artifact_bytes and full_report.artifact_mime_type == "application/pdf"
        assert full_report.artifact_size_bytes == len(full_report.artifact_bytes)
        assert full_report.artifact_sha256 == hashlib.sha256(full_report.artifact_bytes).hexdigest()
        assert user.telegram_id == TELEGRAM_ID and user.account_status == "active" and user.has_matrix
        assert order.status == OrderStatus.PAID
        assert attempt.status == "succeeded" and event.processing_status == "processed"
        report_id, job_id, delivery_id = full_report.id, job.id, delivery.id
        artifact = full_report.artifact_bytes

    RecordingFullDeliveryAdapter.reset()
    monkeypatch.setattr(tasks, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(database_module, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(
        full_delivery_module, "TelegramDocumentAdapter", RecordingFullDeliveryAdapter
    )

    async def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("automatic_delivery_must_not_regenerate_or_repurchase")

    monkeypatch.setattr(MatrixService, "calculate", forbidden)
    monkeypatch.setattr(AIService, "chat", forbidden)
    monkeypatch.setattr(ReportService, "generate_pdf", classmethod(forbidden))

    assert tasks.celery_app.tasks["core.tasks.deliver_full_report"].name == (
        tasks.deliver_full_report.name
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            result = await _run_registered_task(
                executor, tasks.deliver_full_report, str(delivery_id)
            )
        finally:
            await _reset_task_runtime(executor)

    assert result is None
    assert len(RecordingFullDeliveryAdapter.instances) == 1
    sender = RecordingFullDeliveryAdapter.instances[0]
    assert sender.file_id_requests == []
    assert len(sender.documents) == 1
    chat_id, sent_artifact, filename, caption = sender.documents[0]
    assert chat_id == TELEGRAM_ID and sent_artifact == artifact
    assert filename == "NURA-full-matrix.pdf"
    assert "<script" not in caption.casefold()

    async with postgres_factory() as session:
        full_report = await session.get(Report, report_id)
        job = await session.get(ReportGenerationJob, job_id)
        delivery = await session.get(FullReportTelegramDelivery, delivery_id)
        assert full_report is not None and job is not None and delivery is not None
        assert delivery.status == "completed" and delivery.attempt_count == 1
        assert delivery.claimed_at is None and delivery.sent_at is not None
        assert delivery.telegram_document_message_id == 40_001
        assert delivery.telegram_file_id == "sandbox-full-file-1"
        assert full_report.generation_state == ReportGenerationState.COMPLETED
        assert job.state == ReportGenerationJobState.COMPLETED
        assert await _count(session, User) == 1
        assert await _count(session, Report) == 2
        assert await _count(session, ReportGenerationJob) == 1
        assert await _count(session, Order) == 1
        assert await _count(session, PaymentAttempt) == 1
        assert await _count(session, PaymentEvent) == 1
        assert await _count(session, FullReportTelegramDelivery) == 1


@pytest.mark.asyncio
async def test_automatic_full_report_delivery_fresh_process_replay_has_no_sends(
    postgres_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh interpreter replays the registered delivery task without Telegram sends."""
    if os.environ.get("NURA_GOLDEN_PATH_REPLAY_CHILD") != "automatic_delivery":
        child_env = os.environ.copy()
        child_env["NURA_GOLDEN_PATH_REPLAY_CHILD"] = "automatic_delivery"
        completed = subprocess.run(
            (
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                f"{Path(__file__).name}::test_automatic_full_report_delivery_fresh_process_replay_has_no_sends",
                "-q",
            ),
            cwd=Path(__file__).parent,
            env=child_env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, (
            "fresh_process_automatic_delivery_replay_failed:\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
        return

    async with postgres_factory() as session:
        delivery = (await session.execute(select(FullReportTelegramDelivery))).scalar_one()
        before = (
            delivery.status,
            delivery.attempt_count,
            delivery.telegram_document_message_id,
            delivery.telegram_file_id,
        )
        delivery_id = delivery.id

    RecordingFullDeliveryAdapter.reset()
    monkeypatch.setattr(tasks, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(database_module, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(
        full_delivery_module, "TelegramDocumentAdapter", RecordingFullDeliveryAdapter
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            result = await _run_registered_task(
                executor, tasks.deliver_full_report, str(delivery_id)
            )
        finally:
            await _reset_task_runtime(executor)

    assert result is None
    assert all(
        not adapter.documents and not adapter.file_id_requests
        for adapter in RecordingFullDeliveryAdapter.instances
    )
    async with postgres_factory() as session:
        delivery = await session.get(FullReportTelegramDelivery, delivery_id)
        assert delivery is not None
        assert (
            delivery.status,
            delivery.attempt_count,
            delivery.telegram_document_message_id,
            delivery.telegram_file_id,
        ) == before


@pytest.mark.asyncio
async def test_manual_full_report_resend_reuses_persisted_file_id(
    postgres_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the real My Reports callbacks to resend the existing paid full report."""
    async with postgres_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        reports = (await session.execute(select(Report).order_by(Report.created_at))).scalars().all()
        full_report = next(report for report in reports if report.report_type == ReportType.FULL.value)
        automatic = (
            await session.execute(
                select(FullReportTelegramDelivery).where(
                    FullReportTelegramDelivery.delivery_reason == "automatic"
                )
            )
        ).scalar_one()
        assert full_report.generation_state == ReportGenerationState.COMPLETED
        assert full_report.artifact_bytes and full_report.artifact_mime_type == "application/pdf"
        assert automatic.status == "completed" and automatic.telegram_file_id
        user_id, report_id = user.id, full_report.id
        artifact_sha256, artifact_size = full_report.artifact_sha256, full_report.artifact_size_bytes
        automatic_message_id, canonical_file_id = (
            automatic.telegram_document_message_id,
            automatic.telegram_file_id,
        )

    monkeypatch.setattr(profile, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(tasks, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(database_module, "get_async_sessionmaker", lambda: postgres_factory)
    RecordingFullDeliveryAdapter.reset()
    monkeypatch.setattr(
        full_delivery_module, "TelegramDocumentAdapter", RecordingFullDeliveryAdapter
    )

    async def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("manual_full_resend_must_not_regenerate_or_repurchase")

    monkeypatch.setattr(MatrixService, "calculate", forbidden)
    monkeypatch.setattr(AIService, "chat", forbidden)
    monkeypatch.setattr(ReportService, "generate_pdf", classmethod(forbidden))
    manual_dispatches: list[str] = []
    monkeypatch.setattr(
        profile.deliver_full_report,
        "delay",
        lambda delivery_id: manual_dispatches.append(delivery_id),
    )

    transport = RecordingBotSession()
    bot = Bot(token=BOT_TOKEN, session=transport)
    dispatcher = _profile_dispatcher()
    send_callback = "reports:send:" + report_id.hex
    try:
        await dispatcher.feed_update(bot, _callback_update(bot, 2101, "reports:list:0"))
        list_edit = next(
            method for method in transport.methods if method.__api_method__ == "editMessageText"
        )
        list_callbacks = [
            button.callback_data
            for row in list_edit.reply_markup.inline_keyboard
            for button in row
            if button.callback_data
        ]
        assert f"reports:view:{report_id.hex}" in list_callbacks
        assert len([value for value in list_callbacks if value.startswith("reports:view:")]) == 2
        await dispatcher.feed_update(bot, _callback_update(bot, 2102, f"reports:view:{report_id.hex}"))
        await dispatcher.feed_update(bot, _callback_update(bot, 2103, send_callback))
        # A repeated Telegram callback has the same production callback identity.
        await dispatcher.feed_update(bot, _callback_update(bot, 2103, send_callback))
    finally:
        await dispatcher.storage.close()
        await bot.session.close()

    assert len(manual_dispatches) == 2 and manual_dispatches[0] == manual_dispatches[1]
    delivery_id = uuid.UUID(manual_dispatches[0])
    async with postgres_factory() as session:
        manual_rows = (
            await session.execute(
                select(FullReportTelegramDelivery).where(
                    FullReportTelegramDelivery.delivery_reason == "manual"
                )
            )
        ).scalars().all()
        assert len(manual_rows) == 1
        manual = manual_rows[0]
        assert manual.id == delivery_id and manual.report_id == report_id and manual.user_id == user_id
        assert manual.status == "queued" and manual.request_key == hashlib.sha256(
            "callback-2103".encode()
        ).hexdigest()

    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            await _run_registered_task(executor, tasks.deliver_full_report, str(delivery_id))
            await _run_registered_task(executor, tasks.deliver_full_report, str(delivery_id))
        finally:
            await _reset_task_runtime(executor)

    assert sum(len(adapter.documents) for adapter in RecordingFullDeliveryAdapter.instances) == 0
    file_id_requests = [
        request
        for adapter in RecordingFullDeliveryAdapter.instances
        for request in adapter.file_id_requests
    ]
    assert len(file_id_requests) == 1 and file_id_requests[0][0:2] == (
        TELEGRAM_ID,
        canonical_file_id,
    )

    async with postgres_factory() as session:
        manual = await session.get(FullReportTelegramDelivery, delivery_id)
        automatic = (
            await session.execute(
                select(FullReportTelegramDelivery).where(
                    FullReportTelegramDelivery.delivery_reason == "automatic"
                )
            )
        ).scalar_one()
        report = await session.get(Report, report_id)
        assert manual is not None and report is not None
        assert manual.status == "completed" and manual.attempt_count == 1
        assert manual.telegram_document_message_id == 41_001
        assert manual.telegram_file_id == canonical_file_id
        assert automatic.telegram_document_message_id == automatic_message_id
        assert automatic.telegram_file_id == canonical_file_id
        assert report.artifact_sha256 == artifact_sha256 and report.artifact_size_bytes == artifact_size
        assert await _count(session, User) == 1
        assert await _count(session, Report) == 2
        assert await _count(session, ReportGenerationJob) == 1
        assert await _count(session, Order) == 1
        assert await _count(session, PaymentAttempt) == 1
        assert await _count(session, PaymentEvent) == 1
        assert await _count(session, FullReportTelegramDelivery) == 2


@pytest.mark.asyncio
async def test_manual_full_report_resend_fresh_process_replay_has_no_sends(
    postgres_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new interpreter cannot resend an already completed manual request."""
    if os.environ.get("NURA_GOLDEN_PATH_REPLAY_CHILD") != "manual_resend":
        child_env = os.environ.copy()
        child_env["NURA_GOLDEN_PATH_REPLAY_CHILD"] = "manual_resend"
        completed = subprocess.run(
            (
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                f"{Path(__file__).name}::test_manual_full_report_resend_fresh_process_replay_has_no_sends",
                "-q",
            ),
            cwd=Path(__file__).parent,
            env=child_env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, (
            "fresh_process_manual_resend_replay_failed:\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
        return

    async with postgres_factory() as session:
        manual = (
            await session.execute(
                select(FullReportTelegramDelivery).where(
                    FullReportTelegramDelivery.delivery_reason == "manual"
                )
            )
        ).scalar_one()
        before = (
            manual.status,
            manual.attempt_count,
            manual.telegram_document_message_id,
            manual.telegram_file_id,
        )

    RecordingFullDeliveryAdapter.reset()
    monkeypatch.setattr(tasks, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(database_module, "get_async_sessionmaker", lambda: postgres_factory)
    monkeypatch.setattr(
        full_delivery_module, "TelegramDocumentAdapter", RecordingFullDeliveryAdapter
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            await _run_registered_task(executor, tasks.deliver_full_report, str(manual.id))
        finally:
            await _reset_task_runtime(executor)

    assert all(
        not adapter.documents and not adapter.file_id_requests
        for adapter in RecordingFullDeliveryAdapter.instances
    )
    async with postgres_factory() as session:
        manual = await session.get(FullReportTelegramDelivery, manual.id)
        assert manual is not None
        assert (
            manual.status,
            manual.attempt_count,
            manual.telegram_document_message_id,
            manual.telegram_file_id,
        ) == before


@pytest.mark.asyncio
async def test_full_restart_durability(
    postgres_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Recreate all application dependencies in one child interpreter on the same DB/Redis."""
    child_marker = os.environ.get("NURA_GOLDEN_PATH_RESTART_CHILD")
    redis = _redis_for_sandbox()
    if child_marker != "1":
        before = await _durability_snapshot(postgres_factory, redis)
        proof_path = tmp_path / "full-restart-proof.json"
        child_env = os.environ.copy()
        child_env.update(
            {
                "NURA_GOLDEN_PATH_RESTART_CHILD": "1",
                "NURA_GOLDEN_PATH_RESTART_PROOF": str(proof_path),
            }
        )
        completed = subprocess.run(
            (
                sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
                f"{Path(__file__).name}::test_full_restart_durability", "-q",
            ),
            cwd=Path(__file__).parent, env=child_env, capture_output=True,
            text=True, check=False,
        )
        assert completed.returncode == 0, (
            "full_restart_durability_child_failed:\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        assert proof["pid"] != os.getpid()
        assert proof["database_url"] == os.environ["NURA_GOLDEN_PATH_DATABASE_URL"]
        assert proof["redis_url"] == os.environ["REDIS_URL"]
        assert proof["before"] == proof["after"] == before
        assert await _durability_snapshot(postgres_factory, redis) == before
        return

    # This child deliberately uses the production runtime factory created from
    # its environment, rather than the parent fixture's engine/session objects.
    runtime_factory = database_module.get_async_sessionmaker()
    async with runtime_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        draw = (await session.execute(select(DailyTarotDraw))).scalar_one()
        order = (await session.execute(select(Order))).scalar_one()
        attempt = (await session.execute(select(PaymentAttempt))).scalar_one()
        full_report = (
            await session.execute(select(Report).where(Report.report_type == ReportType.FULL.value))
        ).scalar_one()
        job = (await session.execute(select(ReportGenerationJob))).scalar_one()
        deliveries = (await session.execute(select(FullReportTelegramDelivery))).scalars().all()
        assert user.has_matrix and draw.status == DailyTarotDrawState.COMPLETED
        assert order.status == OrderStatus.PAID and attempt.status == "succeeded"
        assert full_report.generation_state == ReportGenerationState.COMPLETED
        assert job.state == ReportGenerationJobState.COMPLETED
        assert len(deliveries) == 2 and {row.status for row in deliveries} == {"completed"}

    before = await _durability_snapshot(runtime_factory, redis)
    reports = await MyReportsService(runtime_factory).list_user_reports(user.id, 0)
    assert reports.total == 2 and {item.report_type for item in reports.items} == {
        ReportType.MINI.value, ReportType.FULL.value,
    }

    tarot_ai = RecordingDailyTarotAI(runtime_factory, user.id, forbidden=True)
    tarot_service = DailyTarotApplicationService(
        user_repository=UserRepository(runtime_factory),
        draw_repository=DailyTarotDrawRepository(runtime_factory),
        ai_service=tarot_ai, now_provider=lambda: DAILY_TAROT_NOW,
    )
    tarot_result = await tarot_service.get_daily_card(DailyTarotRequest(user_id=user.id))
    assert tarot_result.kind.value == "completed_reused" and tarot_result.draw_id == draw.id
    assert tarot_ai.calls == []

    quota = ChatQuotaService(runtime_factory)
    replay = await quota.reserve(
        user.id, chat._telegram_request_key(TELEGRAM_ID, 505), ChatChannel.TELEGRAM, subscriber=False
    )
    exhausted = await quota.reserve(user.id, chat._telegram_request_key(TELEGRAM_ID, 506), ChatChannel.TELEGRAM, subscriber=False)
    assert replay.kind.value == "duplicate_result" and exhausted.kind.value == "exhausted"

    class ForbiddenProvider:
        async def create_payment(self, **_kwargs: Any) -> dict[str, Any]:
            pytest.fail("restart replay must not create provider payment")

        async def get_payment(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            pytest.fail("restart replay must not look up provider payment")

    webhook = await FullMatrixCheckoutService(runtime_factory, ForbiddenProvider()).process_webhook(
        {"event": "payment.succeeded", "object": {"id": attempt.provider_payment_id}}
    )
    assert webhook == {"status": "ok", "result": "already_processed"}

    async def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("restart replay must not call an external boundary")

    monkeypatch.setattr(MatrixService, "calculate", forbidden)
    monkeypatch.setattr(AIService, "chat", forbidden)
    monkeypatch.setattr(ReportService, "generate_pdf", classmethod(forbidden))
    monkeypatch.setattr(tasks.deliver_full_report, "delay", forbidden)
    RecordingFullDeliveryAdapter.reset()
    monkeypatch.setattr(full_delivery_module, "TelegramDocumentAdapter", RecordingFullDeliveryAdapter)
    # The production task wrapper owns a separate event loop in its worker
    # thread. Dispose the child readback engine before that runtime creates its
    # own production factory, exactly as an application restart would.
    await database_module.dispose_async_database_state()
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            generation = await _run_registered_task(
                executor, tasks.process_report_generation_job, str(job.id), str(full_report.id)
            )
            assert generation["disposition"] == "idempotent_completed"
            for delivery in deliveries:
                assert await _run_registered_task(executor, tasks.deliver_full_report, str(delivery.id)) is None
        finally:
            await _reset_task_runtime(executor)
    assert all(not adapter.documents and not adapter.file_id_requests for adapter in RecordingFullDeliveryAdapter.instances)

    database_module.reset_async_database_state_after_fork()
    runtime_factory = database_module.get_async_sessionmaker()
    after = await _durability_snapshot(runtime_factory, redis)
    assert after == before
    Path(os.environ["NURA_GOLDEN_PATH_RESTART_PROOF"]).write_text(
        json.dumps(
            {
                "pid": os.getpid(), "database_url": os.environ["NURA_GOLDEN_PATH_DATABASE_URL"],
                "redis_url": os.environ["REDIS_URL"], "before": before, "after": after,
            }, sort_keys=True
        ), encoding="utf-8",
    )
    await database_module.dispose_async_database_state()


@pytest.mark.asyncio
async def test_refund_replay_revokes_entitlement_and_blocks_delivery(
    postgres_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Use the production webhook boundary for the paid cumulative order."""
    child = os.environ.get("NURA_GOLDEN_PATH_REFUND_CHILD") == "1"
    async with postgres_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        order = (await session.execute(select(Order))).scalar_one()
        attempt = (await session.execute(select(PaymentAttempt))).scalar_one()
        full_report = (
            await session.execute(
                select(Report).where(Report.report_type == ReportType.FULL.value)
            )
        ).scalar_one()

    payload = {
        "event": "refund.succeeded",
        "object": {
            "id": "fake-yookassa-refund-full-matrix",
            "payment_id": attempt.provider_payment_id,
        },
    }
    provider = RefundWebhookYooKassa(
        order.public_id,
        attempt.provider_payment_id,
        attempt.test_mode,
        forbidden=child,
    )
    result = await FullMatrixCheckoutService(postgres_factory, provider).process_webhook(payload)
    if child:
        assert result == {"status": "ok", "result": "already_processed"}
        assert provider.get_calls == 0
        return

    assert result == {"status": "ok", "result": "refunded"}
    assert provider.get_calls == 1
    assert provider.refund_calls == 1
    async with postgres_factory() as session:
        order = await session.get(Order, order.id)
        attempt = await session.get(PaymentAttempt, attempt.id)
        user = await session.get(User, user.id)
        events = (await session.execute(select(PaymentEvent))).scalars().all()
        assert order.status == OrderStatus.REFUNDED and order.refunded_at is not None
        assert attempt.status == "refunded" and attempt.refunded_at is not None
        assert user.has_matrix is False
        assert len(events) == 2 and {event.provider_event_type for event in events} == {
            "payment.succeeded", "refund.succeeded"
        }
    reports = await MyReportsService(postgres_factory).list_user_reports(user.id, 0)
    assert reports.total == 1 and reports.items[0].report_type == ReportType.MINI.value
    assert await MyReportsService(postgres_factory).prepare_repeated_delivery(
        user.id, full_report.id, "refund-resend-request"
    ) is None

    child_env = os.environ.copy()
    child_env["NURA_GOLDEN_PATH_REFUND_CHILD"] = "1"
    completed = subprocess.run(
        (sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
         f"{Path(__file__).name}::test_refund_replay_revokes_entitlement_and_blocks_delivery", "-q"),
        cwd=Path(__file__).parent, env=child_env, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.asyncio
async def test_account_deletion_replay_anonymizes_financial_state_and_clears_redis(
    postgres_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Delete the same refunded persona via the production deletion service."""
    redis = _redis_for_sandbox()
    async with postgres_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        user_id = user.id
        order = (await session.execute(select(Order))).scalar_one()
        attempt = (await session.execute(select(PaymentAttempt))).scalar_one()
    assert await redis.get(chat_history_key(user_id)) is not None
    await AccountDeletionService(postgres_factory, redis).delete(user_id)
    await AccountDeletionService(postgres_factory, redis).delete(user_id)
    assert await redis.get(chat_history_key(user_id)) is None
    assert await redis.get(chat_history_marker_key(user_id)) is None
    async with postgres_factory() as session:
        assert await session.get(User, user_id) is None
        stored_order = await session.get(Order, order.id)
        stored_attempt = await session.get(PaymentAttempt, attempt.id)
        assert stored_order is not None and stored_attempt is not None
        assert stored_order.status == OrderStatus.REFUNDED
        assert stored_order.user_id is None and stored_order.report_id is None
        assert stored_order.anonymized_at is not None
        assert stored_attempt.anonymized_at is not None
        assert await _count(session, Report) == 0
        assert await _count(session, FullReportTelegramDelivery) == 0
    assert (await MyReportsService(postgres_factory).list_user_reports(user_id, 0)).total == 0
    replay = await FullMatrixCheckoutService(
        postgres_factory,
        RefundWebhookYooKassa(
            order.public_id,
            attempt.provider_payment_id,
            attempt.test_mode,
            forbidden=True,
        ),
    ).process_webhook(
        {
            "event": "refund.succeeded",
            "object": {
                "id": "fake-yookassa-refund-full-matrix",
                "payment_id": attempt.provider_payment_id,
            },
        }
    )
    assert replay == {"status": "ok", "result": "already_processed"}
