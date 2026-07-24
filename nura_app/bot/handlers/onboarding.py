import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.handlers.validators import validate_date
from bot.keyboards.main_menu import open_pwa_keyboard
from bot.states.onboarding_state import OnboardingStates
from bot.texts.matrix import mini_analysis_text
from bot.texts.onboarding import (
    ask_birth_date_onboarding_text,
    invalid_format_onboarding_text,
    my_matrix_text,
    onboarding_done_text,
    onboarding_loading_text,
)
from core.config import settings
from core.database import get_async_sessionmaker
from core.models import ReportType
from core.repositories.report import ReportRepository
from core.repositories.user import UserRepository
from core.services.matrix import ARCANA, MatrixService
from core.tasks import generate_mini_report

logger = logging.getLogger(__name__)

router = Router()


@router.message(OnboardingStates.waiting_for_birth_date)
async def process_onboarding_birth_date(
    message: Message, state: FSMContext, user=None
) -> None:
    date_str = message.text.strip()

    if not validate_date(date_str):
        await message.answer(invalid_format_onboarding_text())
        return

    await state.clear()

    loading_msg = await message.answer(onboarding_loading_text())

    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    db_user = user or await user_repo.get_or_create_by_telegram_id(
        message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )

    matrix = MatrixService.calculate(date_str)
    archetype_name = MatrixService.get_archetype_name(matrix.center)
    archetype_number = matrix.center

    await user_repo.update_birth_date(db_user.id, date_str)
    await user_repo.update_archetype(db_user.id, archetype_name, archetype_number)

    username = message.from_user.username or message.from_user.first_name or "user"
    generate_mini_report.delay(str(db_user.id), date_str, username)

    await asyncio.sleep(0.5)
    await loading_msg.edit_text(
        onboarding_done_text(archetype_name, archetype_number),
        reply_markup=open_pwa_keyboard(),
    )


