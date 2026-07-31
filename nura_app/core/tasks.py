import asyncio
import json
import logging
import uuid

import httpx
from datetime import date, datetime, timedelta, timezone

from celery import Celery
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import load_only

from core.config import settings
from core.celery_async import run_celery_async as _run_async
from core.database import get_async_sessionmaker, get_redis
from core.models import Order, ReportType, User
from core.repositories import ReportRepository, UserRepository
from core.repositories.guest import GuestProfileRepository
from core.repositories.mini_report_generation import MiniReportGenerationRepository
from bot.utils.arcana import _daily_arcana_number, _personal_arcana_number
from core.fallbacks import FALLBACK_TAROT_DAILY
from core.services.ai import AIService
from core.services.matrix import ARCANA, MatrixService
from core.services.mini_report_application import (
    MiniReportApplicationService,
    MiniReportRequest,
    MiniReportResultKind,
    UserMiniReportSubject,
)
from core.services.mini_report_generation import MiniReportGenerationService
from core.services.report import ReportService
from core.services.prompt_governance import (
    finalize_generation_metadata,
    input_hash,
    prompt_registry,
    resolve_active_bundle,
)
from core.services.telegram_report_delivery import MiniReportTelegramDeliveryService, TelegramDeliveryError
from core.services.web_push import PushSubscriptionExpired, send_web_push

MSK = timezone(timedelta(hours=3))

logger = logging.getLogger(__name__)

celery_app = Celery("nura")
celery_app.conf.update(
    broker_url=settings.celery_broker_url,
    result_backend=settings.celery_result_backend,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Moscow",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=480,
    task_soft_time_limit=360,
    broker_connection_retry_on_startup=True,
    task_default_queue=settings.celery_task_queue,
    task_default_exchange=settings.celery_task_queue,
    task_default_routing_key=settings.celery_task_queue,
)

_chat_delivery_schedule = {
    "reconcile-chat-deliveries": {
        "task": "core.tasks.reconcile_chat_deliveries",
        "schedule": timedelta(minutes=5),
        "kwargs": {"limit": 20},
    },
}

celery_app.conf.beat_schedule = _chat_delivery_schedule if settings.nura_tg_pilot else {
    "downgrade-expired-subscriptions": {
        "task": "core.tasks.downgrade_expired_subscriptions",
        "schedule": 60 * 60 * 24,
    },
    "cleanup-expired-guests": {
        "task": "core.tasks.cleanup_expired_guest_profiles",
        "schedule": 60 * 60 * 24,
    },
    "block-inactive-users": {
        "task": "core.tasks.block_inactive_users",
        "schedule": 60 * 60 * 6,
    },
    "delete-inactive-users": {
        "task": "core.tasks.delete_inactive_users",
        "schedule": 60 * 60 * 24,
    },
    "monitor-health": {
        "task": "core.tasks.monitor_health",
        "schedule": 60 * 5,
    },
    "dispatch-report-generation-jobs": {
        "task": "core.tasks.dispatch_report_generation_jobs",
        "schedule": timedelta(
            seconds=settings.report_generation_dispatch_interval_seconds
        ),
        "kwargs": {"limit": settings.report_generation_dispatch_limit},
        "options": {
            "expires": settings.report_generation_dispatch_interval_seconds - 5
        },
    },
    "reconcile-report-generation-jobs": {
        "task": "core.tasks.reconcile_report_generation_jobs",
        "schedule": timedelta(
            seconds=settings.report_generation_reconciliation_interval_seconds
        ),
        "kwargs": {"limit": settings.report_generation_reconciliation_limit},
        "options": {
            "expires": settings.report_generation_reconciliation_interval_seconds - 30
        },
    },
    "reconcile-broadcast-campaigns": {
        "task": "core.tasks.reconcile_broadcast_campaigns",
        "schedule": timedelta(minutes=1),
        "kwargs": {"limit": 20},
        "options": {"expires": 50},
    },
    **_chat_delivery_schedule,
}

async def _send_message(
    telegram_id: int,
    text: str,
    reply_markup: dict | None = None,
) -> bool:
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.exceptions import TelegramForbiddenError

    token = settings.telegram_bot_token
    if not token or token.startswith("change-me"):
        logger.warning("TELEGRAM_BOT_TOKEN not configured, skipping notification")
        return False

    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await bot.send_message(
            chat_id=telegram_id, text=text, reply_markup=reply_markup
        )
        return True
    except TelegramForbiddenError:
        return False
    finally:
        await bot.session.close()


async def _notify_full_report(telegram_id: int, token: str) -> None:
    report_url = ReportService.report_url(token)
    text = (
        "✨ Твой полный AI-отчёт готов!\n\n"
        "В нём:\n"
        "• Разбор 9 ключевых зон твоей матрицы\n"
        "• Теневые стороны и зоны роста\n"
        "• Жизненные циклы\n"
        "• 7-дневные рекомендации\n"
        "• Совместимость с другими архетипами\n\n"
        "Открой и изучи — это твоя карта."
    )
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "👁 Открыть отчёт", "url": report_url},
            ],
            [{"text": "🏠 В меню", "callback_data": "main_menu"}],
        ],
    }
    await _send_message(telegram_id, text, keyboard)


@celery_app.task(name="core.tasks.notify_full_matrix_payment_confirmed")
def notify_full_matrix_payment_confirmed(public_order_id: str) -> None:
    async def _run() -> None:
        async with get_async_sessionmaker()() as session:
            order = (
                await session.execute(select(Order).where(Order.public_id == public_order_id))
            ).scalar_one_or_none()
            if order is None or order.user_id is None:
                return
            user = await session.get(User, order.user_id)
            if user is None or user.telegram_id is None:
                return
            telegram_id = user.telegram_id
        await _send_message(
            telegram_id,
            "Оплата подтверждена. Готовлю полный разбор.",
        )
    _run_async(_run())


async def _notify_mini_report(telegram_id: int, token: str) -> None:
    text = (
        "✨ Твой мини-разбор готов!\n\n"
        "Матрица расшифрована. Загляни в профиль — "
        "там ждут 5 ключевых блоков твоего архетипа."
    )
    keyboard = {
        "inline_keyboard": [
            [{"text": "💎 Полный разбор по подписке", "callback_data": "buy_subscription"}],
            [{"text": "🏠 В меню", "callback_data": "main_menu"}],
        ],
    }
    await _send_message(telegram_id, text, keyboard)


def format_daily_card_message(first_name: str, card: dict) -> str:
    lines = [
        f"🃏 Твоя карта дня — {card['card_number']}. {card['card_name']}",
        "",
        card['key_phrase'],
        "",
        card['interpretation'],
    ]
    if card.get('matrix_link'):
        lines += ["", card['matrix_link']]
    lines += [
        "",
        f"💡 {card['advice']}",
        "",
        f"✨ {card['affirmation']}",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "Хочешь глубже? Загляни в ритуалы дня.",
    ]
    return "\n".join(lines)


