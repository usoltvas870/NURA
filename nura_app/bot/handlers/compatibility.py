import asyncio
import logging
from urllib.parse import quote

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from celery.result import AsyncResult

from bot.handlers.validators import validate_date
from bot.states.compatibility_state import CompatibilityStates
from bot.texts.compatibility import (
    ask_partner_date_text,
    ask_partner_name_text,
    ask_relation_type_text,
    compat_details_text,
    loading_steps,
    mini_compatibility_text,
)
from bot.texts.matrix import invalid_format_text
from core.config import settings
from core.database import get_async_sessionmaker
from core.repositories.user import UserRepository
from core.tasks import celery_app, generate_compatibility_report

logger = logging.getLogger(__name__)

router = Router()

POLL_INTERVAL = 2
MAX_POLL_SECONDS = 90


def _has_unlimited_compat(user) -> bool:
    return bool(user.tarot_subscription) or user.subscription_status == "premium"


@router.callback_query(F.data == "compatibility")
async def ask_compatibility(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()

    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_telegram_id(callback.from_user.id)

    if user is None:
        await callback.message.edit_text("Пользователь не найден. Начни с /start")
        return

    if not user.has_matrix:
        await callback.message.edit_text(
            "❤️ Совместимость\n\n"
            "Введи дату рождения любого человека —\n"
            "я разберу вашу совместимость по матрицам.\n\n"
            "Доступно с покупкой Матрицы судьбы.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text="💎 Купить Матрицу — 890 ₽",
                        callback_data="buy_matrix"
                    )],
                    [InlineKeyboardButton(text="← Назад", callback_data="main_menu")],
                ]
            )
        )
        return

    if user.compatibility_used and not _has_unlimited_compat(user):
        await callback.message.edit_text(
            "❤️ Ты уже использовал бесплатный расклад совместимости.\n\n"
            "Безлимитная совместимость доступна с Таро-подпиской.\n"
            "Проверяй совместимость с друзьями, коллегами,\n"
            "новыми знакомыми — без ограничений.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text="✨ Подключить Таро — 390 ₽/мес",
                        callback_data="buy_tarot_subscription"
                    )],
                    [InlineKeyboardButton(text="← В меню", callback_data="main_menu")],
                ]
            )
        )
        return

    await callback.message.edit_text(
        ask_partner_name_text(),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Назад", callback_data="main_menu")]
        ])
    )
    await state.set_state(CompatibilityStates.waiting_partner_name)


@router.message(CompatibilityStates.waiting_partner_name)
async def process_partner_name(message: Message, state: FSMContext) -> None:
    partner_name = message.text.strip()
    await state.update_data(partner_name=partner_name)

    await message.answer(
        ask_relation_type_text(partner_name),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💑 Партнёр / Романтика",
                callback_data="reltype_romance")],
            [InlineKeyboardButton(text="👥 Друг / Подруга",
                callback_data="reltype_friend")],
            [InlineKeyboardButton(text="💼 Коллега",
                callback_data="reltype_colleague")],
            [InlineKeyboardButton(text="👨‍👩‍👧 Родственник",
                callback_data="reltype_family")],
            [InlineKeyboardButton(text="← Назад", callback_data="main_menu")],
        ])
    )
    await state.set_state(CompatibilityStates.waiting_relation_type)


@router.callback_query(F.data.startswith("reltype_"))
async def process_relation_type(callback: CallbackQuery,
                                 state: FSMContext) -> None:
    await callback.answer()
    rel_map = {
        "reltype_romance": "романтика",
        "reltype_friend": "дружба",
        "reltype_colleague": "работа",
        "reltype_family": "семья",
    }
    relation_type = rel_map.get(callback.data, "общение")
    await state.update_data(relation_type=relation_type)

    data = await state.get_data()
    partner_name = data.get("partner_name", "партнёра")

    await callback.message.edit_text(
        ask_partner_date_text(partner_name),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Назад",
                callback_data="main_menu")]
        ])
    )
    await state.set_state(CompatibilityStates.waiting_partner_date)


