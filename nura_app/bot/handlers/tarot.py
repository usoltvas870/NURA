import logging
from datetime import date

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.main_menu import main_menu_keyboard
from bot.keyboards.tarot_keyboard import (
    tarot_back_keyboard,
    tarot_menu_keyboard,
    tarot_paywall_keyboard,
    tarot_spheres_keyboard,
)
from bot.states.tarot_state import TarotStates
from core.config import settings
from core.database import get_async_sessionmaker
from core.repositories.user import UserRepository

logger = logging.getLogger(__name__)

router = Router()

ARCANA = {
    1:  "Маг",
    2:  "Верховная Жрица",
    3:  "Императрица",
    4:  "Император",
    5:  "Иерофант",
    6:  "Влюблённые",
    7:  "Колесница",
    8:  "Сила",
    9:  "Отшельник",
    10: "Колесо Фортуны",
    11: "Справедливость",
    12: "Повешенный",
    13: "Смерть",
    14: "Умеренность",
    15: "Дьявол",
    16: "Башня",
    17: "Звезда",
    18: "Луна",
    19: "Солнце",
    20: "Суд",
    21: "Мир",
    22: "Шут",
}

_SPHERE_NAMES = {
    "tarot_sphere_money": "Деньги и карьера",
    "tarot_sphere_relations": "Отношения",
    "tarot_sphere_purpose": "Предназначение",
}


async def _get_user(telegram_id: int):
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    return await user_repo.get_by_telegram_id(telegram_id)


def _daily_arcana_number(today: date) -> int:
    total = sum(int(d) for d in f"{today.day:02d}{today.month:02d}{today.year}")
    while total > 22:
        total = sum(int(d) for d in str(total))
    return total


def _paywall_text(spread_name: str) -> str:
    return (
        f"🔒 {spread_name}\n\n"
        "Этот расклад доступен в полной практике.\n"
        "Открой все 7 раскладов за 390₽/мес."
    )


@router.callback_query(F.data == "tarot_menu")
async def show_tarot_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    user = await _get_user(callback.from_user.id)
    if user is None:
        await callback.message.edit_text(
            "Пользователь не найден. Начни с /start",
            reply_markup=main_menu_keyboard(),
        )
        return
    has_tarot = bool(user.tarot_subscription)
    if has_tarot:
        text = (
            "🌒 Таро-ритуалы\n\n"
            "Все расклады доступны.\n"
            "Выбери свою практику на сегодня."
        )
    else:
        text = (
            "🌒 Таро-ритуалы\n\n"
            "Карта дня — бесплатно каждое утро.\n"
            "Остальные расклады — в полной практике."
        )
    await callback.message.edit_text(text, reply_markup=tarot_menu_keyboard(has_tarot))


@router.callback_query(F.data == "tarot_daily_card")
async def show_daily_card(callback: CallbackQuery) -> None:
    await callback.answer()
    today = date.today()
    arcana_num = _daily_arcana_number(today)
    arcana_name = ARCANA[arcana_num]
    text = (
        f"🌒 Карта дня — {arcana_num}. {arcana_name}\n\n"
        f"[Заглушка интерпретации — TODO: AI промпт]\n\n"
        f"Аркан дня рассчитывается по дате {today.strftime('%d.%m.%Y')}."
    )
    await callback.message.edit_text(text, reply_markup=tarot_back_keyboard())


