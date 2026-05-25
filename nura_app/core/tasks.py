import asyncio
import logging
import random
import uuid
from datetime import date, datetime, timedelta, timezone

from celery import Celery
from celery.schedules import crontab
from sqlalchemy import select

from core.config import settings
from core.database import get_async_sessionmaker
from core.models import ReportType, User
from core.repositories import ReportRepository, UserRepository
from core.services.ai import AIService
from core.services.insights_data import INSIGHTS_BY_ARCHETYPE
from core.services.daily_arcana import get_today_arcana_with_name
from core.services.matrix import ARCANA, MatrixService
from core.services.report import ReportService

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
    task_time_limit=300,
    task_soft_time_limit=240,
)

celery_app.conf.beat_schedule = {
    "send-daily-insights": {
        "task": "core.tasks.send_daily_insights",
        "schedule": crontab(hour=9, minute=0),
    },
    "send-daily-tarot-card": {
        "task": "core.tasks.send_daily_tarot_card",
        "schedule": crontab(hour=9, minute=15),
    },
    "check-expiring-subscriptions": {
        "task": "core.tasks.check_expiring_subscriptions",
        "schedule": 60 * 60 * 12,
    },
    "downgrade-expired-subscriptions": {
        "task": "core.tasks.downgrade_expired_subscriptions",
        "schedule": 60 * 60 * 24,
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


async def _notify_compatibility(telegram_id: int, token: str) -> None:
    text = (
        "❤️ Разбор совместимости готов!\n\n"
        "Карта вашей совместимости ждёт тебя. "
        "Полный разбор покажет зоны конфликтов и сильные стороны пары."
    )
    keyboard = {
        "inline_keyboard": [
            [{"text": "💎 Подписка 390 ₽/мес", "callback_data": "buy_subscription"}],
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


@celery_app.task(name="core.tasks.generate_mini_report")
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

    matrix = MatrixService.calculate(birth_date)
    from asyncio import gather
    analysis_task = AIService.generate_full_report(birth_date, matrix)
    kitchen_task = AIService.generate_kitchen_report(birth_date, matrix)
    analysis, kitchen_analysis = await gather(analysis_task, kitchen_task)
    token = report_token or ReportService.generate_token()

    user = await user_repo.get(uid)
    user_name = user.first_name or user.username or "пользователь" if user else "пользователь"
    archetype_name = MatrixService.get_archetype_name(matrix.center)
    recommendations_parsed = ReportService.parse_recommendations(
        analysis.get("ai_recommendations", "")
    )

    psych_blocks = ReportService.parse_psych_blocks(
        analysis.get("psychological_blocks", ""),
        arcana_names=matrix.arcana_names,
    )

    chakra_data = MatrixService.calculate_chakras(matrix)

    matrix_raw = {
        "center": matrix.center,
        "top": matrix.top,
        "bottom": matrix.bottom,
        "left": matrix.left,
        "right": matrix.right,
        "talent_zone": matrix.talent_zone,
        "comfort_zone": matrix.comfort_zone,
        "portrait_zone": matrix.portrait_zone,
        "karmic_tail": matrix.karmic_tail,
        "sky_line": matrix.sky_line,
        "earth_line": matrix.earth_line,
        "relationship_line": matrix.relationship_line,
        "money_line": matrix.money_line,
        "relationship_point": matrix.relationship_point,
        "inner_f": matrix.inner_f,
        "inner_g": matrix.inner_g,
        "inner_h": matrix.inner_h,
        "inner_i": matrix.inner_i,
        "arcana_names": matrix.arcana_names,
        "chakra_map": chakra_data,
    }

    bd = date(*(int(x) for x in reversed(birth_date.split("."))))
    current_year = date.today().year

    html = ReportService.generate_html_report(
        report_data={
            "matrix": matrix_raw,
            "analysis": analysis,
            "kitchen_analysis": kitchen_analysis,
            "user_name": user_name,
            "archetype_name": archetype_name,
            "archetype_number": matrix.center,
            "recommendations_parsed": recommendations_parsed,
            "life_periods": MatrixService.calculate_life_periods(bd),
            "year_forecast": MatrixService.calculate_year_forecast(bd, current_year),
            "current_year_arcana": MatrixService.calculate_year_arcana(bd, current_year),
            "daily_tarot_arcana": get_today_arcana_with_name(birth_date, matrix.arcana_names),
            "chakra_data": chakra_data,
            "psych_blocks": psych_blocks,
        },
    )
    pdf = await ReportService.generate_pdf(html)
    paths = ReportService.save_report_files(token, html, pdf)

    existing = await report_repo.get_by_user_id_and_type(uid, ReportType.FULL)
    if existing is not None:
        await report_repo.delete(existing.id)

    matrix_dict = matrix.model_dump()
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


@celery_app.task(name="core.tasks.generate_full_report")
def generate_full_report(user_id: str, birth_date: str, report_token: str) -> dict:
    async def _run_all():
        result = await _process_full_report(user_id, birth_date, report_token)
        telegram_id = await _get_user_telegram_id(user_id)
        if telegram_id:
            await _notify_full_report(telegram_id, result["token"])
        return result
    return _run_async(_run_all())


@celery_app.task(name="core.tasks.generate_compatibility_report")
def generate_compatibility_report(user_id: str, partner_date: str) -> dict:
    async def _run_all():
        result = await _process_compatibility_report(user_id, partner_date)
        telegram_id = await _get_user_telegram_id(user_id)
        if telegram_id:
            await _notify_compatibility(telegram_id, result["token"])
        return result
    return _run_async(_run_all())


async def _process_compatibility_report(
    user_id: str, partner_date: str
) -> dict:
    uid = uuid.UUID(user_id)
    session_factory = get_async_sessionmaker()
    report_repo = ReportRepository(session_factory)
    user_repo = UserRepository(session_factory)

    user = await user_repo.get(uid)
    if user is None or not user.birth_date:
        raise ValueError(f"User {user_id} has no birth_date set")
    user_date = user.birth_date

    matrix1 = MatrixService.calculate(user_date)
    matrix2 = MatrixService.calculate(partner_date)
    analysis = await AIService.generate_compatibility(
        user_date, matrix1, partner_date, matrix2
    )
    token = ReportService.generate_token()

    user_name = user.first_name or user.username or "пользователь"
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
            "archetype_name": archetype_first_name,
            "archetype_number": matrix1.center,
            "archetype_first_name": archetype_first_name,
            "archetype_first_number": matrix1.center,
            "archetype_second_name": archetype_second_name,
            "archetype_second_number": matrix2.center,
        },
        template_name="compatibility_report.html",
    )
    pdf = await ReportService.generate_pdf(html)
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
    }


@celery_app.task(name="core.tasks.send_daily_insights")
def send_daily_insights() -> dict:
    return _run_async(_send_daily_insights_async())


async def _send_daily_insights_async() -> dict:
    session_factory = get_async_sessionmaker()
    async with session_factory() as session:
        result = await session.execute(
            select(User).where(User.subscription_status == "premium")
        )
        users = result.scalars().all()

    total = len(users)
    needs_rate_limit = total > 50
    sent = 0
    blocked = 0

    for i, user in enumerate(users):
        if needs_rate_limit and i > 0:
            await asyncio.sleep(0.5)

        if not user.birth_date:
            continue

        first_name = user.first_name or user.username or "пользователь"
        archetype_number = user.main_archetype_number
        if not archetype_number:
            continue

        archetype_info = ARCANA.get(archetype_number, {})
        archetype_name = archetype_info.get("name", "Неизвестный")
        archetype_key = archetype_info.get("key", "")

        try:
            matrix = MatrixService.calculate(user.birth_date)
            current_date_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            daily_insight = await AIService.generate_daily_insight(
                user_name=first_name,
                archetype_name=archetype_name,
                archetype_number=archetype_number,
                archetype_key=archetype_key,
                matrix_data=matrix,
                current_date=current_date_iso,
            )
            insight = daily_insight.insight
        except Exception:
            archetype_data = INSIGHTS_BY_ARCHETYPE.get(archetype_number)
            insight = (
                random.choice(archetype_data["insights"])
                if archetype_data and archetype_data["insights"]
                else "Сегодня — день новых возможностей. Откройся им."
            )

        text = (
            f"🌅 Доброе утро, {first_name}.\n\n"
            f"{insight}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "✨ Хочешь глубже? Открой полный отчёт или "
            "напиши NURA в чате — сегодня твой архетип "
            "шепчет тебе что-то важное."
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "💬 Чат с NURA", "callback_data": "chat_with_nura"}],
                [{"text": "📋 Мои отчёты", "callback_data": "view_reports"}],
                [{"text": "🏠 В меню", "callback_data": "main_menu"}],
            ],
        }

        ok = await _send_message(user.telegram_id, text, keyboard)
        if not ok:
            async with session_factory() as session:
                db_user = await session.get(User, user.id)
                if db_user is not None:
                    db_user.subscription_status = "blocked"
                    await session.commit()
            blocked += 1
        else:
            sent += 1

    return {"sent": sent, "blocked": blocked, "total": total}