@router.message(CompatibilityStates.waiting_partner_date)
async def process_partner_date(message: Message, state: FSMContext) -> None:
    date_str = message.text.strip()

    if not validate_date(date_str):
        await message.answer(invalid_format_text())
        return

    data = await state.get_data()
    partner_name = data.get("partner_name", "")
    relation_type = data.get("relation_type", "общение")

    await state.clear()

    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_telegram_id(message.from_user.id)

    if user is None or not user.birth_date:
        await message.answer("Пользователь не найден. Начни с /start")
        return

    steps = loading_steps()
    msg = await message.answer(steps[0])
    for step in steps[1:]:
        await asyncio.sleep(2.5)
        await msg.edit_text(step)

    task = generate_compatibility_report.delay(
        str(user.id), date_str, partner_name, relation_type
    )

    result = None
    waited = 0
    while waited < MAX_POLL_SECONDS:
        ready = AsyncResult(task.id, app=celery_app).ready()
        if ready:
            result = AsyncResult(task.id, app=celery_app).result
            break
        await asyncio.sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL

    if result is None:
        await msg.edit_text("Что-то пошло не так. Попробуй ещё раз через минуту.")
        return

    analysis = result.get("analysis", {})
    token = result.get("token", "")
    sender_name = user.first_name or user.username or "Пользователь"

    text = mini_compatibility_text(
        user_name=sender_name,
        partner_name=partner_name,
        portrait_user=analysis.get("portrait_user", "..."),
        portrait_partner=analysis.get("portrait_partner", "..."),
        how_you_interact=analysis.get("how_you_interact", "..."),
        relation_type=relation_type,
    )

    partner_arcana_name = result.get(
        "archetype_second_name",
        analysis.get("archetype_second", "...")
    )
    partner_arcana_number = result.get("archetype_second_number", 0)

    arcana_first_name = result.get("archetype_first_name", "")
    arcana_first_number = result.get("archetype_first_number", 0)
    arcana_second_name = result.get("archetype_second_name", "")
    arcana_second_number = result.get("archetype_second_number", 0)

    await state.update_data(
        compat_user_name=sender_name,
        compat_partner_name=partner_name,
        compat_arcana_first_name=arcana_first_name,
        compat_arcana_first_number=arcana_first_number,
        compat_arcana_second_name=arcana_second_name,
        compat_arcana_second_number=arcana_second_number,
        compat_how_interact=analysis.get("how_you_interact", "Союз двух архетипов"),
    )

    share_text = (
        f"{sender_name} проверил нашу совместимость "
        f"в NURA ✦\n\n"
        f"Твой аркан в этой паре — "
        f"{partner_arcana_name} ({partner_arcana_number})\n\n"
        f"Хочешь увидеть полный разбор?\n"
        f"👉 t.me/ai_nura_bot"
    )
    share_url = (
        f"https://t.me/share/url"
        f"?url=t.me/ai_nura_bot"
        f"&text={quote(share_text)}"
    )

    relation_type = result.get("relation_type", "общение")

    keyboard_rows = []

    if token and _has_unlimited_compat(user):
        report_url = f"{settings.report_base_url}/report/{token}"
        keyboard_rows.append(
            [InlineKeyboardButton(text="📄 Открыть отчёт", url=report_url)],
        )
        if relation_type == "романтика":
            pdf_url = f"{settings.report_base_url}/report/{token}/pdf"
            keyboard_rows[0].append(
                InlineKeyboardButton(text="⬇️ Скачать PDF", url=pdf_url),
            )

    keyboard_rows.append(
        [InlineKeyboardButton(text="🔍 Как мы это считаем", callback_data="compat_details")],
    )

    keyboard_rows.append(
        [InlineKeyboardButton(text="🖼 Поделиться карточкой", callback_data="share_compat_card")],
    )

    keyboard_rows.append(
        [InlineKeyboardButton(text="🔗 Поделиться", url=share_url)],
    )

    if _has_unlimited_compat(user):
        keyboard_rows.append(
            [InlineKeyboardButton(text="🔄 Проверить другого человека", callback_data="compatibility")]
        )
    else:
        keyboard_rows.append(
            [InlineKeyboardButton(text="✨ Подключить Таро", callback_data="buy_tarot_subscription")]
        )

    keyboard_rows.append(
        [InlineKeyboardButton(text="← В меню", callback_data="main_menu")]
    )

    if not _has_unlimited_compat(user):
        await user_repo.mark_compatibility_used(user.id)

    await msg.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows),
    )


