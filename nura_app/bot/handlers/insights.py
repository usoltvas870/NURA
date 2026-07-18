"""Daily insight callback with a bounded free tier and subscriber cache."""

from __future__ import annotations

from datetime import date

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.keyboards.main_menu import main_menu_keyboard, subscription_keyboard
from bot.texts.insights import insight_of_day_text, insights_exhausted_text, no_matrix_text
from core.database import get_async_sessionmaker
from core.repositories.user import UserRepository
from core.services.ai import AIService

router = Router()
_FREE_DAILY_LIMIT = 5


def insight_keyboard():
    return main_menu_keyboard(has_matrix=True)


def insight_keyboard_subscriber():
    return main_menu_keyboard(has_matrix=True, subscription_status="premium")


@router.callback_query(F.data == "daily_insight")
async def show_insight(callback: CallbackQuery, state: FSMContext) -> None:
    """Show a deterministic free insight or a cached subscriber AI insight."""
    await callback.answer()
    repository = UserRepository(get_async_sessionmaker())
    user = await repository.get_by_telegram_id(callback.from_user.id)
    if user is None or not user.main_archetype:
        await callback.message.edit_text(no_matrix_text(), reply_markup=main_menu_keyboard())
        return

    data = await state.get_data()
    today = date.today().isoformat()
    is_subscriber = user.subscription_status == "premium"
    if not is_subscriber:
        key = f"insights_shown_{today}"
        shown = data.get(key, [])
        if len(shown) >= _FREE_DAILY_LIMIT:
            await callback.message.edit_text(insights_exhausted_text(), reply_markup=subscription_keyboard())
            return
        await state.update_data(**{key: [*shown, len(shown)]})
        text = f"{user.main_archetype}: сегодня выбери один небольшой, ясный следующий шаг."
        await callback.message.edit_text(insight_of_day_text(user.main_archetype, text), reply_markup=insight_keyboard())
        return

    if data.get("ai_insight_date") == today and data.get("ai_insight_text"):
        insight = data["ai_insight_text"]
    else:
        result = await AIService.generate_daily_insight(
            user_name=user.first_name or user.username or "друг",
            archetype_name=user.main_archetype,
            archetype_number=user.main_archetype_number or 0,
            archetype_key=user.main_archetype,
            matrix_data={}, current_date=today,
        )
        insight = result.insight
        await state.update_data(ai_insight_date=today, ai_insight_text=insight)
    await callback.message.edit_text(insight_of_day_text(user.main_archetype, insight), reply_markup=insight_keyboard_subscriber())