@celery_app.task(name="core.tasks.send_daily_tarot_card")
def send_daily_tarot_card() -> dict:
    return _run_async(_send_daily_tarot_card_async())


async def _send_daily_tarot_card_async() -> dict:
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    users = await user_repo.get_users_with_tarot()

    sent = 0
    blocked = 0
    for i, user in enumerate(users):
        if i > 0 and len(users) > 50:
            await asyncio.sleep(0.5)
        if not user.birth_date:
            continue

        try:
            card = await AIService.generate_tarot_daily_card(user.birth_date, user)
        except Exception:
            continue

        text = format_daily_card_message(user.first_name, card)
        keyboard = {
            "inline_keyboard": [
                [{"text": "🂠 Расклад недели", "callback_data": "tarot_weekly_spread"}],
                [{"text": "🏠 В меню", "callback_data": "main_menu"}],
            ],
        }
        ok = await _send_message(user.telegram_id, text, keyboard)
        if ok:
            sent += 1
        else:
            async with session_factory() as session:
                db_user = await session.get(User, user.id)
                if db_user is not None:
                    db_user.tarot_subscription = False
                    await session.commit()
            blocked += 1
    return {"sent": sent, "blocked": blocked, "total": len(users)}


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
                User.subscription_until <= three_days,
                User.subscription_until > now,
            )
        )
        users = result.scalars().all()

    notified = 0
    for user in users:
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