async def _process_mini_report(user_id: str, birth_date: str, name: str = "user") -> dict:
    uid = uuid.UUID(user_id)
    session_factory = get_async_sessionmaker()
    report_repo = ReportRepository(session_factory)
    service = MiniReportApplicationService(
        MiniReportGenerationService(MiniReportGenerationRepository(session_factory)),
        report_repo,
        GuestProfileRepository(session_factory),
    )
    result = await service.generate(
        MiniReportRequest(
            owner=UserMiniReportSubject(uid),
            name=name,
            birth_date=birth_date,
            allow_retry=True,
        )
    )
    if result.kind == MiniReportResultKind.FAILED_RETRYABLE:
        raise ConnectionError(result.error_code or "mini_report_generation_failed")
    token = None
    if result.report_id is not None:
        report = await report_repo.get(result.report_id)
        token = report.token if report is not None else None
    return {
        "kind": result.kind,
        "generation_id": str(result.generation_id) if result.generation_id else None,
        "report_id": str(result.report_id) if result.report_id else None,
        "token": token,
        "analysis": result.content,
    }


async def _get_user_telegram_id(user_id: str) -> int | None:
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get(uuid.UUID(user_id))
    if user is None:
        logger.warning("User %s not found for notification", user_id)
        return None
    return user.telegram_id


@celery_app.task(
    name="core.tasks.generate_mini_report",
    autoretry_on=(SoftTimeLimitExceeded, TimeoutError, ConnectionError),
    max_retries=2,
    retry_backoff=20,
    retry_backoff_max=120,
    retry_jitter=True,
)
def generate_mini_report(user_id: str, birth_date: str, username: str) -> dict:
    async def _run_all():
        result = await _process_mini_report(user_id, birth_date, username)
        if result["kind"] in (MiniReportResultKind.COMPLETED_NEW, MiniReportResultKind.COMPLETED_REUSED) and result["report_id"]:
            deliver_mini_report.delay(user_id, result["report_id"], str(result.get("generation_id") or ""))
        return result
    return _run_async(_run_all())


