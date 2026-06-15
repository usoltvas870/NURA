import logging
from datetime import date, datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.main_menu import main_menu_keyboard
from bot.keyboards.tarot_keyboard import (
    tarot_back_keyboard,
    tarot_menu_keyboard,
    tarot_more_keyboard,
    tarot_paywall_keyboard,
    tarot_spheres_keyboard,
    tarot_result_keyboard,
)
from bot.states.tarot_state import TarotStates
from bot.utils.arcana import _daily_arcana_number, _personal_arcana_number
from bot.utils.loading import animated_loading
from core.arcana_data import ARCANA
from core.config import settings
from core.database import get_async_sessionmaker
from core.repositories.user import UserRepository
from core.services.ai import AIService

logger = logging.getLogger(__name__)

router = Router()

_SPHERE_NAMES: dict[str, str] = {
    "tarot_sphere_money": "Деньги и реализация",
    "tarot_sphere_relations": "Отношения",
    "tarot_sphere_purpose": "Предназначение",
    "tarot_money": "Деньги и реализация",
    "tarot_relations": "Отношения",
    "tarot_purpose": "Предназначение",
}


async def _get_user(telegram_id: int):
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)
    return await user_repo.get_by_telegram_id(telegram_id)


def _paywall_text(spread_name: str) -> str:
    return (
        f"🔒 {spread_name}\n\n"
        "Этот расклад доступен в полной практике.\n"
        "Открой все расклады за 390 ₽/мес."
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


@router.callback_query(F.data == "tarot_more")
async def show_tarot_more(callback: CallbackQuery) -> None:
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
            _paywall_text("Ещё расклады"),
            reply_markup=tarot_paywall_keyboard(),
        )
        return
    await callback.message.edit_text(
        "✨ Ещё расклады\n\nВыбери практику:",
        reply_markup=tarot_more_keyboard(),
    )


@router.callback_query(F.data == "tarot_daily_card")
async def show_tarot_daily_card(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await _get_user(callback.from_user.id)
    if user is None:
        await callback.message.edit_text(
            "Пользователь не найден. Начни с /start",
            reply_markup=main_menu_keyboard(),
        )
        return

    today = date.today()
    center_arcana = user.main_archetype_number or _daily_arcana_number(today)
    arcana_num = _personal_arcana_number(today, center_arcana)
    arcana_name = ARCANA[arcana_num]["name"]

    async with animated_loading(callback.message, "🃏 Вытягиваю карту дня"):
        try:
            prompt = AIService._load_prompt("tarot_daily_card.txt")
            filled = prompt.format(
                arcana_number=arcana_num,
                arcana_name=arcana_name,
                user_archetype_number=user.main_archetype_number or arcana_num,
                user_archetype_name=user.main_archetype or arcana_name,
                user_name=user.first_name or user.username or "друг",
                date=today.strftime("%d.%m.%Y"),
            )
            result_text = await AIService.chat(
                messages=[
                    {"role": "system", "content": (
                        "Ты — NURA, персональный психологический проводник. "
                        "Обращайся к пользователю по имени. "
                        "Никогда не называй арканы, карты и их номера. "
                        "Пиши живым личным языком — не как гороскоп, а как персональный инсайт."
                    )},
                    {"role": "user", "content": filled},
                ],
                api_params={"max_tokens": 400, "temperature": 0.7},
            )
            result_text = result_text.strip().strip('"')
        except Exception:
            logger.exception("tarot daily_card AI failed")
            result_text = "Карты молчат сегодня. Попробуй позже."

    has_tarot = bool(user.tarot_subscription)
    user_name_display = user.first_name or user.username or "друг"
    text = (
        f"🌒 <b>Карта дня для {user_name_display}</b>\n"
        f"<i>{today.strftime('%d.%m.%Y')}</i>\n"
        f"{'─' * 20}\n\n"
        f"{result_text}"
    )

    if has_tarot:
        kb = tarot_result_keyboard()
    else:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✨ Открыть практику — 390 ₽/мес", callback_data="buy_tarot_subscription")],
            [InlineKeyboardButton(text="← К раскладам", callback_data="tarot_menu")],
        ])

    await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data == "tarot_weekly")
