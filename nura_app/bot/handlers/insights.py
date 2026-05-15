import logging
import random
from datetime import date, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.keyboards.main_menu import (
    insight_keyboard,
    insight_keyboard_subscriber,
    main_menu_keyboard,
    subscription_keyboard,
)
from bot.texts.insights import (
    insight_copied_text,
    insight_of_day_text,
    insights_exhausted_text,
    no_matrix_text,
    share_insight_text,
)
from core.database import get_async_sessionmaker
from core.repositories.user import UserRepository
from core.services.ai import AIService
from core.services.insights_data import INSIGHTS_BY_ARCHETYPE
from core.services.matrix import ARCANA, MatrixService

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(F.data == "insights")
async def show_insight(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()

    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_telegram_id(callback.from_user.id)

    if user is None:
        await callback.message.edit_text(
            "Пользователь не найден. Начни с /start",
            reply_markup=main_menu_keyboard(),
        )
        return

    if not user.main_archetype or not user.main_archetype_number:
        await callback.message.edit_text(
            no_matrix_text(),
            reply_markup=main_menu_keyboard(),
        )
        return

    archetype_number = user.main_archetype_number
    archetype_name = user.main_archetype

    is_subscriber = user.subscription_status == "premium"

    if is_subscriber:
        state_data = await state.get_data()
        today_str = date.today().isoformat()
        cached_date = state_data.get("ai_insight_date")
        cached_insight = state_data.get("ai_insight_text")

        if cached_date == today_str and cached_insight:
            text = insight_of_day_text(archetype_name, cached_insight)
            await callback.message.edit_text(text, reply_markup=insight_keyboard_subscriber())
            return

        try:
            if not user.birth_date:
                raise ValueError("No birth_date")

            matrix = MatrixService.calculate(user.birth_date)
            archetype_info = ARCANA.get(archetype_number, {})
            archetype_key = archetype_info.get("key", "")
            from datetime import datetime
            current_date_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            first_name = user.first_name or user.username or "пользователь"

            daily_insight = await AIService.generate_daily_insight(
                user_name=first_name,
                archetype_name=archetype_name,
                archetype_number=archetype_number,
                archetype_key=archetype_key,
                matrix_data=matrix,
                current_date=current_date_iso,
            )
            insight_text = daily_insight.insight
        except Exception:
            archetype_data = INSIGHTS_BY_ARCHETYPE.get(archetype_number)
            insight_text = (
                random.choice(archetype_data["insights"])
                if archetype_data and archetype_data["insights"]
                else "Сегодня — день новых возможностей. Откройся им."
            )

        await state.update_data(
            {
                "ai_insight_date": today_str,
                "ai_insight_text": insight_text,
                "current_insight_text": insight_text,
                "current_archetype_name": archetype_name,
            }
        )

        text = insight_of_day_text(archetype_name, insight_text)
        await callback.message.edit_text(text, reply_markup=insight_keyboard_subscriber())
        return

    archetype_data = INSIGHTS_BY_ARCHETYPE.get(archetype_number)

    if not archetype_data:
        await callback.message.edit_text(
            "Инсайты для твоего архетипа пока в разработке.",
            reply_markup=main_menu_keyboard(),
        )
        return

    insights_list = archetype_data["insights"]
    state_data = await state.get_data()
    shown_key = f"insights_shown_{date.today().isoformat()}"
    shown_indices = state_data.get(shown_key, [])

    available = [i for i in range(len(insights_list)) if i not in shown_indices]
    if not available:
        text = insights_exhausted_text()
        await callback.message.edit_text(text, reply_markup=subscription_keyboard())
        return

    chosen = random.choice(available)
    insight_text = insights_list[chosen]

    await state.update_data(
        {
            shown_key: [*shown_indices, chosen],
            "current_insight_text": insight_text,
            "current_archetype_name": archetype_name,
        }
    )

    text = insight_of_day_text(archetype_name, insight_text)
    await callback.message.edit_text(text, reply_markup=insight_keyboard())


@router.callback_query(F.data == "another_insight")
async def another_insight(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()

    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    user = await user_repo.get_by_telegram_id(callback.from_user.id)

    if not user or not user.main_archetype_number:
        await callback.message.edit_text(
            no_matrix_text(),
            reply_markup=main_menu_keyboard(),
        )
        return

    archetype_number = user.main_archetype_number
    archetype_name = user.main_archetype
    archetype_data = INSIGHTS_BY_ARCHETYPE.get(archetype_number)

    if not archetype_data:
        await callback.message.edit_text(
            "Инсайты для твоего архетипа пока в разработке.",
            reply_markup=main_menu_keyboard(),
        )
        return

    insights_list = archetype_data["insights"]
    state_data = await state.get_data()
    shown_key = f"insights_shown_{date.today().isoformat()}"
    shown_indices = state_data.get(shown_key, [])

    available = [i for i in range(len(insights_list)) if i not in shown_indices]
    if not available:
        text = insights_exhausted_text()
        await callback.message.edit_text(text, reply_markup=subscription_keyboard())
        return

    chosen = random.choice(available)
    insight_text = insights_list[chosen]

    shown_indices.append(chosen)
    await state.update_data(
        {
            shown_key: shown_indices,
            "current_insight_text": insight_text,
            "current_archetype_name": archetype_name,
        }
    )

    text = insight_of_day_text(archetype_name, insight_text)
    await callback.message.edit_text(text, reply_markup=insight_keyboard())


@router.callback_query(F.data == "share_insight")
async def share_insight(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()

    state_data = await state.get_data()
    insight_text = state_data.get("current_insight_text")

    if not insight_text:
        await callback.message.edit_text(
            "Нет инсайта для публикации. Начни с /insights",
            reply_markup=main_menu_keyboard(),
        )
        return

    share_text = share_insight_text(insight_text)
    await callback.message.answer(share_text)
    await callback.message.answer(insight_copied_text())
