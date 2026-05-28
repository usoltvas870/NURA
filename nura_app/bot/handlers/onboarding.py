import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.handlers.validators import validate_date
from bot.keyboards.main_menu import main_menu_keyboard
from bot.states.onboarding_state import OnboardingStates
from bot.texts.matrix import invalid_format_text
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
from core.services.matrix import MatrixService
from core.tasks import generate_mini_report

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_telegram_id(message.from_user.id)

    if user and user.birth_date:
        await _show_authenticated_menu(message, user)
        return

    if user is None:
        user = await user_repo.create(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )

    from bot.texts.onboarding import onboarding_greeting_text
    await message.answer(onboarding_greeting_text(message.from_user.first_name or ""))
    await state.set_state(OnboardingStates.waiting_for_birth_date)
    await message.answer(ask_birth_date_onboarding_text())


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
    db_user = user or await user_repo.get_by_telegram_id(message.from_user.id)

    if db_user is None:
        db_user = await user_repo.create(
            telegram_id=message.from_user.id,
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
    has_tarot = bool(db_user.tarot_subscription) if db_user else False
    await loading_msg.edit_text(
        onboarding_done_text(archetype_name, archetype_number),
        reply_markup=main_menu_keyboard(
            has_tarot=has_tarot,
            subscription_status=db_user.subscription_status,
        ),
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
            await report_repo.delete(mini_report.id)
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

    buttons.append([InlineKeyboardButton(text="🏠 В меню", callback_data="main_menu")])

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data == "calculate_matrix")
async def handle_calculate_matrix(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(OnboardingStates.waiting_for_birth_date)
    await callback.message.edit_text(ask_birth_date_onboarding_text())


async def _show_authenticated_menu(message: Message, user) -> None:
    from bot.texts.start import welcome_back_text

    name = user.first_name or user.username or "пользователь"
    archetype = user.main_archetype or "не определён"
    has_tarot = bool(user.tarot_subscription) if user else False
    await message.answer(
        welcome_back_text(name=name, archetype=archetype),
        reply_markup=main_menu_keyboard(
            has_matrix=bool(user.has_matrix),
            has_tarot=has_tarot,
            subscription_status=user.subscription_status,
        ),
    )