@router.callback_query(F.data == "my_matrix")
async def show_my_matrix(callback: CallbackQuery) -> None:
    await callback.answer()
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    report_repo = ReportRepository(session_factory)
    user = await user_repo.get_by_telegram_id(callback.from_user.id)

    if not user or not user.birth_date:
        await callback.message.edit_text(
            "У тебя ещё нет рассчитанной матрицы.\n"
            "Напиши /start чтобы начать ✶"
        )
        return

    matrix = MatrixService.calculate(user.birth_date)
    arcana = matrix.arcana_names

    schema_text = my_matrix_text(
        archetype_name=user.main_archetype or arcana["center"],
        archetype_number=user.main_archetype_number or matrix.center,
        birth_date=user.birth_date,
        center_name=arcana["center"],
        top_name=arcana["top"],
        bottom_name=arcana["bottom"],
        left_name=arcana["left"],
        right_name=arcana["right"],
        talent_zone=arcana["talent_zone"],
        comfort_zone=arcana["comfort_zone"],
        portrait_zone=arcana["portrait_zone"],
    )

    mini_report = await report_repo.get_by_user_id_and_type(user.id, ReportType.MINI)
    full_report = await report_repo.get_by_user_id_and_type(user.id, ReportType.FULL)

    if mini_report and mini_report.ai_analysis:
        analysis = mini_report.ai_analysis or {}
        raw = analysis.get("main_archetype", "")
        is_fallback = isinstance(raw, str) and any(
            m in raw for m in ["чуть больше времени", "запросить разбор ещё раз", "дай мне ещё одну попытку"]
        )
        if is_fallback:
            username = callback.from_user.username or callback.from_user.first_name or "user"
            generate_mini_report.delay(str(user.id), user.birth_date, username)
            await callback.message.edit_text(
                "🔄 Пересчитываю твою матрицу...\n"
                "Это займёт около минуты.\n"
                "Нажми ◈ Моя матрица через минуту."
            )
            return
        matrix_data = mini_report.matrix_data or {}
        analysis_text = mini_analysis_text(
            archetype_name=matrix_data.get("archetype_name", user.main_archetype or "..."),
            archetype_number=matrix_data.get("archetype_number", user.main_archetype_number or 0),
            main_archetype=analysis.get("main_archetype", "..."),
            core_strength=analysis.get("core_strength", "..."),
            emotional_conflict=analysis.get("emotional_conflict", "..."),
            relationship_pattern=analysis.get("relationship_pattern", "..."),
            financial_block=analysis.get("financial_block", "..."),
        )
        text = schema_text + "\n\n" + analysis_text
    else:
        text = schema_text

    # --- Задача 1.3: кнопки отчёта прямо здесь ---
    buttons: list[list[InlineKeyboardButton]] = []

    if full_report and full_report.token:
        # Есть купленный полный отчёт — показываем ссылку прямо здесь
        report_url = f"{settings.report_base_url}/report/{full_report.token}"
        pdf_url = f"{settings.report_base_url}/report/{full_report.token}/pdf"
        buttons.append([
            InlineKeyboardButton(text="📄 Открыть отчёт", url=report_url),
            InlineKeyboardButton(text="⬇️ Скачать PDF", url=pdf_url),
        ])
    else:
        # Матрица не куплена — показываем кнопку покупки с пояснением
        buttons.append([
            InlineKeyboardButton(text="💎 Купить матрицу — 890 ₽", callback_data="buy_matrix")
        ])
        buttons.append([
            InlineKeyboardButton(text="👁 Посмотреть пример отчёта", callback_data="sample_report")
        ])

    if mini_report and mini_report.matrix_data:
        buttons.append([InlineKeyboardButton(text="🔍 Показать расчёт", callback_data="show_kitchen")])

    buttons.append([InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")])

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


def _kitchen_from_matrix(matrix_data: dict) -> str:
    birth_date = matrix_data.get("birth_date", "")
    center = matrix_data.get("center", 0)
    portrait_zone = matrix_data.get("portrait_zone", 0)
    relationship_line = matrix_data.get("relationship_line", [])
    karmic_tail = matrix_data.get("karmic_tail", [])

    center_info = ARCANA.get(center, {})
    portrait_info = ARCANA.get(portrait_zone, {})

    lines = ["🔍 Как NURA считала твой разбор:"]
    if birth_date:
        lines.append(f"Дата: {birth_date}")
    lines.append(
        f"Центр матрицы: Аркан {center} ({center_info.get('name', '...')}) "
        f"→ {center_info.get('key', '')}"
    )
    if relationship_line:
        lines.append(
            f"Линия личности: {' → '.join(str(v) for v in relationship_line)}"
        )
    if karmic_tail:
        lines.append(
            f"Линия кармы: {' → '.join(str(v) for v in karmic_tail)}"
        )
    if portrait_zone and portrait_info:
        lines.append(
            f"Цель года: {portrait_zone} ({portrait_info.get('name', '...')})"
        )
    lines.append("")
    lines.append("Именно эти позиции легли в основу твоего разбора ✶")
    return "\n".join(lines)


@router.callback_query(F.data == "show_kitchen")
async def show_kitchen_callback(callback: CallbackQuery) -> None:
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    report_repo = ReportRepository(session_factory)
    user = await user_repo.get_by_telegram_id(callback.from_user.id)

    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    mini_report = await report_repo.get_by_user_id_and_type(user.id, ReportType.MINI)
    if not mini_report or not mini_report.matrix_data:
        await callback.answer("Нет данных для расчёта", show_alert=True)
        return

    text = _kitchen_from_matrix(mini_report.matrix_data)
    await callback.message.edit_text(text, reply_markup=open_pwa_keyboard())
    await callback.answer()


@router.callback_query(F.data == "calculate_matrix")
async def handle_calculate_matrix(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(OnboardingStates.waiting_for_birth_date)
    await callback.message.edit_text(ask_birth_date_onboarding_text())