@celery_app.task(
    bind=True,
    name="core.tasks.deliver_mini_report",
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def deliver_mini_report(self, user_id: str, report_id: str, generation_id: str) -> None:
    async def _run_delivery() -> None:
        try:
            await MiniReportTelegramDeliveryService(get_async_sessionmaker()).deliver(
                generation_id=uuid.UUID(generation_id), user_id=uuid.UUID(user_id), report_id=uuid.UUID(report_id)
            )
        except TelegramDeliveryError as error:
            if error.retryable:
                raise self.retry(
                    exc=ConnectionError(error.code),
                    countdown=error.retry_after or 20,
                ) from error
        except OperationalError as error:
            raise self.retry(
                exc=ConnectionError("delivery_database_unavailable"),
                countdown=settings.telegram_delivery_claim_timeout_seconds,
            ) from error
    return _run_async(_run_delivery())


@celery_app.task(
    bind=True,
    name="core.tasks.deliver_repeated_mini_report",
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def deliver_repeated_mini_report(
    self, user_id: str, report_id: str, generation_id: str, purpose: str
) -> None:
    async def _run_delivery() -> None:
        try:
            await MiniReportTelegramDeliveryService(get_async_sessionmaker()).deliver(
                generation_id=uuid.UUID(generation_id),
                user_id=uuid.UUID(user_id),
                report_id=uuid.UUID(report_id),
                purpose=purpose,
            )
        except TelegramDeliveryError as error:
            if error.retryable:
                raise self.retry(
                    exc=ConnectionError(error.code),
                    countdown=error.retry_after or 20,
                ) from error
        except OperationalError as error:
            raise self.retry(
                exc=ConnectionError("delivery_database_unavailable"),
                countdown=settings.telegram_delivery_claim_timeout_seconds,
            ) from error
    return _run_async(_run_delivery())


def active_report_prompt_identity() -> tuple[str, str]:
    bundle = resolve_active_bundle("report.full")
    return bundle.bundle_version, bundle.aggregate_hash


async def _process_full_report(
    user_id: str,
    birth_date: str,
    report_token: str,
    prompt_bundle_version: str | None = None,
    prompt_bundle_hash: str | None = None,
) -> dict:
    uid = uuid.UUID(user_id)
    session_factory = get_async_sessionmaker()
    report_repo = ReportRepository(session_factory)
    user_repo = UserRepository(session_factory)

    user = await user_repo.get(uid)
    user_name = user.first_name or user.username or "пользователь" if user else "пользователь"

    matrix = MatrixService.calculate(birth_date)
    from asyncio import gather
    from core.loop_specs.report_loop import generate_governed_full_report_with_loop

    bundle = (
        prompt_registry.resolve("report.full", prompt_bundle_version)
        if prompt_bundle_version is not None
        else resolve_active_bundle("report.full")
    )
    if prompt_bundle_hash is not None and bundle.aggregate_hash != prompt_bundle_hash:
        raise RuntimeError("report_prompt_pin_mismatch")
    prompt_pin = bundle.pin("report.full")
    prompt_pin["requested_model"] = settings.deepseek_model
    analysis_task = generate_governed_full_report_with_loop(
        birth_date,
        matrix,
        name=user_name,
        bundle=bundle,
    )
    kitchen_task = AIService.generate_kitchen_report_with_metadata(
        birth_date, matrix, bundle=bundle
    )
    analysis_result, kitchen_result = await gather(analysis_task, kitchen_task)
    analysis = dict(analysis_result.content)
    kitchen_analysis = dict(kitchen_result.content)
    token = report_token or ReportService.generate_token()

    archetype_name = MatrixService.get_archetype_name(matrix.center)

    matrix_dict = matrix.model_dump()
    generation_metadata = finalize_generation_metadata(
        prompt_pin,
        provider=analysis_result.provider,
        model=analysis_result.model,
        generation_source=analysis_result.generation_source,
        structured_input_hash=input_hash(matrix_dict),
        components={
            "full_report": {
                "provider": analysis_result.provider,
                "model": analysis_result.model,
                "generation_source": analysis_result.generation_source,
            },
            "kitchen_report": {
                "provider": kitchen_result.provider,
                "model": kitchen_result.model,
                "generation_source": kitchen_result.generation_source,
            },
        },
    )

    report_data = ReportService._build_v2_report_data(
        matrix_data=matrix_dict,
        analysis=analysis,
        kitchen_analysis=kitchen_analysis,
        generation_metadata=generation_metadata,
        user_name=user_name,
        archetype_number=matrix.center,
        archetype_name=archetype_name,
        token=token,
    )
    html = ReportService.generate_html_report(report_data, template_name="full_report_v2.html")
    pdf = await ReportService.generate_pdf(html)
    paths = ReportService.save_report_files(token, html, pdf)

    existing = await report_repo.get_by_user_id_and_type(uid, ReportType.FULL)
    if existing is not None:
        await report_repo.delete(existing.id)

    report = await report_repo.create(
        user_id=uid,
        report_type=ReportType.FULL,
        token=token,
        matrix_data=matrix_dict,
        ai_analysis=analysis,
        kitchen_analysis=kitchen_analysis,
        generation_metadata=generation_metadata,
    )

    return {
        "report_id": str(report.id),
        "token": token,
        "report_url": ReportService.report_url(token),
        "html_path": paths["html"],
        "pdf_path": paths["pdf"],
        "analysis": analysis,
    }


@celery_app.task(
    name="core.tasks.generate_full_report",
    autoretry_on=(SoftTimeLimitExceeded, TimeoutError, ConnectionError),
    max_retries=2,
    retry_backoff=30,
    retry_backoff_max=180,
    retry_jitter=True,
)
def generate_full_report(
    user_id: str,
    birth_date: str,
    report_token: str,
    prompt_bundle_version: str | None = None,
    prompt_bundle_hash: str | None = None,
) -> dict:
    async def _run_all():
        result = await _process_full_report(
            user_id,
            birth_date,
            report_token,
            prompt_bundle_version,
            prompt_bundle_hash,
        )
        telegram_id = await _get_user_telegram_id(user_id)
        if telegram_id:
            await _notify_full_report(telegram_id, result["token"])
        return result
    return _run_async(_run_all())


@celery_app.task(
    bind=True,
    name="core.tasks.process_report_generation_job",
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=3,
    default_retry_delay=30,
    task_time_limit=600,
    task_soft_time_limit=480,
)
def process_report_generation_job(self, job_id: str, report_id: str) -> dict:
    try:
        job_uuid = uuid.UUID(job_id)
        report_uuid = uuid.UUID(report_id)
    except (ValueError, AttributeError):
        return {"ok": False, "error": "invalid_task_arguments"}

    async def _run() -> dict:
        from core.database import get_async_sessionmaker
        from core.services.matrix_report_generator import DefaultMatrixReportGenerator
        from core.services.matrix_report_worker import (
            GenerationDisposition,
            MatrixReportGenerationWorker,
        )

        session_factory = get_async_sessionmaker()
        generator = DefaultMatrixReportGenerator()
        worker = MatrixReportGenerationWorker(session_factory, generator)
        result = await worker.process(job_id=job_uuid, report_id=report_uuid)

        if result.disposition == GenerationDisposition.COMPLETED:
            from core.services.full_report_telegram_delivery import FullReportTelegramDeliveryService
            delivery_id = await FullReportTelegramDeliveryService(session_factory).enqueue_automatic(report_uuid)
            if delivery_id is not None:
                deliver_full_report.delay(str(delivery_id))
            return {"ok": True, "disposition": "completed"}
        if result.disposition == GenerationDisposition.IDEMPOTENT_COMPLETED:
            return {"ok": True, "idempotent": True, "disposition": "idempotent_completed"}
        if result.disposition == GenerationDisposition.RETRYABLE_FAILURE:
            return {"ok": False, "retryable": True, "error_category": result.error_category}
        return {"ok": False, "terminal": True, "error_category": result.error_category}

    return _run_async(_run())


@celery_app.task(
    bind=True, name="core.tasks.deliver_full_report", acks_late=True,
    reject_on_worker_lost=True, max_retries=3, default_retry_delay=30,
)
def deliver_full_report(self, delivery_id: str, claimed_attempt: int | None = None) -> None:
    try:
        parsed_id = uuid.UUID(delivery_id)
    except (ValueError, AttributeError):
        return

    async def _run() -> None:
        from core.database import get_async_sessionmaker
        from core.services.full_report_telegram_delivery import FullReportTelegramDeliveryService
        from core.services.telegram_report_delivery import TelegramDeliveryError

        try:
            await FullReportTelegramDeliveryService(
                get_async_sessionmaker()
            ).deliver(parsed_id, claimed_attempt=claimed_attempt)
        except TelegramDeliveryError as error:
            if error.retryable:
                countdown = min(max(error.retry_after or 20, 1), 300)
                raise self.retry(
                    exc=ConnectionError(error.code),
                    countdown=countdown,
                    args=(delivery_id,),
                    kwargs={},
                ) from error
        except OperationalError as error:
            raise self.retry(
                exc=ConnectionError("delivery_database_unavailable"),
                countdown=settings.telegram_delivery_claim_timeout_seconds,
            ) from error

    _run_async(_run())


@celery_app.task(
    bind=True, name="core.tasks.deliver_chat_response", acks_late=True,
    reject_on_worker_lost=True, max_retries=3, default_retry_delay=30,
)
def deliver_chat_response(self, usage_id: str) -> None:
    """Continue a persisted Telegram chat delivery after a transient failure."""
    try:
        parsed_id = uuid.UUID(usage_id)
    except (ValueError, AttributeError):
        return

    async def _run() -> None:
        from core.services.chat_quota import ChatQuotaService
        from core.services.chat_telegram_delivery import TelegramChatDeliveryService

        result = await TelegramChatDeliveryService(
            ChatQuotaService(get_async_sessionmaker())
        ).deliver(parsed_id)
        if result.retryable:
            raise self.retry(
                exc=ConnectionError("telegram_chat_delivery_retryable"),
                countdown=30,
                args=(usage_id,), kwargs={},
            )

    _run_async(_run())


@celery_app.task(name="core.tasks.reconcile_chat_deliveries", acks_late=False)
def reconcile_chat_deliveries(limit: int = 20) -> dict:
    if limit <= 0 or limit > 100:
        return {"ok": False, "error": "invalid_limit"}

    async def _run() -> dict:
        from core.services.chat_quota import ChatQuotaService

        selected = await ChatQuotaService(get_async_sessionmaker()).list_reconcilable_telegram_delivery_ids(
            limit=limit
        )
        dispatched = 0
        errors = 0
        for usage_id in selected:
            try:
                deliver_chat_response.delay(str(usage_id))
                dispatched += 1
            except Exception:
                errors += 1
        return {"selected": len(selected), "dispatched": dispatched, "errors": errors}

    return _run_async(_run())


@celery_app.task(
    name="core.tasks.dispatch_report_generation_jobs",
    acks_late=False,
    reject_on_worker_lost=True,
    task_time_limit=120,
    task_soft_time_limit=90,
)
def dispatch_report_generation_jobs(limit: int = 20) -> dict:
    if limit <= 0 or limit > 100:
        return {"ok": False, "error": "invalid_limit"}

    async def _run() -> dict:
        from core.services.celery_publisher import build_dispatcher
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        dispatcher = build_dispatcher()
        result = await dispatcher.dispatch_batch(now=now, limit=limit)
        return {
            "selected": result.selected,
            "claimed": result.claimed,
            "published": result.published,
            "retryable_failed": result.retryable_failed,
            "terminal_failed": result.terminal_failed,
            "claim_conflicts": result.claim_conflicts,
        }

    return _run_async(_run())


@celery_app.task(
    name="core.tasks.reconcile_report_generation_jobs",
    acks_late=False,
    reject_on_worker_lost=True,
    task_time_limit=180,
    task_soft_time_limit=150,
)
def reconcile_report_generation_jobs(limit: int = 50) -> dict:
    if limit <= 0 or limit > 200:
        return {"ok": False, "error": "invalid_limit"}

    async def _run() -> dict:
        from core.services.report_generation_reconciliation import (
            build_report_generation_reconciler,
        )
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        reconciler = build_report_generation_reconciler()
        result = await reconciler.reconcile_batch(now=now, limit=limit)
        return {
            "inspected": result.inspected,
            "dispatch_claims_recovered": result.dispatch_claims_recovered,
            "queued_recovered": result.queued_recovered,
            "running_recovered": result.running_recovered,
            "retries_promoted": result.retries_promoted,
            "terminalized": result.terminalized,
            "missing_jobs_repaired": result.missing_jobs_repaired,
            "completed_pairs_repaired": result.completed_pairs_repaired,
            "full_deliveries_created": result.full_deliveries_created,
            "full_deliveries_canceled": result.full_deliveries_canceled,
            "full_deliveries_claimed": result.full_deliveries_claimed,
            "full_deliveries_dispatched": result.full_deliveries_dispatched,
            "conflicts": result.conflicts,
            "errors": result.errors,
        }

    return _run_async(_run())


@celery_app.task(name="core.tasks.generate_compatibility_report")
def generate_compatibility_report(user_id: str, partner_date: str, partner_name: str = "Партнёр", relation_type: str = "общение") -> dict:
    async def _run_all():
        result = await _process_compatibility_report(user_id, partner_date, partner_name, relation_type)
        return result
    return _run_async(_run_all())


async def _process_compatibility_report(
    user_id: str, partner_date: str, partner_name: str = "Партнёр", relation_type: str = "общение"
) -> dict:
    uid = uuid.UUID(user_id)
    session_factory = get_async_sessionmaker()
    report_repo = ReportRepository(session_factory)
    user_repo = UserRepository(session_factory)

    user = await user_repo.get(uid)
    if user is None or not user.birth_date:
        raise ValueError(f"User {user_id} has no birth_date set")
    user_date = user.birth_date

    user_name = user.first_name or user.username or "пользователь"

    matrix1 = MatrixService.calculate(user_date)
    matrix2 = MatrixService.calculate(partner_date)
    analysis = await AIService.generate_compatibility(
        user_date, matrix1, partner_date, matrix2,
        user_name=user_name,
        partner_name=partner_name,
        relation_type=relation_type,
    )
    token = ReportService.generate_token()
    archetype_first_name = MatrixService.get_archetype_name(matrix1.center)
    archetype_second_name = MatrixService.get_archetype_name(matrix2.center)

    matrix_raw_1 = {
        "center": matrix1.center,
        "top": matrix1.top,
        "bottom": matrix1.bottom,
        "left": matrix1.left,
        "right": matrix1.right,
        "talent_zone": matrix1.talent_zone,
        "comfort_zone": matrix1.comfort_zone,
        "portrait_zone": matrix1.portrait_zone,
        "karmic_tail": matrix1.karmic_tail,
    }
    matrix_raw_2 = {
        "center": matrix2.center,
        "top": matrix2.top,
        "bottom": matrix2.bottom,
        "left": matrix2.left,
        "right": matrix2.right,
        "talent_zone": matrix2.talent_zone,
        "comfort_zone": matrix2.comfort_zone,
        "portrait_zone": matrix2.portrait_zone,
        "karmic_tail": matrix2.karmic_tail,
    }

    html = ReportService.generate_html_report(
        report_data={
            "matrix": matrix_raw_1,
            "matrix_second": matrix_raw_2,
            "analysis": analysis,
            "user_name": user_name,
            "partner_name": partner_name,
            "relation_type": relation_type,
            "archetype_name": archetype_first_name,
            "archetype_number": matrix1.center,
            "archetype_first_name": archetype_first_name,
            "archetype_first_number": matrix1.center,
            "archetype_second_name": archetype_second_name,
            "archetype_second_number": matrix2.center,
        },
        template_name="compatibility_report.html",
    )
    pdf = await ReportService.generate_pdf(html) if relation_type == "романтика" else None
    paths = ReportService.save_report_files(token, html, pdf)

    existing = await report_repo.get_by_user_id_and_type(uid, ReportType.COMPATIBILITY)
    if existing is not None:
        await report_repo.delete(existing.id)

    report = await report_repo.create(
        user_id=uid,
        report_type=ReportType.COMPATIBILITY,
        token=token,
        matrix_data={
            "matrix1": matrix1.model_dump(),
            "matrix2": matrix2.model_dump(),
            "partner_name": partner_name,
        },
        ai_analysis=analysis,
    )

    return {
        "report_id": str(report.id),
        "token": token,
        "analysis": analysis,
        "report_url": ReportService.report_url(token),
        "html_path": paths["html"],
        "pdf_path": paths["pdf"],
        "archetype_first_name": archetype_first_name,
        "archetype_first_number": matrix1.center,
        "archetype_second_name": archetype_second_name,
        "archetype_second_number": matrix2.center,
        "relation_type": relation_type,
    }


async def _notify_user(
    user: User,
    text: str,
    keyboard: dict | None = None,
    push_title: str = "NURA",
    push_body: str = "",
    push_url: str = "/app/tarot",
    push_tag: str = "daily-card",
) -> bool:
    push_ok = False
    telegram_ok = False

    if user.has_pwa_push and user.push_endpoint:
        try:
            push_ok = await send_web_push(
                endpoint=user.push_endpoint,
                p256dh=user.push_p256dh,
                auth=user.push_auth,
                title=push_title,
                body=push_body or text[:100],
                url=push_url,
                tag=push_tag,
            )
        except PushSubscriptionExpired:
            logger.info(
                "Clearing expired push subscription for user %s", user.id
            )
            session_factory = get_async_sessionmaker()
            user_repo = UserRepository(session_factory)
            try:
                await user_repo.update_push_subscription(
                    user_id=user.id,
                    endpoint=None,
                    p256dh=None,
                    auth=None,
                    has_pwa_push=False,
                )
            except Exception:
                logger.exception(
                    "Failed to clear push subscription for user %s", user.id
                )
        except Exception:
            logger.exception(
                "Push notification failed for user %s", user.id
            )

    if user.telegram_id:
        try:
            telegram_ok = await _send_message(user.telegram_id, text, keyboard)
        except Exception:
            logger.exception(
                "Telegram notification failed for user %s", user.id
            )

    return push_ok or telegram_ok


# Dormant legacy notification producers. Keep registered for a future migration,
# but do not schedule until notifications use DailyTarotApplicationService.
@celery_app.task(name="core.tasks.send_daily_card")
def send_daily_card() -> dict:
    return _run_async(_send_daily_card_async())


# Cache daily-card AI text by arcana number so each archetype calls AI once
ARCANE_CACHE: dict[tuple[date, int], str] = {}

# Cache daily-tarot-card AI text by (today, arcana_num) — same archetype shares cache
DAILY_CARD_CACHE: dict[tuple[date, int], str] = {}


async def _send_daily_card_async() -> dict:
    session_factory = get_async_sessionmaker()
    async with session_factory() as session:
        result = await session.execute(
            select(User)
            .options(
                load_only(
                    User.id,
                    User.telegram_id,
                    User.first_name,
                    User.username,
                    User.birth_date,
                    User.main_archetype_number,
                    User.main_archetype,
                    User.has_pwa_push,
                    User.push_endpoint,
                    User.push_p256dh,
                    User.push_auth,
                )
            )
            .where(
                User.subscription_status.in_(["free", "premium", "active"])
            )
        )
        users = result.scalars().all()

    today = datetime.now(MSK).date()
    send_semaphore = asyncio.Semaphore(5)
    sent = 0
    failed = 0

    async def _send_one(user: User) -> bool:
        nonlocal sent, failed
        arcana_num = user.main_archetype_number or 0
        daily_arcana = (
            _personal_arcana_number(today, arcana_num)
            if arcana_num
            else _daily_arcana_number(today)
        )
        arcana_name = ARCANA.get(daily_arcana, f"Аркан {daily_arcana}")

        # Cache AI-generated card text by daily arcana number
        if (today, daily_arcana) not in ARCANE_CACHE:
            user_name = user.first_name or user.username or "друг"
            try:
                card_text = await AIService().generate_tarot_daily_card(
                    arcana_number=daily_arcana,
                    arcana_name=arcana_name,
                    date_str=today.strftime("%d.%m.%Y"),
                    user_name=user_name,
                    user_archetype_number=arcana_num or daily_arcana,
                    user_archetype_name=user.main_archetype or arcana_name,
                )
                ARCANE_CACHE[(today, daily_arcana)] = card_text
            except Exception:
                logger.exception(
                    "Daily card AI failed for arcana %s, using fallback",
                    daily_arcana,
                )
                ARCANE_CACHE[(today, daily_arcana)] = (
                    f"🌒 Карта дня — {arcana_name} ({daily_arcana})\n\n"
                    f"{FALLBACK_TAROT_DAILY['interpretation']}"
                )

        cached = ARCANE_CACHE[(today, daily_arcana)]
        user_name = user.first_name or user.username or "друг"
        text = f"🌒 {user_name}, твоя карта дня\n\n{cached}"

        async with send_semaphore:
            try:
                ok = await _notify_user(
                    user,
                    text,
                    push_title="🌒 Карта дня",
                    push_body=cached[:120],
                    push_url="/app/tarot",
                    push_tag="daily-card",
                )
                if ok:
                    sent += 1
                else:
                    failed += 1
                return ok
            except Exception:
                logger.exception("Failed to notify user %s in daily card task", user.id)
                failed += 1
                return False

    stale_keys = [k for k in ARCANE_CACHE if k[0] != today]
    for k in stale_keys:
        ARCANE_CACHE.pop(k, None)

    await asyncio.gather(*[_send_one(u) for u in users])
    logger.info("send_daily_card: sent=%d failed=%d total=%d", sent, failed, len(users))
    return {"sent": sent, "failed": failed, "total": len(users)}


@celery_app.task(name="core.tasks.send_daily_tarot_card")
def send_daily_tarot_card() -> dict:
    return _run_async(_send_daily_tarot_card_async())


async def _send_daily_tarot_card_async() -> dict:
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    users = await user_repo.get_users_with_tarot()

    today = datetime.now(MSK).date()
    send_semaphore = asyncio.Semaphore(5)
    sent = 0
    failed = 0

    async def _send_one(user: User) -> bool:
        nonlocal sent, failed
        center_arcana = user.main_archetype_number or 0
        arcana_num = (
            _personal_arcana_number(today, center_arcana)
            if center_arcana else _daily_arcana_number(today)
        )
        arcana_name = ARCANA[arcana_num]
        user_name = user.first_name or user.username or "друг"

        if (today, arcana_num) not in DAILY_CARD_CACHE:
            try:
                card_text = await AIService().generate_tarot_daily_card(
                    arcana_number=arcana_num,
                    arcana_name=arcana_name,
                    date_str=today.strftime("%d.%m.%Y"),
                    user_name=user_name,
                    user_archetype_number=user.main_archetype_number or arcana_num,
                    user_archetype_name=user.main_archetype or arcana_name,
                )
                DAILY_CARD_CACHE[(today, arcana_num)] = card_text
            except Exception:
                logger.exception(
                    "Daily tarot card AI failed for arcana %s, using fallback",
                    arcana_num,
                )
                DAILY_CARD_CACHE[(today, arcana_num)] = (
                    f"🌒 Карта дня — {arcana_name} ({arcana_num})\n\n"
                    f"{FALLBACK_TAROT_DAILY['interpretation']}"
                )
                failed += 1

        card_text = DAILY_CARD_CACHE[(today, arcana_num)]

        text = (
            f"🌒 <b>Карта дня для {user_name}</b>\n"
            f"<i>{today.strftime('%d.%m.%Y')}</i>\n"
            f"{'─' * 20}\n\n"
            f"{card_text}"
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "✦ Расклад недели", "callback_data": "tarot_weekly"}],
                [{"text": "🏠 В меню", "callback_data": "main_menu"}],
            ],
        }

        async with send_semaphore:
            try:
                ok = await _notify_user(
                    user,
                    text,
                    keyboard,
                    push_title="🌒 Карта дня",
                    push_body=f"Карта дня для {user_name}",
                    push_url="/app/tarot",
                    push_tag="daily-tarot-card",
                )
                if ok:
                    sent += 1
                else:
                    failed += 1
                return ok
            except Exception:
                logger.exception(
                    "Failed to notify user %s in daily tarot card task", user.id
                )
                failed += 1
                return False

    stale_keys = [k for k in DAILY_CARD_CACHE if k[0] != today]
    for k in stale_keys:
        DAILY_CARD_CACHE.pop(k, None)

    await asyncio.gather(*[_send_one(u) for u in users])
    logger.info(
        "send_daily_tarot_card: sent=%d failed=%d total=%d",
        sent, failed, len(users),
    )
    return {"sent": sent, "failed": failed, "total": len(users)}