async def show_tarot_weekly(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await _get_user(callback.from_user.id)
    if user is None:
        await callback.message.edit_text("Пользователь не найден. Начни с /start", reply_markup=main_menu_keyboard())
        return
    if not user.tarot_subscription and not settings.test_mode:
        await callback.message.edit_text(_paywall_text("Расклад недели"), reply_markup=tarot_paywall_keyboard())
        return
    if not user.birth_date:
        await callback.message.edit_text("Для расклада нужна твоя дата рождения. Заполни её в /start", reply_markup=tarot_back_keyboard())
        return
    async with animated_loading(callback.message, "🎴 Раскладываю карты"):
        try:
            result = await AIService.generate_tarot_weekly_spread(user.birth_date, user)
        except Exception:
            logger.exception("show_tarot_weekly AI failed")
            await callback.message.edit_text(
                "✦ Расклад недели\n\nКарты молчат сегодня. Попробуй позже.",
                reply_markup=tarot_back_keyboard(),
            )
            return
    b = result.get("body", {})
    m = result.get("mind", {})
    s = result.get("spirit", {})
    overall = result.get("overall", "")
    text = (
        f"✦ Расклад недели\n\n"
        f"💪 Тело \u2014 {b.get('card_name', '')}\n"
        f"{b.get('interpretation', '')}\n"
        f"Практика: {b.get('practice', '')}\n\n"
        f"🧠 Ум \u2014 {m.get('card_name', '')}\n"
        f"{m.get('interpretation', '')}\n"
        f"Практика: {m.get('practice', '')}\n\n"
        f"🌀 Дух \u2014 {s.get('card_name', '')}\n"
        f"{s.get('interpretation', '')}\n"
        f"Практика: {s.get('practice', '')}\n\n"
        f"{'─' * 16}\n"
        f"{overall}"
    )
    await callback.message.edit_text(text, reply_markup=tarot_result_keyboard())


@router.callback_query(F.data == "tarot_question")
async def start_tarot_question(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    user = await _get_user(callback.from_user.id)
    if user is None:
        await callback.message.edit_text("Пользователь не найден. Начни с /start", reply_markup=main_menu_keyboard())
        return
    if not user.tarot_subscription and not settings.test_mode:
        await callback.message.edit_text(_paywall_text("Расклад по вопросу"), reply_markup=tarot_paywall_keyboard())
        return
    await state.set_state(TarotStates.waiting_for_question)
    await state.update_data(spread_type="question")
    await callback.message.edit_text("◈ Расклад по вопросу\n\nНапиши свой вопрос, и я разложу карты.")


@router.callback_query(F.data.in_({
    "tarot_money", "tarot_relations", "tarot_purpose",
    "tarot_sphere_money", "tarot_sphere_relations", "tarot_sphere_purpose",
}))
async def show_sphere_result(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    user = await _get_user(callback.from_user.id)
    if user is None:
        await callback.message.edit_text("Пользователь не найден. Начни с /start", reply_markup=main_menu_keyboard())
        return
    if not user.tarot_subscription and not settings.test_mode:
        await callback.message.edit_text(_paywall_text("Сферы жизни"), reply_markup=tarot_paywall_keyboard())
        return

    await state.clear()
    sphere_name = _SPHERE_NAMES[callback.data]
    today = date.today()
    arcana_num = _daily_arcana_number(today)
    arcana_name = ARCANA[arcana_num]["name"]

    async with animated_loading(callback.message, "🃏 Раскладываю карты"):
        try:
            prompt = AIService._load_prompt("tarot_spheres.txt")
            filled = prompt.format(
                sphere_name=sphere_name,
                arcana_number=arcana_num,
                arcana_name=arcana_name,
                date=datetime.now().strftime("%d.%m.%Y"),
            )
            interpretation = await AIService.chat(
                messages=[
                    {"role": "system", "content": "Ты — NURA, AI-проводник самопознания."},
                    {"role": "user", "content": filled},
                ],
                api_params={"max_tokens": 500, "temperature": 0.7},
            )
            interpretation = interpretation.strip().strip('"')
        except Exception:
            logger.exception("show_sphere_result AI failed")
            await callback.message.edit_text(
                f"✶ Сферы жизни — {sphere_name}\n\nКарты молчат сегодня. Попробуй позже.",
                reply_markup=tarot_back_keyboard(),
            )
            return

    text = (
        f"✶ {sphere_name}\n"
        f"{'─' * 20}\n\n"
        f"{interpretation}\n\n"
        f"Аркан · {arcana_name}"
    )
    await callback.message.edit_text(text, reply_markup=tarot_result_keyboard())


@router.callback_query(F.data == "tarot_spheres")
async def show_tarot_spheres(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    user = await _get_user(callback.from_user.id)
    if user is None:
        await callback.message.edit_text("Пользователь не найден. Начни с /start", reply_markup=main_menu_keyboard())
        return
    if not user.tarot_subscription and not settings.test_mode:
        await callback.message.edit_text(_paywall_text("Сферы жизни"), reply_markup=tarot_paywall_keyboard())
        return
    await state.set_state(TarotStates.waiting_for_sphere)
    await callback.message.edit_text(
        "✶ Сферы жизни\n\nВыбери сферу, которую хочешь рассмотреть:",
        reply_markup=tarot_spheres_keyboard(),
    )


@router.callback_query(F.data == "tarot_twins")
async def show_tarot_twins(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await _get_user(callback.from_user.id)
    if user is None:
        await callback.message.edit_text("Пользователь не найден. Начни с /start", reply_markup=main_menu_keyboard())
        return
    if not user.tarot_subscription and not settings.test_mode:
        await callback.message.edit_text(_paywall_text("Теневые стороны"), reply_markup=tarot_paywall_keyboard())
        return

    today = date.today()
    base = _daily_arcana_number(today)
    arcana_one = base
    arcana_two = base % 22 + 1
    dominant = arcana_one if arcana_one >= arcana_two else arcana_two

    async with animated_loading(callback.message, "🃏 Раскладываю карты"):
        try:
            prompt = AIService._load_prompt("tarot_doubles.txt")
            filled = prompt.format(
                arcana_one_number=arcana_one,
                arcana_one_name=ARCANA[arcana_one]["name"],
                arcana_two_number=arcana_two,
                arcana_two_name=ARCANA[arcana_two]["name"],
                dominant_arcana_name=ARCANA[dominant]["name"],
                date=datetime.now().strftime("%d.%m.%Y"),
            )
            interpretation = await AIService.chat(
                messages=[
                    {"role": "system", "content": "Ты — NURA, AI-проводник самопознания."},
                    {"role": "user", "content": filled},
                ],
                api_params={"max_tokens": 500, "temperature": 0.7},
            )
            interpretation = interpretation.strip().strip('"')
        except Exception:
            logger.exception("show_tarot_twins AI failed")
            await callback.message.edit_text(
                "☯ Теневые стороны\n\nКарты молчат сегодня. Попробуй позже.",
                reply_markup=tarot_back_keyboard(),
            )
            return

    text = (
        f"☯ Теневые стороны\n"
        f"{'─' * 20}\n\n"
        f"{interpretation}\n\n"
        f"{ARCANA[arcana_one]['name']} · {ARCANA[arcana_two]['name']}"
    )
    await callback.message.edit_text(text, reply_markup=tarot_result_keyboard())


@router.callback_query(F.data == "tarot_portal")
async def show_tarot_portal(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await _get_user(callback.from_user.id)
    if user is None:
        await callback.message.edit_text("Пользователь не найден. Начни с /start", reply_markup=main_menu_keyboard())
        return
    if not user.tarot_subscription and not settings.test_mode:
        await callback.message.edit_text(_paywall_text("Энергия месяца"), reply_markup=tarot_paywall_keyboard())
        return

    now = datetime.now()
    month_num = now.month
    teach = (month_num * 3) % 22 + 1
    release = (month_num * 7) % 22 + 1
    strengthen = (month_num * 11) % 22 + 1

    month_names = {
        1: "Январь", 2: "Февраль", 3: "Март",
        4: "Апрель", 5: "Май", 6: "Июнь",
        7: "Июль", 8: "Август", 9: "Сентябрь",
        10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
    }
    month_name = month_names[month_num]

    async with animated_loading(callback.message, "🃏 Открываю портал месяца"):
        try:
            prompt = AIService._load_prompt("tarot_portal.txt")
            filled = prompt.format(
                month_name=month_name,
                teach_arcana_number=teach,
                teach_arcana_name=ARCANA[teach]["name"],
                release_arcana_number=release,
                release_arcana_name=ARCANA[release]["name"],
                strengthen_arcana_number=strengthen,
                strengthen_arcana_name=ARCANA[strengthen]["name"],
            )
            interpretation = await AIService.chat(
                messages=[
                    {"role": "system", "content": "Ты — NURA, AI-проводник самопознания."},
                    {"role": "user", "content": filled},
                ],
                api_params={"max_tokens": 500, "temperature": 0.7},
            )
            interpretation = interpretation.strip().strip('"')
        except Exception:
            logger.exception("show_tarot_portal AI failed")
            await callback.message.edit_text(
                f"🌅 Энергия месяца — {month_name}\n\nКарты молчат сегодня. Попробуй позже.",
                reply_markup=tarot_back_keyboard(),
            )
            return

    text = (
        f"🌅 Энергия месяца — {month_name}\n"
        f"{'─' * 20}\n\n"
        f"{interpretation}"
    )
    await callback.message.edit_text(text, reply_markup=tarot_result_keyboard())


@router.callback_query(F.data == "tarot_blocks")
async def show_tarot_blocks(callback: CallbackQuery) -> None:
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
            _paywall_text("Что мешает"),
            reply_markup=tarot_paywall_keyboard(),
        )
        return

    today = date.today()
    base = _daily_arcana_number(today)
    block_num = base
    cause_num = (base * 3) % 22 + 1
    solution_num = (base * 7) % 22 + 1

    async with animated_loading(callback.message, "🃏 Раскладываю карты"):
        try:
            prompt = AIService._load_prompt("tarot_blocks.txt")
            filled = prompt.format(
                block_arcana_number=block_num,
                block_arcana_name=ARCANA[block_num]["name"],
                cause_arcana_number=cause_num,
                cause_arcana_name=ARCANA[cause_num]["name"],
                solution_arcana_number=solution_num,
                solution_arcana_name=ARCANA[solution_num]["name"],
                date=datetime.now().strftime("%d.%m.%Y"),
            )
            interpretation = await AIService.chat(
                messages=[
                    {"role": "system", "content": (
                        "Ты — NURA, психологический проводник. "
                        "Никогда не называй арканы, карты и их номера. "
                        "Переводи их в психологические качества. "
                        "Пиши живым человеческим языком."
                    )},
                    {"role": "user", "content": filled},
                ],
                api_params={"max_tokens": 600, "temperature": 0.7},
            )
            interpretation = interpretation.strip().strip('"')
        except Exception:
            logger.exception("show_tarot_blocks AI failed")
            await callback.message.edit_text(
                "🚧 Что мешает\n\nКарты молчат сегодня. Попробуй позже.",
                reply_markup=tarot_back_keyboard(),
            )
            return

    text = (
        f"🚧 Что мешает\n"
        f"{'─' * 20}\n\n"
        f"{interpretation}"
    )
    await callback.message.edit_text(text, reply_markup=tarot_result_keyboard())


@router.callback_query(F.data == "tarot_yes_no")
async def start_tarot_yes_no(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    user = await _get_user(callback.from_user.id)
    if user is None:
        await callback.message.edit_text("Пользователь не найден. Начни с /start", reply_markup=main_menu_keyboard())
        return
    if not user.tarot_subscription and not settings.test_mode:
        await callback.message.edit_text(_paywall_text("Да/Нет"), reply_markup=tarot_paywall_keyboard())
        return
    await state.set_state(TarotStates.waiting_for_question)
    await state.update_data(spread_type="yes_no")
    await callback.message.edit_text("🔮 Да/Нет\n\nНапиши свой вопрос, и я разложу карты.")


@router.message(TarotStates.waiting_for_question)
async def handle_question_input(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напиши свой вопрос текстом.")
        return

    data = await state.get_data()
    spread_type = data.get("spread_type", "question")
    question = message.text
    today = date.today()
    base_arcana = _daily_arcana_number(today)

    if spread_type == "yes_no":
        arcana_name = ARCANA[base_arcana]["name"]
        yes_or_no = "Да" if base_arcana % 2 == 1 else "Нет"
        async with animated_loading(message, "🃏 Раскладываю карты"):
            try:
                prompt = AIService._load_prompt("tarot_yes_no.txt")
                filled = prompt.format(
                    question=question,
                    arcana_number=base_arcana,
                    arcana_name=arcana_name,
                    yes_or_no=yes_or_no,
                )
                interpretation = await AIService.chat(
                    messages=[
                        {"role": "system", "content": "Ты — NURA, AI-проводник самопознания."},
                        {"role": "user", "content": filled},
                    ],
                    api_params={"max_tokens": 500, "temperature": 0.7},
                )
                interpretation = interpretation.strip().strip('"')
            except Exception:
                logger.exception("tarot yes_no AI failed")
                await message.answer("🔮 Да/Нет\n\nКарты молчат сегодня. Попробуй позже.", reply_markup=tarot_back_keyboard())
                await state.clear()
                return

        text = (
            f"🔮 Да/Нет\n"
            f"{'─' * 20}\n\n"
            f"Вопрос: {question}\n\n"
            f"{interpretation}\n\n"
            f"Аркан · {arcana_name}"
        )
        await message.answer(text, reply_markup=tarot_result_keyboard())

    else:
        past_num = (base_arcana - 1) % 22 + 1
        present_num = base_arcana
        future_num = base_arcana % 22 + 1
        past_name = ARCANA[past_num]["name"]
        present_name = ARCANA[present_num]["name"]
        future_name = ARCANA[future_num]["name"]

        async with animated_loading(message, "🃏 Раскладываю карты"):
            try:
                prompt = AIService._load_prompt("tarot_question.txt")
                filled = prompt.format(
                    question=question,
                    date=today.strftime("%d.%m.%Y"),
                    past_arcana=past_num,
                    past_arcana_name=past_name,
                    present_arcana=present_num,
                    present_arcana_name=present_name,
                    future_arcana=future_num,
                    future_arcana_name=future_name,
                )
                interpretation = await AIService.chat(
                    messages=[
                        {"role": "system", "content": "Ты — NURA, AI-проводник самопознания."},
                        {"role": "user", "content": filled},
                    ],
                    api_params={"max_tokens": 500, "temperature": 0.7},
                )
                interpretation = interpretation.strip().strip('"')
            except Exception:
                logger.exception("tarot question AI failed")
                await message.answer("◈ Расклад по вопросу\n\nКарты молчат сегодня. Попробуй позже.", reply_markup=tarot_back_keyboard())
                await state.clear()
                return

        text = (
            f"◈ Расклад по вопросу\n"
            f"{'─' * 20}\n\n"
            f"Вопрос: {question}\n\n"
            f"{interpretation}\n\n"
            f"Прошлое · {past_name}\n"
            f"Настоящее · {present_name}\n"
            f"Будущее · {future_name}"
        )
        await message.answer(text, reply_markup=tarot_result_keyboard())

    await state.clear()