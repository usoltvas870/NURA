import asyncio
import json
import logging
import uuid

import httpx
from datetime import date, datetime, timedelta, timezone

from celery import Celery
from celery.exceptions import SoftTimeLimitExceeded
from celery.schedules import crontab
from sqlalchemy import select
from sqlalchemy.orm import load_only

from core.config import settings
from core.database import get_async_sessionmaker, get_redis
from core.models import ReportType, User
from core.repositories import ReportRepository, UserRepository
from bot.utils.arcana import _daily_arcana_number, _personal_arcana_number
from core.fallbacks import FALLBACK_TAROT_DAILY
from core.services.ai import AIService
from core.services.matrix import ARCANA, MatrixService
from core.services.report import ReportService
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
)

celery_app.conf.beat_schedule = {
    "send-daily-card": {
        "task": "core.tasks.send_daily_card",
        "schedule": crontab(hour=3, minute=0),
    },
    "send-daily-tarot-card": {
        "task": "core.tasks.send_daily_tarot_card",
        "schedule": crontab(hour=9, minute=15),
    },
    "send-weekly-tarot-spread": {
        "task": "core.tasks.send_weekly_tarot_spread",
        "schedule": crontab(hour=9, minute=0, day_of_week=1),
    },
    "send-monthly-tarot-portal": {
        "task": "core.tasks.send_monthly_tarot_portal",
        "schedule": crontab(hour=9, minute=0, day_of_month=1),
    },
    "check-inactive-users": {
        "task": "core.tasks.check_inactive_users",
        "schedule": 60 * 60 * 6,
    },
    "check-expiring-subscriptions": {
        "task": "core.tasks.check_expiring_subscriptions",
        "schedule": 60 * 60 * 12,
    },
    "downgrade-expired-subscriptions": {
        "task": "core.tasks.downgrade_expired_subscriptions",
        "schedule": 60 * 60 * 24,
    },
    "charge-recurring-subscriptions": {
        "task": "core.tasks.charge_recurring_subscriptions",
        "schedule": 60 * 60 * 6,
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
}


def _run_async(coro) -> dict:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


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


async def _process_mini_report(user_id: str, birth_date: str) -> dict:
    uid = uuid.UUID(user_id)
    session_factory = get_async_sessionmaker()
    report_repo = ReportRepository(session_factory)
    user_repo = UserRepository(session_factory)

    matrix = MatrixService.calculate(birth_date)
    analysis = await AIService.generate_mini_analysis(birth_date, matrix)
    token = ReportService.generate_token()
    archetype_name = MatrixService.get_archetype_name(matrix.center)

    existing = await report_repo.get_by_user_id_and_type(uid, ReportType.MINI)
    if existing is not None:
        await report_repo.delete(existing.id)

    report = await report_repo.create(
        user_id=uid,
        report_type=ReportType.MINI,
        token=token,
        matrix_data=matrix.model_dump(),
        ai_analysis=analysis,
    )

    await user_repo.update_archetype(
        user_id=uid,
        archetype=archetype_name,
        number=matrix.center,
    )

    return {
        "report_id": str(report.id),
        "token": token,
        "analysis": analysis,
        "archetype": {"name": archetype_name, "number": matrix.center},
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
        result = await _process_mini_report(user_id, birth_date)
        telegram_id = await _get_user_telegram_id(user_id)
        if telegram_id:
            await _notify_mini_report(telegram_id, result["token"])
        return result
    return _run_async(_run_all())


async def _process_full_report(
    user_id: str, birth_date: str, report_token: str
) -> dict:
    uid = uuid.UUID(user_id)
    session_factory = get_async_sessionmaker()
    report_repo = ReportRepository(session_factory)
    user_repo = UserRepository(session_factory)

    user = await user_repo.get(uid)
    user_name = user.first_name or user.username or "пользователь" if user else "пользователь"

    matrix = MatrixService.calculate(birth_date)
    from asyncio import gather
    from core.loop_specs.report_loop import generate_full_report_with_loop
    analysis_task = generate_full_report_with_loop(birth_date, matrix, name=user_name)
    kitchen_task = AIService.generate_kitchen_report(birth_date, matrix)
    analysis, kitchen_analysis = await gather(analysis_task, kitchen_task)
    token = report_token or ReportService.generate_token()

    archetype_name = MatrixService.get_archetype_name(matrix.center)

    matrix_dict = matrix.model_dump()

    report_data = ReportService._build_v2_report_data(
        matrix_data=matrix_dict,
        analysis=analysis,
        kitchen_analysis=kitchen_analysis,
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
def generate_full_report(user_id: str, birth_date: str, report_token: str) -> dict:
    async def _run_all():
        result = await _process_full_report(user_id, birth_date, report_token)
        telegram_id = await _get_user_telegram_id(user_id)
        if telegram_id:
            await _notify_full_report(telegram_id, result["token"])
        return result
    return _run_async(_run_all())


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
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.exceptions import TelegramForbiddenError

    redis = get_redis()
    session_factory = get_async_sessionmaker()

    async with session_factory() as session:
        stmt = select(User)
        if filter_type == "premium":
            stmt = stmt.where(User.subscription_status == "premium")
        elif filter_type == "free":
            stmt = stmt.where(User.subscription_status == "free")
        result = await session.execute(stmt)
        users = result.scalars().all()

    total = len(users)
    if total == 0:
        await redis.set(f"broadcast:{task_id}", json.dumps({
            "status": "completed", "sent": 0, "total": 0, "failed": 0,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }))
        return {"sent": 0, "total": 0, "failed": 0}

    await redis.set(f"broadcast:{task_id}", json.dumps({
        "status": "running", "sent": 0, "total": total, "failed": 0, "finished_at": None,
    }))

    send_telegram = "telegram" in channels
    send_push = "push" in channels

    bot = None
    if send_telegram and settings.telegram_bot_token:
        bot = Bot(
            token=settings.telegram_bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )

    send_semaphore = asyncio.Semaphore(5)
    failed = 0

    async def _send_one(user: User) -> bool:
        nonlocal failed
        tg_sent = False

        async with send_semaphore:
            if send_telegram and user.telegram_id and bot:
                try:
                    await bot.send_message(chat_id=user.telegram_id, text=text)
                    tg_sent = True
                except TelegramForbiddenError:
                    failed += 1
                    return False
                except Exception:
                    logger.exception("Broadcast TG failed for user %s", user.id)
                    failed += 1
                    return False

            if send_push and user.has_pwa_push and user.push_endpoint and user.push_p256dh and user.push_auth:
                try:
                    ok = await send_web_push(
                        endpoint=user.push_endpoint,
                        p256dh=user.push_p256dh,
                        auth=user.push_auth,
                        title=push_title or "NURA",
                        body=text[:200],
                        url=push_url or "/app",
                        tag="broadcast",
                    )
                    if not ok:
                        failed += 1
                        return False
                except PushSubscriptionExpired:
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
                        logger.exception("Failed to clear push sub for user %s", user.id)
                    failed += 1
                    return False
                except Exception:
                    logger.exception("Broadcast push failed for user %s", user.id)
                    failed += 1
                    return False

            if tg_sent or not send_telegram:
                return True
            return False

    try:
        await asyncio.gather(*[_send_one(u) for u in users])
    finally:
        if bot:
            await bot.session.close()

    sent = total - failed
    await redis.set(f"broadcast:{task_id}", json.dumps({
        "status": "completed",
        "sent": sent,
        "total": total,
        "failed": failed,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }))

    return {"sent": sent, "total": total, "failed": failed}


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