@celery_app.task(name="core.tasks.send_weekly_tarot_spread")
def send_weekly_tarot_spread() -> dict:
    return _run_async(_send_weekly_tarot_spread_async())


async def _send_weekly_tarot_spread_async() -> dict:
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    users = await user_repo.get_users_with_tarot()
    today = datetime.now(MSK).date()

    prompt = AIService._load_prompt("tarot_weekly_spread.txt")
    send_semaphore = asyncio.Semaphore(3)
    sent = 0
    failed = 0

    async def _send_one(user: User) -> bool:
        nonlocal sent, failed
        if not user.birth_date:
            failed += 1
            return False
        center_arcana = user.main_archetype_number or 0
        arcana_num = (
            _personal_arcana_number(today, center_arcana)
            if center_arcana else _daily_arcana_number(today)
        )
        three_arcana = [(arcana_num + i * 7) % 22 + 1 for i in range(3)]
        user_name = user.first_name or user.username or "друг"

        matrix_context = ""
        if user.main_archetype:
            matrix_context = f"Центральный архетип: {user.main_archetype} ({center_arcana})"
        filled = prompt.format(
            user_name=user_name,
            birth_date=user.birth_date,
            three_arcana=three_arcana,
            matrix_context=matrix_context or "(нет данных матрицы)",
        )
        try:
            from core.loop_specs.tarot_loop import generate_tarot_text

            card_text = await generate_tarot_text(
                messages=[
                    {"role": "system", "content": "Ты — NURA, персональный психологический проводник."},
                    {"role": "user", "content": filled},
                ],
                api_params={"max_tokens": 600, "temperature": 0.7},
                use_cache=True,
                cache_ttl=7 * 86400,
            )
        except Exception:
            logger.exception("Weekly spread AI failed for user %s", user.id)
            failed += 1
            return False

        text = (
            f"✦ <b>Расклад недели для {user_name}</b>\n"
            f"<i>{today.strftime('%d.%m.%Y')} — понедельник</i>\n"
            f"{'─' * 20}\n\n"
            f"{card_text}"
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "🌒 Карта дня", "callback_data": "tarot_daily"}],
                [{"text": "🏠 В меню", "callback_data": "main_menu"}],
            ],
        }
        async with send_semaphore:
            try:
                ok = await _notify_user(
                    user, text, keyboard,
                    push_title="✦ Расклад недели",
                    push_body=f"Твой расклад на неделю готов, {user_name}",
                    push_url="/app/tarot",
                    push_tag="weekly-spread",
                )
                if ok:
                    sent += 1
                else:
                    failed += 1
                return ok
            except Exception:
                logger.exception("Failed to notify user %s in weekly spread task", user.id)
                failed += 1
                return False

    await asyncio.gather(*[_send_one(u) for u in users])
    logger.info("send_weekly_tarot_spread: sent=%d failed=%d total=%d", sent, failed, len(users))
    return {"sent": sent, "failed": failed, "total": len(users)}