@celery_app.task(name="core.tasks.assemble_video")
def assemble_video(scenario_name: str) -> dict:
    import json

    from core.services.video_assembler import NURA_ROOT, ScenarioConfig, assemble

    scenario_path = NURA_ROOT / "scenarios" / f"{scenario_name}.json"
    if not scenario_path.exists():
        raise FileNotFoundError(f"Scenario not found: {scenario_path}")

    raw = json.loads(scenario_path.read_text("utf-8"))
    cfg = ScenarioConfig.model_validate(raw)
    output = assemble(cfg)
    return {"output": str(output)}


@celery_app.task(name="core.tasks.assemble_carousel")
def assemble_carousel(scenario_name: str) -> dict:
    import json

    from core.schemas.carousel import CarouselConfig
    from core.services.carousel_assembler import NURA_ROOT, CarouselAssembler

    carousel_path = NURA_ROOT / "scenarios" / f"{scenario_name}.carousel.json"
    if not carousel_path.exists():
        raise FileNotFoundError(f"Carousel config not found: {carousel_path}")

    raw = json.loads(carousel_path.read_text("utf-8"))
    cfg = CarouselConfig.model_validate(raw)
    paths = _run_async(CarouselAssembler.assemble(cfg))
    return {"output": [str(p) for p in paths], "count": len(paths)}