@router.callback_query(F.data == "tarot_weekly")
async def show_tarot_weekly(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await _get_user(callback.from_user.id)
    if user is None:
        await callback.message.edit_text(
            "Пользователь не найден. Начни с /start",
            reply_markup=main_menu_keyboard(),
        )
        return
    if not user.tarot_subscription and not settings.test_mode:
        await callback.message.edit_text(
            _paywall_text("Расклад недели"),
            reply_markup=tarot_paywall_keyboard(),
        )
        return
    await callback.message.edit_text(
        "🌒 Расклад недели — в разработке. Скоро здесь появится твой расклад.",
        reply_markup=tarot_back_keyboard(),
    )


@router.callback_query(F.data == "tarot_question")
async def start_tarot_question(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    user = await _get_user(callback.from_user.id)
    if user is None:
        await callback.message.edit_text(
            "Пользователь не найден. Начни с /start",
            reply_markup=main_menu_keyboard(),
        )
        return
    if not user.tarot_subscription and not settings.test_mode:
        await callback.message.edit_text(
            _paywall_text("Расклад по вопросу"),
            reply_markup=tarot_paywall_keyboard(),
        )
        return
    await state.set_state(TarotStates.waiting_for_question)
    await state.update_data(spread_type="question")
    await callback.message.edit_text(
        "◈ Расклад по вопросу\n\nНапиши свой вопрос, и я разложу карты."
    )


@router.callback_query(F.data == "tarot_spheres")
async def show_tarot_spheres(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    user = await _get_user(callback.from_user.id)
    if user is None:
        await callback.message.edit_text(
            "Пользователь не найден. Начни с /start",
            reply_markup=main_menu_keyboard(),
        )
        return
    if not user.tarot_subscription and not settings.test_mode:
        await callback.message.edit_text(
            _paywall_text("Сферы жизни"),
            reply_markup=tarot_paywall_keyboard(),
        )
        return
    await state.set_state(TarotStates.waiting_for_sphere)
    await callback.message.edit_text(
        "✶ Сферы жизни\n\nВыбери сферу, которую хочешь рассмотреть:",
        reply_markup=tarot_spheres_keyboard(),
    )


@router.callback_query(F.data.in_({"tarot_sphere_money", "tarot_sphere_relations", "tarot_sphere_purpose"}))
async def show_sphere_result(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    sphere = _SPHERE_NAMES[callback.data]
    await callback.message.edit_text(
        f"🌒 Сферы жизни — {sphere} — в разработке. Скоро здесь появится твой расклад.",
        reply_markup=tarot_back_keyboard(),
    )


@router.callback_query(F.data == "tarot_twins")
async def show_tarot_twins(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await _get_user(callback.from_user.id)
    if user is None:
        await callback.message.edit_text(
            "Пользователь не найден. Начни с /start",
            reply_markup=main_menu_keyboard(),
        )
        return
    if not user.tarot_subscription and not settings.test_mode:
        await callback.message.edit_text(
            _paywall_text("Двойники"),
            reply_markup=tarot_paywall_keyboard(),
        )
        return
    await callback.message.edit_text(
        "🌒 Двойники — в разработке. Скоро здесь появится твой расклад.",
        reply_markup=tarot_back_keyboard(),
    )


@router.callback_query(F.data == "tarot_portal")
async def show_tarot_portal(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await _get_user(callback.from_user.id)
    if user is None:
        await callback.message.edit_text(
            "Пользователь не найден. Начни с /start",
            reply_markup=main_menu_keyboard(),
        )
        return
    if not user.tarot_subscription and not settings.test_mode:
        await callback.message.edit_text(
            _paywall_text("Портал месяца"),
            reply_markup=tarot_paywall_keyboard(),
        )
        return
    await callback.message.edit_text(
        "🌒 Портал месяца — в разработке. Скоро здесь появится твой расклад.",
        reply_markup=tarot_back_keyboard(),
    )


@router.callback_query(F.data == "tarot_yes_no")
async def start_tarot_yes_no(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    user = await _get_user(callback.from_user.id)
    if user is None:
        await callback.message.edit_text(
            "Пользователь не найден. Начни с /start",
            reply_markup=main_menu_keyboard(),
        )
        return
    if not user.tarot_subscription and not settings.test_mode:
        await callback.message.edit_text(
            _paywall_text("Да/Нет"),
            reply_markup=tarot_paywall_keyboard(),
        )
        return
    await state.set_state(TarotStates.waiting_for_question)
    await state.update_data(spread_type="yes_no")
    await callback.message.edit_text(
        "👁 Да/Нет\n\nНапиши свой вопрос, и я разложу карты."
    )


@router.message(TarotStates.waiting_for_question)
async def handle_question_input(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напиши свой вопрос текстом.")
        return
    data = await state.get_data()
    spread_type = data.get("spread_type", "question")
    await state.clear()
    if spread_type == "yes_no":
        await message.answer(
            "🌒 Да/Нет — в разработке. Скоро здесь появится твой расклад.",
            reply_markup=tarot_back_keyboard(),
        )
    else:
        await message.answer(
            "🌒 Расклад по вопросу — в разработке. Скоро здесь появится твой расклад.",
            reply_markup=tarot_back_keyboard(),
        )