@celery_app.task(name="core.tasks.send_monthly_tarot_portal")
def send_monthly_tarot_portal() -> dict:
    return _run_async(_send_monthly_tarot_portal_async())


async def _send_monthly_tarot_portal_async() -> dict:
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    users = await user_repo.get_users_with_tarot()
    now = datetime.now(MSK)
    month_num = now.month
    month_names = {1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь",
                   7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"}
    month_name = month_names[month_num]

    prompt = AIService._load_prompt("tarot_portal.txt")
    send_semaphore = asyncio.Semaphore(3)
    sent = 0
    failed = 0

    async def _send_one(user: User) -> bool:
        nonlocal sent, failed
        teach = (month_num * 3) % 22 + 1
        release = (month_num * 7) % 22 + 1
        strengthen = (month_num * 11) % 22 + 1
        from core.arcana_data import ARCANA
        t_name = ARCANA.get(teach, f"Аркан {teach}")
        r_name = ARCANA.get(release, f"Аркан {release}")
        s_name = ARCANA.get(strengthen, f"Аркан {strengthen}")

        filled = prompt.format(
            month_name=month_name,
            teach_arcana_number=teach,
            teach_arcana_name=t_name if isinstance(t_name, str) else t_name.get("name", f"Аркан {teach}"),
            release_arcana_number=release,
            release_arcana_name=r_name if isinstance(r_name, str) else r_name.get("name", f"Аркан {release}"),
            strengthen_arcana_number=strengthen,
            strengthen_arcana_name=s_name if isinstance(s_name, str) else s_name.get("name", f"Аркан {strengthen}"),
        )
        try:
            from core.loop_specs.tarot_loop import generate_tarot_text

            card_text = await generate_tarot_text(
                messages=[
                    {"role": "system", "content": "Ты — NURA, персональный психологический проводник."},
                    {"role": "user", "content": filled},
                ],
                api_params={"max_tokens": 500, "temperature": 0.7},
                use_cache=True,
                cache_ttl=31 * 86400,
            )
        except Exception:
            logger.exception("Monthly portal AI failed for user %s", user.id)
            failed += 1
            return False

        user_name = user.first_name or user.username or "друг"
        text = (
            f"🌅 <b>Портал месяца для {user_name}</b>\n"
            f"<i>{month_name}</i>\n"
            f"{'─' * 20}\n\n"
            f"{card_text}"
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "✦ Расклад недели", "callback_data": "tarot_weekly"}],
                [{"text": "🏠 В меню", "callback_data": "main_menu"}],
            ],
        }
        async with send_semaphore:
            try:
                ok = await _notify_user(
                    user, text, keyboard,
                    push_title=f"🌅 Портал {month_name}",
                    push_body=f"Твой портал месяца — {month_name}",
                    push_url="/app/tarot",
                    push_tag="monthly-portal",
                )
                if ok:
                    sent += 1
                else:
                    failed += 1
                return ok
            except Exception:
                logger.exception("Failed to notify user %s in monthly portal task", user.id)
                failed += 1
                return False

    await asyncio.gather(*[_send_one(u) for u in users])
    logger.info("send_monthly_tarot_portal: sent=%d failed=%d total=%d", sent, failed, len(users))
    return {"sent": sent, "failed": failed, "total": len(users)}


