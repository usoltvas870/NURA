import re
from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.main_menu import main_menu_keyboard
from bot.states.matrix_state import MatrixState
from core.tasks import generate_mini_report

router = Router()

DATE_PATTERN = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")


def validate_date(date_str: str) -> bool:
    if not DATE_PATTERN.match(date_str):
        return False
    try:
        datetime.strptime(date_str, "%d.%m.%Y")
        return True
    except ValueError:
        return False


@router.callback_query(F.data == "calculate_matrix")
async def ask_birth_date(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(MatrixState.waiting_for_birth_date)
    await callback.message.answer(
        "Введи свою дату рождения в формате ДД.ММ.ГГГГ\n"
        "Например: 15.06.1998"
    )


@router.message(MatrixState.waiting_for_birth_date)
async def process_birth_date(message: Message, state: FSMContext):
    date_str = message.text.strip()

    if not validate_date(date_str):
        await message.answer(
            "Пожалуйста, введи дату в формате ДД.ММ.ГГГГ, "
            "например 15.06.1998"
        )
        return

    await state.clear()

    user_id = str(message.from_user.id)
    await message.answer(
        "Анализирую твою Матрицу Судьбы...\n"
        "Это займёт несколько секунд."
    )

    try:
        task = generate_mini_report.delay(user_id, date_str)
        result = task.get(timeout=120)
    except Exception:
        await message.answer(
            "Произошла ошибка при расчёте. Попробуй снова через минуту.",
            reply_markup=main_menu_keyboard(),
        )
        return

    analysis = result.get("analysis", {})
    token = result.get("token", "")

    text = (
        "Твоя Матрица Судьбы\n\n"
        f"Главный архетип: {analysis.get('main_archetype', '...')}\n\n"
        f"Сильная сторона: {analysis.get('core_strength', '...')}\n\n"
        f"Эмоциональный конфликт: {analysis.get('emotional_conflict', '...')}\n\n"
        f"Паттерн отношений: {analysis.get('relationship_pattern', '...')}\n\n"
        f"Денежный блок: {analysis.get('financial_block', '...')}\n\n"
        "Хочешь получить полный AI-отчёт?\n"
        "В нём — теневые стороны, жизненные циклы, "
        "совместимость и персональные рекомендации на 7 дней."
    )

    from bot.keyboards.main_menu import paywall_keyboard

    await message.answer(text, reply_markup=paywall_keyboard(token))


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "Главное меню",
        reply_markup=main_menu_keyboard(),
    )