@router.callback_query(F.data == "compat_details")
async def show_compat_details(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()

    user_name = data.get("compat_user_name", "Пользователь")
    partner_name = data.get("compat_partner_name", "партнёра")
    arcana_first_number = int(data.get("compat_arcana_first_number", 0))
    arcana_first_name = data.get("compat_arcana_first_name", "")
    arcana_second_number = int(data.get("compat_arcana_second_number", 0))
    arcana_second_name = data.get("compat_arcana_second_name", "")

    if not arcana_first_name:
        session_factory = get_async_sessionmaker()
        async with session_factory() as session:
            from sqlalchemy import select
            from core.models import Report, ReportType
            from core.services.matrix import MatrixService
            result = await session.execute(
                select(Report).where(
                    Report.user_id == callback.from_user.id,
                    Report.report_type == ReportType.COMPATIBILITY,
                ).order_by(Report.created_at.desc()).limit(1)
            )
            report = result.scalar_one_or_none()
            if report and report.matrix_data:
                md = report.matrix_data
                m1 = md.get("matrix1", {}).get("center", 0)
                m2 = md.get("matrix2", {}).get("center", 0)
                if isinstance(m1, (int, float)) and m1 > 0:
                    arcana_first_number = int(m1)
                    arcana_first_name = MatrixService.get_archetype_name(int(m1))
                if isinstance(m2, (int, float)) and m2 > 0:
                    arcana_second_number = int(m2)
                    arcana_second_name = MatrixService.get_archetype_name(int(m2))
                partner_name = md.get("partner_name", "партнёра")

    text = compat_details_text(
        user_name=user_name,
        partner_name=partner_name,
        arcana_first_number=arcana_first_number,
        arcana_first_name=arcana_first_name or "...",
        arcana_second_number=arcana_second_number,
        arcana_second_name=arcana_second_name or "...",
    )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Назад к результату", callback_data="compatibility")]
        ])
    )


@router.callback_query(F.data == "share_compat_card")
async def send_compat_card(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("Генерирую карточку…")

    data = await state.get_data()
    sender_name   = data.get("compat_user_name", "Пользователь")
    partner_name  = data.get("compat_partner_name", "Партнёр")
    a1_name       = data.get("compat_arcana_first_name", "Аркан")
    a1_num        = int(data.get("compat_arcana_first_number", 1))
    a2_name       = data.get("compat_arcana_second_name", "Аркан")
    a2_num        = int(data.get("compat_arcana_second_number", 1))
    compat_line   = data.get("compat_how_interact", "Союз двух архетипов")

    try:
        from core.services.share_card import generate_compat_card

        img_bytes = generate_compat_card(
            sender_name=sender_name,
            partner_name=partner_name,
            user_arcana_name=a1_name,
            user_arcana_number=a1_num,
            partner_arcana_name=a2_name,
            partner_arcana_number=a2_num,
            compatibility_line=compat_line,
        )

        photo = BufferedInputFile(img_bytes, filename="nura_compat.png")
        caption = (
            f"✦ {sender_name} + {partner_name}\n"
            f"{a1_name} · {a2_name}\n\n"
            f"Проверь свою совместимость: nura-ai.ru"
        )
        await callback.message.answer_photo(photo=photo, caption=caption)

    except Exception as e:
        logger.exception("share_card error: %s", e)
        await callback.message.answer("Не удалось создать карточку. Попробуй ещё раз.")