@celery_app.task(name="core.tasks.check_inactive_users")
def check_inactive_users() -> dict:
    return _run_async(_check_inactive_users_async())


async def _check_inactive_users_async() -> dict:
    session_factory = get_async_sessionmaker()
    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)

    async with session_factory() as session:
        result = await session.execute(
            select(User).where(
                User.tarot_subscription.is_(True),
                User.created_at < seven_days_ago,
            )
        )
        users = result.scalars().all()

    notified = 0
    for user in users:
        user_name = user.first_name or user.username or "друг"
        text = (
            f"🌒 {user_name}, мы соскучились!\n\n"
            f"Твоя карта дня ждёт тебя в боте. "
            f"Один взгляд — и ты будешь знать, "
            f"в каком режиме прожить сегодняшний день.\n\n"
            f"Загляни — это занимает меньше минуты."
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "🌒 Карта дня", "callback_data": "tarot_daily"}],
                [{"text": "🏠 В меню", "callback_data": "main_menu"}],
            ],
        }
        ok = await _notify_user(
            user, text, keyboard,
            push_title="🌒 Давно не виделись",
            push_body=f"{user_name}, твоя карта дня ждёт",
            push_url="/app/tarot",
            push_tag="re-engagement",
        )
        if ok:
            notified += 1

    logger.info("check_inactive_users: notified=%d total_inactive=%d", notified, len(users))
    return {"notified": notified, "total_inactive": len(users)}


@celery_app.task(name="core.tasks.check_expiring_subscriptions")
def check_expiring_subscriptions() -> dict:
    return _run_async(_check_expiring_subscriptions_async())


async def _check_expiring_subscriptions_async() -> dict:
    now = datetime.now(timezone.utc)
    three_days = now + timedelta(days=3)

    session_factory = get_async_sessionmaker()
    async with session_factory() as session:
        result = await session.execute(
            select(User).where(
                User.subscription_status == "premium",
                User.telegram_id.isnot(None),
                User.subscription_until <= three_days,
                User.subscription_until > now,
            )
        )
        users = result.scalars().all()

    notified = 0
    for user in users:
        if user.telegram_id is None:
            continue
        first_name = user.first_name or user.username or "пользователь"
        text = (
            f"🌒 NURA\n\n"
            f"{first_name}, твоя подписка истекает через 3 дня.\n\n"
            "После этого ты потеряешь доступ к чату с NURA, "
            "ежедневным инсайтам и новым отчётам.\n\n"
            "Продли сейчас, чтобы ничего не прерывать."
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "💎 Продлить подписку", "callback_data": "buy_subscription"}],
                [{"text": "🏠 В меню", "callback_data": "main_menu"}],
            ],
        }
        ok = await _send_message(user.telegram_id, text, keyboard)
        if ok:
            notified += 1

    return {"notified": notified, "total_expiring": len(users)}


@celery_app.task(name="core.tasks.downgrade_expired_subscriptions")
def downgrade_expired_subscriptions() -> dict:
    return _run_async(_downgrade_expired_subscriptions_async())


async def _downgrade_expired_subscriptions_async() -> dict:
    now = datetime.now(timezone.utc)

    session_factory = get_async_sessionmaker()
    async with session_factory() as session:
        result = await session.execute(
            select(User).where(
                User.subscription_status == "premium",
                User.subscription_until < now,
            )
        )
        users = result.scalars().all()

        downgraded = 0
        for user in users:
            user.subscription_status = "free"
            downgraded += 1
        await session.commit()

    return {"downgraded": downgraded, "total_expired": len(users)}


@celery_app.task(name="core.tasks.charge_recurring_subscriptions")
def charge_recurring_subscriptions() -> dict:
    if not settings.payments_enabled:
        logger.warning("recurring payments are disabled for the Telegram pilot")
        return {"charged": 0, "failed": 0, "total": 0, "disabled": True}
    return _run_async(_charge_recurring_subscriptions_async())


async def _charge_recurring_subscriptions_async() -> dict:
    from core.services.payment import PaymentService
    from core.repositories.payment import PaymentRepository

    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    payment_repo = PaymentRepository(session_factory)
    users = await user_repo.get_users_for_recurring_charge()

    now = datetime.now(timezone.utc)
    charged = 0
    failed = 0

    for user in users:
        is_tarot = (
            user.tarot_subscription
            and user.tarot_subscription_until
            and user.tarot_subscription_until <= now + timedelta(hours=24)
        )
        is_premium = (
            user.subscription_status == "premium"
            and user.subscription_until
            and user.subscription_until <= now + timedelta(hours=24)
        )

        if is_tarot and user.payment_method_id:
            try:
                result = await PaymentService.create_recurring_payment(
                    payment_method_id=user.payment_method_id,
                    amount_rub=settings.tarot_subscription_price_rub,
                    description="NURA — Таро-ритуалы (продление)",
                    metadata={
                        "user_id": str(user.id),
                        "payment_type": "tarot",
                        "recurring": "true",
                    },
                )
                await payment_repo.create(
                    user_id=user.id,
                    amount=settings.tarot_subscription_price_rub,
                    yookassa_id=result["id"],
                    payment_type="tarot",
                )
                until = now + timedelta(days=30)
                await user_repo.update_tarot_subscription(user.id, True, until)
                charged += 1
                logger.info(
                    "recurring: charged tarot for user %s, payment %s",
                    user.id, result["id"],
                )
            except Exception:
                logger.exception(
                    "recurring: failed to charge tarot for user %s", user.id
                )
                failed += 1

        elif is_premium and user.payment_method_id:
            try:
                result = await PaymentService.create_recurring_payment(
                    payment_method_id=user.payment_method_id,
                    amount_rub=settings.tarot_subscription_price_rub,
                    description="NURA — Ежедневные инсайты (продление)",
                    metadata={
                        "telegram_id": user.telegram_id,
                        "payment_type": "subscription",
                        "recurring": "true",
                    },
                )
                await payment_repo.create(
                    user_id=user.id,
                    amount=settings.tarot_subscription_price_rub,
                    yookassa_id=result["id"],
                    payment_type="subscription",
                )
                until = now + timedelta(days=30)
                await user_repo.update_subscription(user.id, "premium", until)
                charged += 1
                logger.info(
                    "recurring: charged premium for user %s, payment %s",
                    user.id, result["id"],
                )
            except Exception:
                logger.exception(
                    "recurring: failed to charge premium for user %s", user.id
                )
                failed += 1

    if failed > 0:
        admin_id = settings.admin_telegram_id
        if admin_id:
            await _send_message(
                admin_id,
                f"⚠️ Recurring charge: {failed} failed out of {len(users)} users",
            )

    logger.info(
        "charge_recurring_subscriptions: charged=%d failed=%d total=%d",
        charged, failed, len(users),
    )
    return {"charged": charged, "failed": failed, "total": len(users)}


@celery_app.task(name="core.tasks.send_broadcast", bind=True)
def send_broadcast(self, text: str, channels: list[str], filter_type: str,
                   push_title: str | None = None, push_url: str | None = None):
    return _run_async(_send_broadcast_async(
        self.request.id, text, channels, filter_type, push_title, push_url
    ))


async def _send_broadcast_async(
    task_id: str,
    text: str,
    channels: list[str],
    filter_type: str,
    push_title: str | None,
    push_url: str | None,
) -> dict:
    redis = get_redis()
    del text, channels, filter_type, push_title, push_url
    result = {
        "status": "deprecated",
        "sent": 0,
        "total": 0,
        "failed": 0,
        "error_code": "direct_broadcast_disabled",
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    await redis.set(f"broadcast:{task_id}", json.dumps(result))
    return result


@celery_app.task(name="core.tasks.dispatch_broadcast_campaign")
def dispatch_broadcast_campaign(campaign_id: str) -> dict:
    return _run_async(_dispatch_broadcast_campaign_async(campaign_id))


async def _dispatch_broadcast_campaign_async(campaign_id: str) -> dict:
    from core.services.broadcast import BroadcastCampaignService

    return await BroadcastCampaignService(
        get_async_sessionmaker()
    ).dispatch_campaign(uuid.UUID(campaign_id))


@celery_app.task(name="core.tasks.reconcile_broadcast_campaigns")
def reconcile_broadcast_campaigns(limit: int = 20) -> dict:
    return _run_async(_reconcile_broadcast_campaigns_async(limit))


async def _reconcile_broadcast_campaigns_async(limit: int) -> dict:
    from core.services.broadcast import BroadcastCampaignService

    return await BroadcastCampaignService(get_async_sessionmaker()).reconcile(limit=limit)


@celery_app.task(
    name="core.tasks.send_magic_link_email",
    bind=True,
    max_retries=3,
    autoretry_on=(Exception,),
    retry_backoff=30,
    retry_backoff_max=180,
)
def send_magic_link_email(self, email: str, token: str) -> dict:
    link = f"{settings.report_base_url}/api/v1/auth/email/verify?token={token}"
    if not settings.smtp_password:
        logger.warning("smtp password unset, skipping magic link email to %s", email)
        return {"ok": True, "skipped_no_key": True}

    async def _send() -> dict:
        import aiosmtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        ttl = settings.magic_link_ttl_minutes
        html_body = (
            '<!DOCTYPE html>'
            '<html><head><meta charset="utf-8"></head>'
            '<body style="margin:0;padding:0;background-color:#EFEEE9;">'
            '<table width="100%" cellpadding="0" cellspacing="0" role="presentation">'
            '<tr><td align="center" style="padding:40px 20px;">'
            '<table width="480" cellpadding="0" cellspacing="0" role="presentation"'
            ' style="background:#fff;border-radius:12px;overflow:hidden;">'
            '<tr><td style="padding:40px 40px 30px;text-align:center;">'
            '<h1 style="font:32px Georgia,serif;color:#1a1a1a;margin:0;letter-spacing:2px;">NURA</h1>'
            '</td></tr>'
            '<tr><td style="padding:0 40px 30px;font:16px/24px Arial,Helvetica,sans-serif;color:#333;">'
            '<p style="margin:0;">Нажмите кнопку, чтобы войти в NURA:</p>'
            '</td></tr>'
            '<tr><td align="center" style="padding:0 40px 30px;">'
            '<a href="' + link + '"'
            ' style="display:inline-block;background:#D45429;color:#fff;text-decoration:none;'
            'padding:14px 40px;border-radius:8px;font:16px Arial,Helvetica,sans-serif;'
            'font-weight:600;">Войти в NURA</a>'
            '</td></tr>'
            '<tr><td style="padding:0 40px 20px;font:14px/20px Arial,Helvetica,sans-serif;color:#777;">'
            '<p style="margin:0 0 8px;">Или откройте ссылку в браузере:</p>'
            '<p style="margin:0;"><a href="' + link + '"'
            ' style="color:#D45429;word-break:break-all;">' + link + '</a></p>'
            '<p style="margin:8px 0 0;">Ссылка действительна ' + str(ttl) + ' минут.</p>'
            '</td></tr>'
            '<tr><td style="padding:0 40px 30px;font:12px/18px Arial,Helvetica,sans-serif;color:#999;">'
            '<p style="margin:0;">Если вы не запрашивали вход, просто проигнорируйте это письмо.</p>'
            '</td></tr>'
            '</table></td></tr>'
            '<tr><td align="center" style="padding:20px;font:12px Arial,Helvetica,sans-serif;color:#bbb;">'
            'NURA &middot; <a href="https://nura-ai.ru" style="color:#bbb;">nura-ai.ru</a>'
            '</td></tr></table></body></html>'
        )
        text_body = (
            f"Вход в NURA\n\n"
            f"Нажмите кнопку, чтобы войти в NURA:\n{link}\n\n"
            f"Ссылка действительна {ttl} минут.\n\n"
            f"Если вы не запрашивали вход, просто проигнорируйте это письмо.\n\n"
            f"NURA — nura-ai.ru"
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Вход в NURA"
        msg["From"] = settings.smtp_from
        msg["To"] = email
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            use_tls=settings.smtp_secure,
        )
        return {"ok": True}

    masked = email[0] + "***@" + email.rsplit("@", 1)[-1] if "@" in email else email
    try:
        result = _run_async(_send())
        logger.info("magic link email sent to %s", masked)
        return result
    except Exception:
        logger.exception("failed to send magic link email to %s", masked)
        raise


@celery_app.task(name="core.tasks.cleanup_expired_guest_profiles")
def cleanup_expired_guest_profiles() -> dict:
    async def _run() -> dict:
        from core.services.auth import AuthService

        svc = AuthService()
        count = await svc.cleanup_expired_guests()
        return {"deleted": count}

    return _run_async(_run())


@celery_app.task(name="core.tasks.block_inactive_users")
def block_inactive_users() -> dict:
    async def _run() -> dict:
        session_factory = get_async_sessionmaker()
        user_repo = UserRepository(session_factory)
        threshold = datetime.now(timezone.utc) - timedelta(days=14)
        count = await user_repo.block_inactive_users(threshold)
        logger.info("block_inactive_users: blocked=%d", count)
        return {"blocked": count}

    return _run_async(_run())


@celery_app.task(name="core.tasks.delete_inactive_users")
def delete_inactive_users() -> dict:
    async def _run() -> dict:
        session_factory = get_async_sessionmaker()
        user_repo = UserRepository(session_factory)
        threshold = datetime.now(timezone.utc) - timedelta(days=30)
        count = await user_repo.delete_inactive_users(threshold)
        logger.info("delete_inactive_users: deleted=%d", count)
        return {"deleted": count}

    return _run_async(_run())


@celery_app.task(name="core.tasks.monitor_health")
def monitor_health() -> dict:
    return _run_async(_monitor_health_async())


def _russian_error(exc: Exception) -> str:
    msg = str(exc)
    if isinstance(exc, httpx.ConnectError):
        return "Не удалось подключиться — сервер не отвечает"
    if isinstance(exc, httpx.TimeoutException):
        return "Сервер не ответил вовремя (таймаут)"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP ошибка: {exc.response.status_code}"
    if isinstance(exc, ImportError):
        return f"Ошибка загрузки модуля: {msg}"
    if isinstance(exc, FileNotFoundError):
        return "Файл или ресурс не найден"
    return f"Ошибка: {msg}"


async def _monitor_health_async() -> dict:
    logger.info("Проверка здоровья сервера...")
    admin_id = settings.admin_telegram_id
    if not admin_id:
        logger.warning("ADMIN_TELEGRAM_ID не задан, пропускаю мониторинг")
        return {"skipped": True}

    issues: list[str] = []

    # 1. Check API health endpoint
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("http://api:8000/health")
            if resp.status_code != 200:
                issues.append(f"🔴 API-сервер вернул статус {resp.status_code}")
    except Exception as e:
        issues.append(f"🔴 API-сервер недоступен: {_russian_error(e)}")

    # 2. Docker container status
    try:
        from admin_bot.services.docker_client import DockerClient

        dc = DockerClient()
        containers = await dc.list_containers()
        for c in containers:
            if c["state"] != "running":
                issues.append(f"🔴 Контейнер <b>{c['name']}</b> — {c['status']}")
    except Exception as e:
        issues.append(f"🔴 Не удалось проверить Docker: {_russian_error(e)}")

    # 3. Scan recent logs for errors
    try:
        from admin_bot.services.docker_client import DockerClient
        from admin_bot.services.log_parser import LogParser

        dc = DockerClient()
        containers = await dc.list_containers()
        error_count = 0
        error_samples: list[str] = []
        for c in containers:
            if c["state"] != "running":
                continue
            lines = await dc.get_container_logs(c["name"], since_minutes=5, lines=200)
            errors = LogParser.extract_errors(lines, max_per_container=5)
            for err in errors:
                error_count += 1
                if len(error_samples) < 5:
                    error_samples.append(f"[{c['name']}] {err['line'][:200]}")

        if error_samples:
            issues.append(
                f"⚠️ Найдено {error_count} ошибок в логах за 5 мин:\n"
                + "\n".join(f"<code>{s}</code>" for s in error_samples)
            )
    except Exception as e:
        issues.append(f"⚠️ Не удалось проверить логи: {_russian_error(e)}")

    if not issues:
        logger.info("monitor_health: всё в порядке")
        return {"status": "ok"}

    alert_text = "⚠️ <b>NURA Health Alert</b>\n\n" + "\n\n".join(issues)

    try:
        await _send_admin_message(admin_id, alert_text)
        logger.info("monitor_health: alert sent to admin %s", admin_id)
    except Exception as e:
        logger.exception("Failed to send health alert: %s", e)

    return {"status": "alert", "issues": issues}


async def _send_admin_message(telegram_id: int, text: str) -> bool:
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.exceptions import TelegramForbiddenError

    token = settings.admin_bot_token
    if not token or token.startswith("change-me"):
        logger.warning("ADMIN_BOT_TOKEN not configured, skipping admin message")
        return False

    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await bot.send_message(chat_id=telegram_id, text=text)
        return True
    except TelegramForbiddenError:
        logger.warning("Admin bot blocked by user %s", telegram_id)
        return False
    except Exception:
        logger.exception("Failed to send admin message")
        return False
    finally:
        await bot.session.close()
