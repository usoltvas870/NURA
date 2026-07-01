"""
Тесты bot handlers с моком aiogram.
Тестируем: tarot, start, profile, payment, compatibility.

CAVEMAN-ПРОТОКОЛ
================
- Никаких приветствий
- Русский язык комментариев
- Каждый тест проверяет edit_text / answer / send_message
- Мокаем на уровне импорта в тестируемом модуле
- Не импортируем реальные aiogram классы — только AsyncMock/patch
"""

# flake8: noqa: E501
# pylint: disable=redefined-outer-name,protected-access,too-many-lines

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =====================================================================
# FIXTURES (общие для всех тестов)
# =====================================================================


@pytest.fixture
def mock_user():
    """Базовый мок пользователя со всеми полями."""
    user = MagicMock()
    user.id = "user-uuid-1234"
    user.telegram_id = 123456789
    user.username = "testuser"
    user.first_name = "Test"
    user.birth_date = "01.01.2000"
    user.main_archetype = "Маг"
    user.main_archetype_number = 1
    user.subscription_status = "free"
    user.subscription_until = None
    user.tarot_subscription = False
    user.tarot_subscription_until = None
    user.has_matrix = False
    user.compatibility_used = False
    return user


@pytest.fixture
def mock_tarot_user(mock_user):
    """Пользователь с таро-подпиской."""
    mock_user.tarot_subscription = True
    mock_user.subscription_status = "premium"
    return mock_user


@pytest.fixture
def mock_premium_user(mock_user):
    """Premium-пользователь."""
    mock_user.subscription_status = "premium"
    mock_user.tarot_subscription = True
    mock_user.has_matrix = True
    mock_user.subscription_until = datetime.now(timezone.utc) + timedelta(days=30)
    return mock_user


@pytest.fixture
def mock_callback():
    """Базовый мок CallbackQuery."""
    cb = AsyncMock()
    cb.from_user.id = 123456789
    cb.message = AsyncMock()
    cb.message.edit_text = AsyncMock()
    cb.message.answer = AsyncMock()
    cb.message.chat = MagicMock()
    cb.message.chat.id = 123456789
    cb.answer = AsyncMock()
    return cb


@pytest.fixture
def mock_message():
    """Базовый мок Message."""
    msg = AsyncMock()
    msg.from_user.id = 123456789
    msg.from_user.username = "testuser"
    msg.from_user.first_name = "Test"
    msg.text = "test message"
    msg.chat = MagicMock()
    msg.chat.id = 123456789
    msg.answer = AsyncMock()
    msg.edit_text = AsyncMock()
    msg.reply = AsyncMock()
    msg.bot = AsyncMock()
    msg.bot.send_message = AsyncMock()
    return msg


@pytest.fixture
def mock_state():
    """Мок FSMContext."""
    state = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


@pytest.fixture
def mock_command():
    """Мок CommandObject для /start."""
    cmd = MagicMock()
    cmd.args = None
    return cmd


@pytest.fixture
def repo_patch():
    """Патч для UserRepository — возвращает базового пользователя."""

    def _make_patch(user_override: MagicMock | None = None):
        patcher = patch("bot.handlers.tarot.UserRepository")
        mock_repo_cls = MagicMock()
        repo_instance = MagicMock()
        repo_instance.get_by_telegram_id = AsyncMock(
            return_value=user_override or MagicMock()
        )
        mock_repo_cls.return_value = repo_instance
        patcher.start.return_value = mock_repo_cls
        return patcher, repo_instance

    return _make_patch


@pytest.fixture(autouse=True)
def patch_settings_test_mode():
    """Автоматически выключаем test_mode во всех тестах."""
    with patch("bot.handlers.tarot.settings") as mock_settings:
        mock_settings.test_mode = False
        mock_settings.report_base_url = "http://test"
        mock_settings.bot_username = "test_bot"
        mock_settings.support_username = "@test_support"
        yield mock_settings


@pytest.fixture
def patch_get_sessionmaker():
    """Патч get_async_sessionmaker."""
    with patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm:
        mock_gsm.return_value = MagicMock()
        yield mock_gsm


# =====================================================================
# TAROT HANDLER TESTS
# =====================================================================


class TestTarotMenu:
    """Тесты show_tarot_menu — callback_data == 'tarot_menu'."""

    @pytest.mark.asyncio
    async def test_shows_menu_for_free_user(
        self, mock_callback, mock_state, mock_user
    ):
        """Свободный пользователь видит меню с бесплатной картой дня."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.tarot_menu_keyboard") as mock_kb,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_kb.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_menu

            await show_tarot_menu(mock_callback, mock_state)

        mock_callback.answer.assert_awaited_once()
        mock_state.clear.assert_awaited_once()
        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Таро-ритуалы" in text
        assert "Карта дня — бесплатно" in text

    @pytest.mark.asyncio
    async def test_shows_menu_for_tarot_user(
        self, mock_callback, mock_state, mock_tarot_user
    ):
        """Пользователь с таро-подпиской видит 'все расклады доступны'."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.tarot_menu_keyboard") as mock_kb,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_tarot_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_kb.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_menu

            await show_tarot_menu(mock_callback, mock_state)

        mock_callback.answer.assert_awaited_once()
        mock_state.clear.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Все расклады доступны" in text

    @pytest.mark.asyncio
    async def test_user_not_found(
        self, mock_callback, mock_state
    ):
        """Пользователь не найден — показываем 'начни с /start'."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.main_menu_keyboard") as mock_mm,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=None)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_mm.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_menu

            await show_tarot_menu(mock_callback, mock_state)

        mock_callback.answer.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Пользователь не найден" in text

    @pytest.mark.asyncio
    async def test_calls_tarot_menu_keyboard_with_flag(
        self, mock_callback, mock_state, mock_tarot_user
    ):
        """Проверяем, что tarot_menu_keyboard вызывается с правильным флагом."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.tarot_menu_keyboard") as mock_kb,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_tarot_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_kb.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_menu

            await show_tarot_menu(mock_callback, mock_state)

        # has_tarot=True для пользователя с подпиской
        kwargs = mock_kb.call_args
        assert kwargs is not None
        assert kwargs[0][0] is True


class TestTarotMore:
    """Тесты show_tarot_more — callback_data == 'tarot_more'."""

    @pytest.mark.asyncio
    async def test_shows_paywall_for_free_user(
        self, mock_callback, mock_user
    ):
        """Свободный пользователь видит пэйволл."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot.tarot_paywall_keyboard") as mock_pw,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_pw.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_more

            await show_tarot_more(mock_callback)

        mock_callback.answer.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Этот расклад доступен в полной практике" in text

    @pytest.mark.asyncio
    async def test_shows_more_for_tarot_user(
        self, mock_callback, mock_tarot_user
    ):
        """Пользователь с таро видит 'Ещё расклады'."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot.tarot_more_keyboard") as mock_mk,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_tarot_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_mk.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_more

            await show_tarot_more(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Ещё расклады" in text

    @pytest.mark.asyncio
    async def test_user_not_found(
        self, mock_callback
    ):
        """Пользователь не найден."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot.main_menu_keyboard") as mock_mm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=None)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_mm.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_more

            await show_tarot_more(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Пользователь не найден" in text

    @pytest.mark.asyncio
    async def test_test_mode_bypasses_paywall(
        self, mock_callback, mock_user
    ):
        """Тестовый режим пропускает пэйволл."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot.tarot_more_keyboard") as mock_mk,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_mk.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_more
            from core.config import settings

            settings.test_mode = True

            await show_tarot_more(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Ещё расклады" in text


class TestTarotDailyCard:
    """Тесты show_tarot_daily_card — callback_data == 'tarot_daily_card'."""

    @pytest.mark.asyncio
    async def test_shows_daily_card(
        self, mock_callback, mock_user
    ):
        """Базовая карта дня для free-пользователя."""
        mock_user.main_archetype_number = 1
        mock_user.main_archetype = "Маг"
        mock_user.first_name = "Test"

        mock_daily_arcana = MagicMock()
        mock_daily_arcana.return_value = 5

        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot._daily_arcana_number", mock_daily_arcana),
            patch("bot.handlers.tarot._personal_arcana_number") as mock_personal,
            patch("bot.handlers.tarot.AIService") as mock_ai,
            patch("bot.handlers.tarot.animated_loading") as mock_load,
            patch("aiogram.types.InlineKeyboardMarkup") as mock_ikm,
            patch("aiogram.types.InlineKeyboardButton") as mock_ikb,
            patch("bot.handlers.tarot.ARCANA", {
                1: {"name": "Маг"},
                5: {"name": "Иерофант"},
            }),
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_personal.return_value = 5
            mock_load.return_value = AsyncMock()
            mock_load.return_value.__aenter__ = AsyncMock()
            mock_load.return_value.__aexit__ = AsyncMock()
            mock_ai._load_prompt.return_value = "prompt template {arcana_number}"
            mock_ai.chat = AsyncMock(return_value="Твоя карта дня — Иерофант. Время учиться новому.")
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_daily_card

            await show_tarot_daily_card(mock_callback)

        mock_callback.answer.assert_awaited_once()
        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Карта дня" in text
        assert "Test" in text or "Иерофант" in text or "учиться" in text

    @pytest.mark.asyncio
    async def test_no_user_shows_start_prompt(
        self, mock_callback, mock_state
    ):
        """Пользователь не найден."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot.main_menu_keyboard") as mock_mm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=None)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_mm.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_daily_card

            await show_tarot_daily_card(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Пользователь не найден" in text

    @pytest.mark.asyncio
    async def test_user_archetype_fallback(
        self, mock_callback, mock_user
    ):
        """Если у пользователя нет main_archetype_number — используется _daily_arcana_number."""
        mock_user.main_archetype_number = None
        mock_user.main_archetype = None

        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot._daily_arcana_number") as mock_daily,
            patch("bot.handlers.tarot._personal_arcana_number") as mock_personal,
            patch("bot.handlers.tarot.AIService") as mock_ai,
            patch("bot.handlers.tarot.animated_loading") as mock_load,
            patch("aiogram.types.InlineKeyboardMarkup") as mock_ikm,
            patch("aiogram.types.InlineKeyboardButton") as mock_ikb,
            patch("bot.handlers.tarot.ARCANA", {
                1: {"name": "Маг"},
                3: {"name": "Императрица"},
            }),
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            # daily возвращает 1, personal 3
            mock_daily.return_value = 1
            mock_personal.return_value = 3
            mock_load.return_value = AsyncMock()
            mock_load.return_value.__aenter__ = AsyncMock()
            mock_load.return_value.__aexit__ = AsyncMock()
            mock_ai._load_prompt.return_value = "prompt"
            mock_ai.chat = AsyncMock(return_value="Карта дня для тебя.")
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_daily_card

            await show_tarot_daily_card(mock_callback)

        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Карта дня" in text

    @pytest.mark.asyncio
    async def test_ai_failure_fallback(
        self, mock_callback, mock_user
    ):
        """При ошибке AI показываем 'Карты молчат сегодня'."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot._daily_arcana_number") as mock_daily,
            patch("bot.handlers.tarot._personal_arcana_number") as mock_personal,
            patch("bot.handlers.tarot.AIService") as mock_ai,
            patch("bot.handlers.tarot.animated_loading") as mock_load,
            patch("aiogram.types.InlineKeyboardMarkup") as mock_ikm,
            patch("aiogram.types.InlineKeyboardButton") as mock_ikb,
            patch("bot.handlers.tarot.ARCANA", {
                1: {"name": "Маг"},
                5: {"name": "Иерофант"},
            }),
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_daily.return_value = 1
            mock_personal.return_value = 5
            mock_load.return_value = AsyncMock()
            mock_load.return_value.__aenter__ = AsyncMock()
            mock_load.return_value.__aexit__ = AsyncMock()
            mock_ai._load_prompt.return_value = "prompt"
            mock_ai.chat = AsyncMock(side_effect=Exception("API error"))
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_daily_card

            await show_tarot_daily_card(mock_callback)

        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Карты молчат" in text or "Карта дня" in text

    @pytest.mark.asyncio
    async def test_tarot_user_sees_result_keyboard(
        self, mock_callback, mock_tarot_user
    ):
        """Пользователь с таро видит tarot_result_keyboard."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot._daily_arcana_number") as mock_daily,
            patch("bot.handlers.tarot._personal_arcana_number") as mock_personal,
            patch("bot.handlers.tarot.AIService") as mock_ai,
            patch("bot.handlers.tarot.animated_loading") as mock_load,
            patch("bot.handlers.tarot.tarot_result_keyboard") as mock_trk,
            patch("bot.handlers.tarot.ARCANA", {
                1: {"name": "Маг"},
                5: {"name": "Иерофант"},
            }),
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_tarot_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_daily.return_value = 1
            mock_personal.return_value = 5
            mock_load.return_value = AsyncMock()
            mock_load.return_value.__aenter__ = AsyncMock()
            mock_load.return_value.__aexit__ = AsyncMock()
            mock_ai._load_prompt.return_value = "prompt"
            mock_ai.chat = AsyncMock(return_value="Карта дня готова.")
            mock_trk.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_daily_card

            await show_tarot_daily_card(mock_callback)

        # Должен быть вызван tarot_result_keyboard, не InlineKeyboardMarkup
        mock_trk.assert_called_once()


class TestTarotWeekly:
    """Тесты show_tarot_weekly — callback_data == 'tarot_weekly'."""

    @pytest.mark.asyncio
    async def test_paywall_for_free_user(
        self, mock_callback, mock_user
    ):
        """Free-пользователь видит пэйволл."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot.tarot_paywall_keyboard") as mock_pw,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_pw.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_weekly

            await show_tarot_weekly(mock_callback)

        mock_callback.answer.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Этот расклад доступен в полной практике" in text

    @pytest.mark.asyncio
    async def test_no_birth_date_shows_error(
        self, mock_callback, mock_tarot_user
    ):
        """Пользователь без даты рождения видит просьбу заполнить её."""
        mock_tarot_user.birth_date = None

        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot.tarot_back_keyboard") as mock_tbk,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_tarot_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_tbk.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_weekly

            await show_tarot_weekly(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "дата рождения" in text

    @pytest.mark.asyncio
    async def test_generates_weekly_spread(
        self, mock_callback, mock_tarot_user
    ):
        """Успешная генерация расклада недели."""
        mock_result = {
            "body": {"card_name": "Маг", "interpretation": "Действуй", "practice": "Медитация"},
            "mind": {"card_name": "Жрица", "interpretation": "Слушай", "practice": "Дневник"},
            "spirit": {"card_name": "Императрица", "interpretation": "Твори", "practice": "Йога"},
            "overall": "Хорошая неделя",
        }

        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot.AIService") as mock_ai,
            patch("bot.handlers.tarot.animated_loading") as mock_load,
            patch("bot.handlers.tarot.tarot_result_keyboard") as mock_trk,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_tarot_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_load.return_value = AsyncMock()
            mock_load.return_value.__aenter__ = AsyncMock()
            mock_load.return_value.__aexit__ = AsyncMock()
            mock_ai.generate_tarot_weekly_spread = AsyncMock(
                return_value=mock_result
            )
            mock_trk.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_weekly

            await show_tarot_weekly(mock_callback)

        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Расклад недели" in text
        assert "Маг" in text
        assert "Жрица" in text
        assert "Императрица" in text

    @pytest.mark.asyncio
    async def test_ai_failure_shows_fallback(
        self, mock_callback, mock_tarot_user
    ):
        """При ошибке AI — сообщение об ошибке."""
        mock_tarot_user.birth_date = "01.01.2000"

        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot.AIService") as mock_ai,
            patch("bot.handlers.tarot.animated_loading") as mock_load,
            patch("bot.handlers.tarot.tarot_back_keyboard") as mock_tbk,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_tarot_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_load.return_value = AsyncMock()
            mock_load.return_value.__aenter__ = AsyncMock()
            mock_load.return_value.__aexit__ = AsyncMock()
            mock_ai.generate_tarot_weekly_spread = AsyncMock(
                side_effect=Exception("Generation failed")
            )
            mock_tbk.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_weekly

            await show_tarot_weekly(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Карты молчат" in text


class TestTarotQuestion:
    """Тесты start_tarot_question — callback_data == 'tarot_question'."""

    @pytest.mark.asyncio
    async def test_paywall_for_free_user(
        self, mock_callback, mock_user, mock_state
    ):
        """Free-пользователь видит пэйволл."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot.tarot_paywall_keyboard") as mock_pw,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_pw.return_value = MagicMock()

            from bot.handlers.tarot import start_tarot_question

            await start_tarot_question(mock_callback, mock_state)

        mock_callback.answer.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Этот расклад доступен в полной практике" in text

    @pytest.mark.asyncio
    async def test_sets_state_for_tarot_user(
        self, mock_callback, mock_tarot_user, mock_state
    ):
        """Пользователь с таро переходит в состояние waiting_for_question."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_tarot_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()

            from bot.handlers.tarot import start_tarot_question
            from bot.states.tarot_state import TarotStates

            await start_tarot_question(mock_callback, mock_state)

        mock_state.set_state.assert_awaited_once_with(
            TarotStates.waiting_for_question
        )
        mock_state.update_data.assert_awaited_once_with(spread_type="question")
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Расклад по вопросу" in text


class TestTarotSphereResult:
    """Тесты show_sphere_result — сферы жизни."""

    @pytest.mark.asyncio
    async def test_paywall_for_free_user(
        self, mock_callback, mock_user, mock_state
    ):
        """Free-пользователь видит пэйволл для сфер."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot.tarot_paywall_keyboard") as mock_pw,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_pw.return_value = MagicMock()

            from bot.handlers.tarot import show_sphere_result

            mock_callback.data = "tarot_money"
            await show_sphere_result(mock_callback, mock_state)

        mock_callback.answer.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Этот расклад доступен в полной практике" in text

    @pytest.mark.asyncio
    async def test_shows_sphere_result_for_tarot_user(
        self, mock_callback, mock_tarot_user, mock_state
    ):
        """Успешный расклад сферы."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot._daily_arcana_number") as mock_daily,
            patch("bot.handlers.tarot.AIService") as mock_ai,
            patch("bot.handlers.tarot.animated_loading") as mock_load,
            patch("bot.handlers.tarot.tarot_result_keyboard") as mock_trk,
            patch("bot.handlers.tarot.ARCANA", {
                5: {"name": "Иерофант"},
            }),
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_tarot_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_daily.return_value = 5
            mock_load.return_value = AsyncMock()
            mock_load.return_value.__aenter__ = AsyncMock()
            mock_load.return_value.__aexit__ = AsyncMock()
            mock_ai._load_prompt.return_value = "prompt {sphere_name}"
            mock_ai.chat = AsyncMock(
                return_value="Хороший период для денег."
            )
            mock_trk.return_value = MagicMock()

            from bot.handlers.tarot import show_sphere_result

            mock_callback.data = "tarot_money"
            await show_sphere_result(mock_callback, mock_state)

        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Деньги и реализация" in text

    @pytest.mark.asyncio
    async def test_shows_relations_sphere(
        self, mock_callback, mock_tarot_user, mock_state
    ):
        """Сфера отношений."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot._daily_arcana_number") as mock_daily,
            patch("bot.handlers.tarot.AIService") as mock_ai,
            patch("bot.handlers.tarot.animated_loading") as mock_load,
            patch("bot.handlers.tarot.tarot_result_keyboard") as mock_trk,
            patch("bot.handlers.tarot.ARCANA", {
                5: {"name": "Иерофант"},
            }),
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_tarot_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_daily.return_value = 5
            mock_load.return_value = AsyncMock()
            mock_load.return_value.__aenter__ = AsyncMock()
            mock_load.return_value.__aexit__ = AsyncMock()
            mock_ai._load_prompt.return_value = "prompt {sphere_name}"
            mock_ai.chat = AsyncMock(
                return_value="Гармония в отношениях."
            )
            mock_trk.return_value = MagicMock()

            from bot.handlers.tarot import show_sphere_result

            mock_callback.data = "tarot_sphere_relations"
            await show_sphere_result(mock_callback, mock_state)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Отношения" in text

    @pytest.mark.asyncio
    async def test_shows_purpose_sphere(
        self, mock_callback, mock_tarot_user, mock_state
    ):
        """Сфера предназначения."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot._daily_arcana_number") as mock_daily,
            patch("bot.handlers.tarot.AIService") as mock_ai,
            patch("bot.handlers.tarot.animated_loading") as mock_load,
            patch("bot.handlers.tarot.tarot_result_keyboard") as mock_trk,
            patch("bot.handlers.tarot.ARCANA", {
                5: {"name": "Иерофант"},
            }),
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_tarot_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_daily.return_value = 5
            mock_load.return_value = AsyncMock()
            mock_load.return_value.__aenter__ = AsyncMock()
            mock_load.return_value.__aexit__ = AsyncMock()
            mock_ai._load_prompt.return_value = "prompt {sphere_name}"
            mock_ai.chat = AsyncMock(
                return_value="Твоё предназначение — творить."
            )
            mock_trk.return_value = MagicMock()

            from bot.handlers.tarot import show_sphere_result

            mock_callback.data = "tarot_purpose"
            await show_sphere_result(mock_callback, mock_state)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Предназначение" in text


class TestTarotSpheres:
    """Тесты show_tarot_spheres — callback_data == 'tarot_spheres'."""

    @pytest.mark.asyncio
    async def test_paywall_for_free_user(
        self, mock_callback, mock_user, mock_state
    ):
        """Free-пользователь видит пэйволл."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot.tarot_paywall_keyboard") as mock_pw,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_pw.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_spheres

            await show_tarot_spheres(mock_callback, mock_state)

        mock_callback.answer.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Этот расклад доступен в полной практике" in text

    @pytest.mark.asyncio
    async def test_shows_spheres_for_tarot_user(
        self, mock_callback, mock_tarot_user, mock_state
    ):
        """Пользователь с таро видит клавиатуру сфер."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot.tarot_spheres_keyboard") as mock_sk,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_tarot_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_sk.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_spheres
            from bot.states.tarot_state import TarotStates

            await show_tarot_spheres(mock_callback, mock_state)

        mock_state.set_state.assert_awaited_once_with(
            TarotStates.waiting_for_sphere
        )
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Сферы жизни" in text


class TestTarotTwins:
    """Тесты show_tarot_twins — callback_data == 'tarot_twins'."""

    @pytest.mark.asyncio
    async def test_paywall_for_free_user(
        self, mock_callback, mock_user
    ):
        """Free-пользователь видит пэйволл."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot.tarot_paywall_keyboard") as mock_pw,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_pw.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_twins

            await show_tarot_twins(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Этот расклад доступен в полной практике" in text

    @pytest.mark.asyncio
    async def test_shows_twins_for_tarot_user(
        self, mock_callback, mock_tarot_user
    ):
        """Успешный расклад теневых сторон."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot._daily_arcana_number") as mock_daily,
            patch("bot.handlers.tarot.AIService") as mock_ai,
            patch("bot.handlers.tarot.animated_loading") as mock_load,
            patch("bot.handlers.tarot.tarot_result_keyboard") as mock_trk,
            patch("bot.handlers.tarot.ARCANA", {
                5: {"name": "Иерофант"},
                6: {"name": "Влюблённые"},
            }),
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_tarot_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_daily.return_value = 5
            mock_load.return_value = AsyncMock()
            mock_load.return_value.__aenter__ = AsyncMock()
            mock_load.return_value.__aexit__ = AsyncMock()
            mock_ai._load_prompt.return_value = "prompt {arcana_one_name}"
            mock_ai.chat = AsyncMock(
                return_value="Двойственная энергия."
            )
            mock_trk.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_twins

            await show_tarot_twins(mock_callback)

        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Теневые стороны" in text


class TestTarotPortal:
    """Тесты show_tarot_portal — callback_data == 'tarot_portal'."""

    @pytest.mark.asyncio
    async def test_paywall_for_free_user(
        self, mock_callback, mock_user
    ):
        """Free-пользователь видит пэйволл."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot.tarot_paywall_keyboard") as mock_pw,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_pw.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_portal

            await show_tarot_portal(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Этот расклад доступен в полной практике" in text

    @pytest.mark.asyncio
    async def test_shows_portal_for_tarot_user(
        self, mock_callback, mock_tarot_user
    ):
        """Успешный расклад энергии месяца."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot.AIService") as mock_ai,
            patch("bot.handlers.tarot.animated_loading") as mock_load,
            patch("bot.handlers.tarot.tarot_result_keyboard") as mock_trk,
            patch("bot.handlers.tarot.ARCANA", {
                1: {"name": "Маг"},
                2: {"name": "Жрица"},
                3: {"name": "Императрица"},
            }),
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_tarot_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_load.return_value = AsyncMock()
            mock_load.return_value.__aenter__ = AsyncMock()
            mock_load.return_value.__aexit__ = AsyncMock()
            mock_ai._load_prompt.return_value = "prompt {month_name}"
            mock_ai.chat = AsyncMock(
                return_value="Энергия месяца — рост."
            )
            mock_trk.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_portal

            await show_tarot_portal(mock_callback)

        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Энергия месяца" in text


class TestTarotBlocks:
    """Тесты show_tarot_blocks — callback_data == 'tarot_blocks'."""

    @pytest.mark.asyncio
    async def test_paywall_for_free_user(
        self, mock_callback, mock_user
    ):
        """Free-пользователь видит пэйволл."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot.tarot_paywall_keyboard") as mock_pw,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_pw.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_blocks

            await show_tarot_blocks(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Этот расклад доступен в полной практике" in text

    @pytest.mark.asyncio
    async def test_shows_blocks_for_tarot_user(
        self, mock_callback, mock_tarot_user
    ):
        """Успешный расклад 'Что мешает'."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot._daily_arcana_number") as mock_daily,
            patch("bot.handlers.tarot.AIService") as mock_ai,
            patch("bot.handlers.tarot.animated_loading") as mock_load,
            patch("bot.handlers.tarot.tarot_result_keyboard") as mock_trk,
            patch("bot.handlers.tarot.ARCANA", {
                5: {"name": "Иерофант"},
                15: {"name": "Дьявол"},
                6: {"name": "Влюблённые"},
            }),
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_tarot_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_daily.return_value = 5
            mock_load.return_value = AsyncMock()
            mock_load.return_value.__aenter__ = AsyncMock()
            mock_load.return_value.__aexit__ = AsyncMock()
            mock_ai._load_prompt.return_value = "prompt {block_arcana_name}"
            mock_ai.chat = AsyncMock(
                return_value="Блок — страх перемен."
            )
            mock_trk.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_blocks

            await show_tarot_blocks(mock_callback)

        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Что мешает" in text


class TestTarotYesNo:
    """Тесты start_tarot_yes_no — callback_data == 'tarot_yes_no'."""

    @pytest.mark.asyncio
    async def test_paywall_for_free_user(
        self, mock_callback, mock_user, mock_state
    ):
        """Free-пользователь видит пэйволл."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot.tarot_paywall_keyboard") as mock_pw,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_pw.return_value = MagicMock()

            from bot.handlers.tarot import start_tarot_yes_no

            await start_tarot_yes_no(mock_callback, mock_state)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Этот расклад доступен в полной практике" in text

    @pytest.mark.asyncio
    async def test_sets_state_for_tarot_user(
        self, mock_callback, mock_tarot_user, mock_state
    ):
        """Пользователь с таро переходит в состояние yes_no."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_tarot_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()

            from bot.handlers.tarot import start_tarot_yes_no
            from bot.states.tarot_state import TarotStates

            await start_tarot_yes_no(mock_callback, mock_state)

        mock_state.set_state.assert_awaited_once_with(
            TarotStates.waiting_for_question
        )
        mock_state.update_data.assert_awaited_once_with(spread_type="yes_no")
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Да/Нет" in text


class TestTarotQuestionInput:
    """Тесты handle_question_input — ввод вопроса пользователем."""

    @pytest.mark.asyncio
    async def test_no_text_shows_prompt(
        self, mock_message, mock_state
    ):
        """Пустой текст — просьба ввести текст."""
        mock_message.text = None

        from bot.handlers.tarot import handle_question_input

        await handle_question_input(mock_message, mock_state)

        mock_message.answer.assert_awaited_once()
        text = mock_message.answer.await_args[0][0]
        assert "текстом" in text

    @pytest.mark.asyncio
    async def test_yes_no_spread(
        self, mock_message, mock_state
    ):
        """Расклад Да/Нет — успешный сценарий."""
        mock_message.text = "Стоит ли менять работу?"

        with (
            patch("bot.handlers.tarot._daily_arcana_number") as mock_daily,
            patch("bot.handlers.tarot.AIService") as mock_ai,
            patch("bot.handlers.tarot.animated_loading") as mock_load,
            patch("bot.handlers.tarot.tarot_result_keyboard") as mock_trk,
            patch("bot.handlers.tarot.ARCANA", {
                5: {"name": "Иерофант"},
            }),
        ):
            mock_state.get_data = AsyncMock(
                return_value={"spread_type": "yes_no"}
            )
            mock_daily.return_value = 5
            mock_load.return_value = AsyncMock()
            mock_load.return_value.__aenter__ = AsyncMock()
            mock_load.return_value.__aexit__ = AsyncMock()
            mock_ai._load_prompt.return_value = (
                "prompt {question} {arcana_number}"
            )
            mock_ai.chat = AsyncMock(return_value="Да, сейчас хорошее время.")
            mock_trk.return_value = MagicMock()

            from bot.handlers.tarot import handle_question_input

            await handle_question_input(mock_message, mock_state)

        mock_message.answer.assert_awaited_once()
        text = mock_message.answer.await_args[0][0]
        assert "Да/Нет" in text
        assert "менять работу" in text
        mock_state.clear.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_question_spread(
        self, mock_message, mock_state
    ):
        """Расклад по вопросу (прошлое/настоящее/будущее) — успешный сценарий."""
        mock_message.text = "Как пройдёт встреча?"

        with (
            patch("bot.handlers.tarot._daily_arcana_number") as mock_daily,
            patch("bot.handlers.tarot.AIService") as mock_ai,
            patch("bot.handlers.tarot.animated_loading") as mock_load,
            patch("bot.handlers.tarot.tarot_result_keyboard") as mock_trk,
            patch("bot.handlers.tarot.ARCANA", {
                5: {"name": "Иерофант"},
                4: {"name": "Император"},
                6: {"name": "Влюблённые"},
            }),
        ):
            mock_state.get_data = AsyncMock(
                return_value={"spread_type": "question"}
            )
            mock_daily.return_value = 5
            mock_load.return_value = AsyncMock()
            mock_load.return_value.__aenter__ = AsyncMock()
            mock_load.return_value.__aexit__ = AsyncMock()
            mock_ai._load_prompt.return_value = (
                "prompt {question} {past_arcana}"
            )
            mock_ai.chat = AsyncMock(
                return_value="Прошлое готовит почву."
            )
            mock_trk.return_value = MagicMock()

            from bot.handlers.tarot import handle_question_input

            await handle_question_input(mock_message, mock_state)

        mock_message.answer.assert_awaited_once()
        text = mock_message.answer.await_args[0][0]
        assert "Расклад по вопросу" in text
        assert "встреча" in text
        assert "Прошлое" in text
        assert "Настоящее" in text
        assert "Будущее" in text

    @pytest.mark.asyncio
    async def test_yes_no_ai_failure(
        self, mock_message, mock_state
    ):
        """Ошибка AI при Да/Нет — фоллбек."""
        mock_message.text = "Купить квартиру?"

        with (
            patch("bot.handlers.tarot._daily_arcana_number") as mock_daily,
            patch("bot.handlers.tarot.AIService") as mock_ai,
            patch("bot.handlers.tarot.animated_loading") as mock_load,
            patch("bot.handlers.tarot.tarot_back_keyboard") as mock_tbk,
            patch("bot.handlers.tarot.ARCANA", {
                5: {"name": "Иерофант"},
            }),
        ):
            mock_state.get_data = AsyncMock(
                return_value={"spread_type": "yes_no"}
            )
            mock_daily.return_value = 5
            mock_load.return_value = AsyncMock()
            mock_load.return_value.__aenter__ = AsyncMock()
            mock_load.return_value.__aexit__ = AsyncMock()
            mock_ai._load_prompt.return_value = "prompt"
            mock_ai.chat = AsyncMock(side_effect=Exception("API error"))
            mock_tbk.return_value = MagicMock()

            from bot.handlers.tarot import handle_question_input

            await handle_question_input(mock_message, mock_state)

        mock_message.answer.assert_awaited_once()
        text = mock_message.answer.await_args[0][0]
        assert "Карты молчат" in text
        mock_state.clear.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_question_ai_failure(
        self, mock_message, mock_state
    ):
        """Ошибка AI при раскладе по вопросу — фоллбек."""
        mock_message.text = "Что делать с проектом?"

        with (
            patch("bot.handlers.tarot._daily_arcana_number") as mock_daily,
            patch("bot.handlers.tarot.AIService") as mock_ai,
            patch("bot.handlers.tarot.animated_loading") as mock_load,
            patch("bot.handlers.tarot.tarot_back_keyboard") as mock_tbk,
            patch("bot.handlers.tarot.ARCANA", {
                4: {"name": "Император"},
                5: {"name": "Иерофант"},
                6: {"name": "Влюблённые"},
            }),
        ):
            mock_state.get_data = AsyncMock(
                return_value={"spread_type": "question"}
            )
            mock_daily.return_value = 5
            mock_load.return_value = AsyncMock()
            mock_load.return_value.__aenter__ = AsyncMock()
            mock_load.return_value.__aexit__ = AsyncMock()
            mock_ai._load_prompt.return_value = "prompt"
            mock_ai.chat = AsyncMock(side_effect=Exception("API error"))
            mock_tbk.return_value = MagicMock()

            from bot.handlers.tarot import handle_question_input

            await handle_question_input(mock_message, mock_state)

        mock_message.answer.assert_awaited_once()
        text = mock_message.answer.await_args[0][0]
        assert "Карты молчат" in text
        mock_state.clear.assert_awaited_once()


# =====================================================================
# START HANDLER TESTS
# =====================================================================


class TestCmdStart:
    """Тесты cmd_start — команда /start."""

    @pytest.mark.asyncio
    async def test_new_user_starts_onboarding(
        self, mock_message, mock_state, mock_command
    ):
        """Новый пользователь без birth_date — видит онбординг."""
        with (
            patch("bot.handlers.start.UserRepository") as MockRepo,
            patch("bot.handlers.start.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.start.onboarding_greeting_text") as mock_greet,
            patch("bot.handlers.start.ask_birth_date_onboarding_text") as mock_ask,
            patch("bot.handlers.start.OnboardingStates"),
        ):
            repo_instance = MagicMock()
            new_user = MagicMock(
                birth_date=None,
                main_archetype="Маг",
            )
            repo_instance.get_or_create_by_telegram_id = AsyncMock(return_value=new_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_greet.return_value = "Привет!"
            mock_ask.return_value = "Введи дату рождения:"

            from bot.handlers.start import cmd_start

            await cmd_start(mock_message, mock_state, mock_command)

        mock_message.answer.assert_awaited()
        mock_state.set_state.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_existing_user_shows_menu(
        self, mock_message, mock_state, mock_command
    ):
        """Существующий пользователь с birth_date — сразу в меню."""
        with (
            patch("bot.handlers.start.UserRepository") as MockRepo,
            patch("bot.handlers.start.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.start.welcome_back_text") as mock_wb,
            patch("bot.handlers.start.main_menu_keyboard") as mock_mm,
        ):
            existing_user = MagicMock()
            existing_user.birth_date = "01.01.2000"
            existing_user.main_archetype = "Маг"
            existing_user.first_name = "Test"
            existing_user.username = "testuser"
            existing_user.has_matrix = True
            existing_user.tarot_subscription = False
            existing_user.subscription_status = "free"

            repo_instance = MagicMock()
            repo_instance.get_or_create_by_telegram_id = AsyncMock(
                return_value=existing_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_wb.return_value = "С возвращением!"
            mock_mm.return_value = MagicMock()

            from bot.handlers.start import cmd_start

            await cmd_start(mock_message, mock_state, mock_command)

        mock_message.answer.assert_awaited_once()
        mock_state.clear.assert_awaited_once()
        text = mock_message.answer.await_args[0][0]
        assert "С возвращением" in text

    @pytest.mark.asyncio
    async def test_referral_link_handled(
        self, mock_message, mock_state
    ):
        """Реферальная ссылка start=ref_ обрабатывается."""
        mock_command = MagicMock()
        mock_command.args = "ref_123456"

        with (
            patch("bot.handlers.start.UserRepository") as MockRepo,
            patch("bot.handlers.start.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.start._handle_referral") as mock_hr,
        ):
            existing_user = MagicMock()
            existing_user.birth_date = "01.01.2000"
            existing_user.main_archetype = "Маг"

            repo_instance = MagicMock()
            repo_instance.get_or_create_by_telegram_id = AsyncMock(
                return_value=existing_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_hr.return_value = None

            from bot.handlers.start import cmd_start

            await cmd_start(mock_message, mock_state, mock_command)

        # Проверяем, что _handle_referral был вызван
        mock_hr.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_link_token_handled(
        self, mock_message, mock_state
    ):
        """Ссылка link_ обрабатывается."""
        mock_command = MagicMock()
        mock_command.args = "link_sometoken123"

        with (
            patch("bot.handlers.start._handle_link_token") as mock_hlt,
        ):
            from bot.handlers.start import cmd_start

            await cmd_start(mock_message, mock_state, mock_command)

        mock_hlt.assert_awaited_once_with(mock_message, "sometoken123")


class TestCmdMenu:
    """Тесты cmd_menu — команда /menu."""

    @pytest.mark.asyncio
    async def test_user_without_birth_date(
        self, mock_message, mock_state
    ):
        """Пользователь без birth_date — просьба ввести /start."""
        with (
            patch("bot.handlers.start.UserRepository") as MockRepo,
            patch("bot.handlers.start.get_async_sessionmaker") as mock_gsm,
        ):
            user_no_bd = MagicMock()
            user_no_bd.birth_date = None

            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=user_no_bd
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()

            from bot.handlers.start import cmd_menu

            await cmd_menu(mock_message, mock_state)

        mock_message.answer.assert_awaited_once()
        text = mock_message.answer.await_args[0][0]
        assert "Напиши /start" in text

    @pytest.mark.asyncio
    async def test_user_with_birth_date_sees_menu(
        self, mock_message, mock_state
    ):
        """Пользователь с birth_date видит главное меню."""
        with (
            patch("bot.handlers.start.UserRepository") as MockRepo,
            patch("bot.handlers.start.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.start.welcome_back_text") as mock_wb,
            patch("bot.handlers.start.main_menu_keyboard") as mock_mm,
        ):
            user = MagicMock()
            user.birth_date = "01.01.2000"
            user.main_archetype = "Маг"
            user.first_name = "Test"
            user.username = "testuser"
            user.has_matrix = True
            user.tarot_subscription = False
            user.subscription_status = "free"

            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_wb.return_value = "Меню!"
            mock_mm.return_value = MagicMock()

            from bot.handlers.start import cmd_menu

            await cmd_menu(mock_message, mock_state)

        mock_message.answer.assert_awaited_once()
        text = mock_message.answer.await_args[0][0]
        assert "Меню" in text

    @pytest.mark.asyncio
    async def test_user_not_found(
        self, mock_message, mock_state
    ):
        """Пользователь не найден — просьба ввести /start."""
        with (
            patch("bot.handlers.start.UserRepository") as MockRepo,
            patch("bot.handlers.start.get_async_sessionmaker") as mock_gsm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=None)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()

            from bot.handlers.start import cmd_menu

            await cmd_menu(mock_message, mock_state)

        mock_message.answer.assert_awaited_once()
        text = mock_message.answer.await_args[0][0]
        assert "Напиши /start" in text


class TestCmdHelp:
    """Тесты cmd_help — команда /help."""

    @pytest.mark.asyncio
    async def test_shows_help_text(self, mock_message):
        """Показывает справку."""
        with (
            patch("bot.handlers.start.help_text") as mock_ht,
        ):
            mock_ht.return_value = "Справка NURA"

            from bot.handlers.start import cmd_help

            await cmd_help(mock_message)

        mock_message.answer.assert_awaited_once_with("Справка NURA")


class TestCallbackMainMenu:
    """Тесты callback_main_menu — callback_data == 'main_menu'."""

    @pytest.mark.asyncio
    async def test_shows_main_menu(
        self, mock_callback, mock_state
    ):
        """Показывает главное меню."""
        with (
            patch("bot.handlers.start.UserRepository") as MockRepo,
            patch("bot.handlers.start.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.start.welcome_back_text") as mock_wb,
            patch("bot.handlers.start.main_menu_keyboard") as mock_mm,
        ):
            user = MagicMock()
            user.birth_date = "01.01.2000"
            user.main_archetype = "Маг"
            user.first_name = "Test"
            user.username = "testuser"
            user.tarot_subscription = False
            user.subscription_status = "free"

            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_wb.return_value = "Главное меню"
            mock_mm.return_value = MagicMock()

            from bot.handlers.start import callback_main_menu

            await callback_main_menu(mock_callback, mock_state)

        mock_callback.answer.assert_awaited_once()
        mock_state.clear.assert_awaited_once()
        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Главное меню" in text

    @pytest.mark.asyncio
    async def test_no_birth_date_shows_start_prompt(
        self, mock_callback, mock_state
    ):
        """Без birth_date — просьба ввести /start."""
        with (
            patch("bot.handlers.start.UserRepository") as MockRepo,
            patch("bot.handlers.start.get_async_sessionmaker") as mock_gsm,
        ):
            user = MagicMock()
            user.birth_date = None

            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()

            from bot.handlers.start import callback_main_menu

            await callback_main_menu(mock_callback, mock_state)

        mock_callback.message.answer.assert_awaited_once()
        text = mock_callback.message.answer.await_args[0][0]
        assert "Напиши /start" in text


class TestCallbackSampleReport:
    """Тесты callback_sample_report."""

    @pytest.mark.asyncio
    async def test_shows_sample_report(self, mock_callback):
        """Показывает пример отчёта."""
        with (
            patch("bot.handlers.start.InlineKeyboardMarkup") as mock_ikm,
            patch("bot.handlers.start.InlineKeyboardButton") as mock_ikb,
        ):
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.start import callback_sample_report

            await callback_sample_report(mock_callback)

        mock_callback.answer.assert_awaited_once()
        mock_callback.message.answer.assert_awaited_once()
        text = mock_callback.message.answer.await_args[0][0]
        assert "Пример полного отчёта" in text


# =====================================================================
# PROFILE HANDLER TESTS
# =====================================================================


class TestProfile:
    """Тесты profile handler."""

    @pytest.mark.asyncio
    async def test_callback_profile_shows(
        self, mock_callback
    ):
        """callback_profile показывает профиль."""
        with (
            patch("bot.handlers.profile.UserRepository") as MockRepo,
            patch("bot.handlers.profile.ReportRepository") as MockReportRepo,
            patch("bot.handlers.profile.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.profile.profile_mini_text") as mock_pmt,
            patch("bot.handlers.profile.profile_keyboard") as mock_pk,
        ):
            user = MagicMock()
            user.first_name = "Test"
            user.main_archetype = "Маг"
            user.subscription_status = "free"
            user.tarot_subscription = False
            user.telegram_id = 123456789
            user.birth_date = "01.01.2000"

            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=user)
            MockRepo.return_value = repo_instance

            report_repo_instance = MagicMock()
            report_repo_instance.get_by_user_id = AsyncMock(return_value=[])
            MockReportRepo.return_value = report_repo_instance

            mock_gsm.return_value = MagicMock()
            mock_pmt.return_value = "Профиль пользователя"
            mock_pk.return_value = MagicMock()

            from bot.handlers.profile import callback_profile

            await callback_profile(mock_callback)

        mock_callback.answer.assert_awaited_once()
        # _show_profile вызывает message.answer (не edit_text)
        mock_callback.message.answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_view_reports_empty(
        self, mock_callback
    ):
        """view_reports без отчётов."""
        with (
            patch("bot.handlers.profile.UserRepository") as MockRepo,
            patch("bot.handlers.profile.ReportRepository") as MockReportRepo,
            patch("bot.handlers.profile.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.profile.reports_list_text") as mock_rlt,
            patch("bot.handlers.profile.reports_keyboard") as mock_rk,
        ):
            user = MagicMock()
            user.first_name = "Test"

            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=user)
            MockRepo.return_value = repo_instance

            report_repo_instance = MagicMock()
            report_repo_instance.get_by_user_id = AsyncMock(return_value=[])
            MockReportRepo.return_value = report_repo_instance

            mock_gsm.return_value = MagicMock()
            mock_rlt.return_value = "Нет отчётов"
            mock_rk.return_value = MagicMock()

            from bot.handlers.profile import view_reports

            await view_reports(mock_callback)

        mock_callback.answer.assert_awaited_once()
        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Нет отчётов" in text

    @pytest.mark.asyncio
    async def test_view_reports_with_reports(
        self, mock_callback
    ):
        """view_reports с отчётами."""
        from datetime import datetime, timezone

        mock_report = MagicMock()
        mock_report.token = "token-123"
        mock_report.report_type = "full"
        mock_report.created_at = datetime.now(timezone.utc)

        with (
            patch("bot.handlers.profile.UserRepository") as MockRepo,
            patch("bot.handlers.profile.ReportRepository") as MockReportRepo,
            patch("bot.handlers.profile.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.profile.reports_list_text") as mock_rlt,
            patch("bot.handlers.profile.reports_keyboard") as mock_rk,
        ):
            user = MagicMock()
            user.first_name = "Test"

            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=user)
            MockRepo.return_value = repo_instance

            report_repo_instance = MagicMock()
            report_repo_instance.get_by_user_id = AsyncMock(
                return_value=[mock_report]
            )
            MockReportRepo.return_value = report_repo_instance

            mock_gsm.return_value = MagicMock()
            mock_rlt.return_value = "Список отчётов"
            mock_rk.return_value = MagicMock()

            from bot.handlers.profile import view_reports

            await view_reports(mock_callback)

        mock_callback.answer.assert_awaited_once()
        mock_callback.message.edit_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_show_subscription(
        self, mock_callback
    ):
        """show_subscription показывает предложение подписки."""
        with (
            patch("bot.handlers.profile.subscription_offer_text") as mock_sot,
            patch("bot.handlers.profile.subscription_keyboard") as mock_sk,
        ):
            mock_sot.return_value = "Оформи подписку!"
            mock_sk.return_value = MagicMock()

            from bot.handlers.profile import show_subscription

            await show_subscription(mock_callback)

        mock_callback.answer.assert_awaited_once()
        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Оформи подписку" in text

    @pytest.mark.asyncio
    async def test_manage_subscription(
        self, mock_callback
    ):
        """manage_subscription показывает управление."""
        with (
            patch("bot.handlers.profile.UserRepository") as MockRepo,
            patch("bot.handlers.profile.ReportRepository") as MockReportRepo,
            patch("bot.handlers.profile.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.profile.InlineKeyboardMarkup") as mock_ikm,
            patch("bot.handlers.profile.InlineKeyboardButton") as mock_ikb,
        ):
            user = MagicMock()
            user.subscription_until = datetime.now(timezone.utc) + timedelta(days=30)

            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=user)
            MockRepo.return_value = repo_instance

            report_repo_instance = MagicMock()
            report_repo_instance.get_by_user_id = AsyncMock(return_value=[])
            MockReportRepo.return_value = report_repo_instance
            mock_gsm.return_value = MagicMock()
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.profile import manage_subscription

            await manage_subscription(mock_callback)

        mock_callback.answer.assert_awaited_once()
        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Управление подпиской" in text

    @pytest.mark.asyncio
    async def test_cancel_subscription_confirm(
        self, mock_callback
    ):
        """cancel_subscription_confirm показывает подтверждение."""
        with (
            patch("bot.handlers.profile.InlineKeyboardMarkup") as mock_ikm,
            patch("bot.handlers.profile.InlineKeyboardButton") as mock_ikb,
        ):
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.profile import cancel_subscription_confirm

            await cancel_subscription_confirm(mock_callback)

        mock_callback.answer.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Подтверди отмену" in text

    @pytest.mark.asyncio
    async def test_cancel_subscription_do(
        self, mock_callback
    ):
        """cancel_subscription_do отменяет подписку."""
        with (
            patch("bot.handlers.profile.UserRepository") as MockRepo,
            patch("bot.handlers.profile.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.profile.InlineKeyboardMarkup") as mock_ikm,
            patch("bot.handlers.profile.InlineKeyboardButton") as mock_ikb,
        ):
            user = MagicMock()
            user.subscription_until = datetime.now(timezone.utc) + timedelta(days=30)

            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=user)
            MockRepo.return_value = repo_instance

            mock_gsm.return_value = MagicMock()
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.profile import cancel_subscription_do

            await cancel_subscription_do(mock_callback)

        mock_callback.answer.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Подписка отменена" in text

    @pytest.mark.asyncio
    async def test_show_support(
        self, mock_callback
    ):
        """show_support показывает контакты поддержки."""
        with (
            patch("bot.handlers.profile.InlineKeyboardMarkup") as mock_ikm,
            patch("bot.handlers.profile.InlineKeyboardButton") as mock_ikb,
        ):
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.profile import show_support

            await show_support(mock_callback)

        mock_callback.answer.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Поддержка NURA" in text

    @pytest.mark.asyncio
    async def test_back_to_profile(
        self, mock_callback
    ):
        """back_to_profile возвращает в профиль."""
        with (
            patch("bot.handlers.profile.UserRepository") as MockRepo,
            patch("bot.handlers.profile.ReportRepository") as MockReportRepo,
            patch("bot.handlers.profile.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.profile.profile_mini_text") as mock_pmt,
            patch("bot.handlers.profile.profile_keyboard") as mock_pk,
        ):
            user = MagicMock()
            user.first_name = "Test"
            user.main_archetype = "Маг"
            user.subscription_status = "free"
            user.tarot_subscription = False
            user.telegram_id = 123456789
            user.birth_date = "01.01.2000"

            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=user)
            MockRepo.return_value = repo_instance

            report_repo_instance = MagicMock()
            report_repo_instance.get_by_user_id = AsyncMock(return_value=[])
            MockReportRepo.return_value = report_repo_instance

            mock_gsm.return_value = MagicMock()
            mock_pmt.return_value = "Профиль"
            mock_pk.return_value = MagicMock()

            from bot.handlers.profile import back_to_profile

            await back_to_profile(mock_callback)

        mock_callback.answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cmd_profile_shows(
        self, mock_message
    ):
        """cmd_profile показывает профиль."""
        with (
            patch("bot.handlers.profile.UserRepository") as MockRepo,
            patch("bot.handlers.profile.ReportRepository") as MockReportRepo,
            patch("bot.handlers.profile.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.profile.profile_mini_text") as mock_pmt,
            patch("bot.handlers.profile.profile_keyboard") as mock_pk,
        ):
            user = MagicMock()
            user.first_name = "Test"
            user.main_archetype = "Маг"
            user.subscription_status = "free"
            user.tarot_subscription = False
            user.telegram_id = 123456789
            user.birth_date = "01.01.2000"

            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=user)
            MockRepo.return_value = repo_instance

            report_repo_instance = MagicMock()
            report_repo_instance.get_by_user_id = AsyncMock(return_value=[])
            MockReportRepo.return_value = report_repo_instance

            mock_gsm.return_value = MagicMock()
            mock_pmt.return_value = "Профиль через команду"
            mock_pk.return_value = MagicMock()

            from bot.handlers.profile import cmd_profile

            await cmd_profile(mock_message)

        mock_message.answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_profile_user_not_found(
        self, mock_message
    ):
        """cmd_profile для ненайденного пользователя."""
        with (
            patch("bot.handlers.profile.UserRepository") as MockRepo,
            patch("bot.handlers.profile.ReportRepository") as MockReportRepo,
            patch("bot.handlers.profile.get_async_sessionmaker") as mock_gsm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=None)
            MockRepo.return_value = repo_instance

            MockReportRepo.return_value = MagicMock()
            mock_gsm.return_value = MagicMock()

            from bot.handlers.profile import cmd_profile

            await cmd_profile(mock_message)

        mock_message.answer.assert_awaited_once()
        text = mock_message.answer.await_args[0][0]
        assert "Пользователь не найден" in text


# =====================================================================
# PAYMENT HANDLER TESTS
# =====================================================================


class TestBuySubscription:
    """Тесты initiate_subscription — callback_data == 'buy_subscription'."""

    @pytest.mark.asyncio
    async def test_user_not_found(
        self, mock_callback
    ):
        """Пользователь не найден."""
        with (
            patch("bot.handlers.payment.UserRepository") as MockRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.main_menu_keyboard") as mock_mm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=None)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_mm.return_value = MagicMock()

            from bot.handlers.payment import initiate_subscription

            await initiate_subscription(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Пользователь не найден" in text

    @pytest.mark.asyncio
    async def test_already_premium(
        self, mock_callback, mock_premium_user
    ):
        """Premium-пользователь видит сообщение об активности."""
        with (
            patch("bot.handlers.payment.UserRepository") as MockRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.main_menu_keyboard") as mock_mm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_premium_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_mm.return_value = MagicMock()

            from bot.handlers.payment import initiate_subscription

            await initiate_subscription(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Подписка уже активна" in text

    @pytest.mark.asyncio
    async def test_test_mode_activates(
        self, mock_callback, mock_user
    ):
        """Тестовый режим активирует подписку."""
        mock_user.birth_date = None  # не триггерим ReportRepository

        with (
            patch("bot.handlers.payment.UserRepository") as MockRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.main_menu_keyboard") as mock_mm,
            patch("bot.handlers.payment.settings") as mock_settings,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            repo_instance.update_subscription = AsyncMock()
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_mm.return_value = MagicMock()
            mock_settings.test_mode = True

            from bot.handlers.payment import initiate_subscription

            await initiate_subscription(mock_callback)

        repo_instance.update_subscription.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Подписка активирована" in text

    @pytest.mark.asyncio
    async def test_creates_payment_url(
        self, mock_callback, mock_user
    ):
        """Создаёт платёж и возвращает URL."""
        with (
            patch("bot.handlers.payment.UserRepository") as MockRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.PaymentService") as mock_ps,
            patch("bot.handlers.payment.main_menu_keyboard") as mock_mm,
            patch("bot.handlers.payment.settings") as mock_settings,
            patch("bot.handlers.payment.InlineKeyboardMarkup") as mock_ikm,
            patch("bot.handlers.payment.InlineKeyboardButton") as mock_ikb,
            patch("bot.handlers.payment.payment_pending_text") as mock_ppt,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_settings.test_mode = False
            mock_ps.create_subscription = AsyncMock(
                return_value={
                    "payment_url": "https://pay.example.com",
                    "id": "pm-123",
                }
            )
            mock_mm.return_value = MagicMock()
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()
            mock_ppt.return_value = "Платёж создан"

            from bot.handlers.payment import initiate_subscription

            await initiate_subscription(mock_callback)

        mock_callback.message.edit_text.assert_awaited()
        # Должен быть answer с pending текстом
        mock_callback.message.answer.assert_awaited_once()


class TestBuyTarotSubscription:
    """Тесты initiate_tarot_subscription — callback_data == 'buy_tarot_subscription'."""

    @pytest.mark.asyncio
    async def test_user_not_found(
        self, mock_callback
    ):
        """Пользователь не найден."""
        with (
            patch("bot.handlers.payment.UserRepository") as MockRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.main_menu_keyboard") as mock_mm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=None)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_mm.return_value = MagicMock()

            from bot.handlers.payment import initiate_tarot_subscription

            await initiate_tarot_subscription(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Пользователь не найден" in text

    @pytest.mark.asyncio
    async def test_already_active(
        self, mock_callback, mock_tarot_user
    ):
        """Таро-подписка уже активна."""
        with (
            patch("bot.handlers.payment.UserRepository") as MockRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.main_menu_keyboard") as mock_mm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_tarot_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_mm.return_value = MagicMock()

            from bot.handlers.payment import initiate_tarot_subscription

            await initiate_tarot_subscription(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Таро-подписка уже активна" in text

    @pytest.mark.asyncio
    async def test_test_mode_activates(
        self, mock_callback, mock_user
    ):
        """Тестовый режим активирует таро."""
        with (
            patch("bot.handlers.payment.UserRepository") as MockRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.main_menu_keyboard") as mock_mm,
            patch("bot.handlers.payment.settings") as mock_settings,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            repo_instance.update_tarot_subscription = AsyncMock()
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_mm.return_value = MagicMock()
            mock_settings.test_mode = True

            from bot.handlers.payment import initiate_tarot_subscription

            await initiate_tarot_subscription(mock_callback)

        repo_instance.update_tarot_subscription.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Таро-подписка активирована" in text

    @pytest.mark.asyncio
    async def test_creates_payment(
        self, mock_callback, mock_user
    ):
        """Создаёт платёж для таро."""
        with (
            patch("bot.handlers.payment.UserRepository") as MockRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.PaymentService") as mock_ps,
            patch("bot.handlers.payment.main_menu_keyboard") as mock_mm,
            patch("bot.handlers.payment.settings") as mock_settings,
            patch("bot.handlers.payment.InlineKeyboardMarkup") as mock_ikm,
            patch("bot.handlers.payment.InlineKeyboardButton") as mock_ikb,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_settings.test_mode = False
            mock_ps.create_subscription = AsyncMock(
                return_value={
                    "payment_url": "https://pay.example.com",
                    "id": "pm-456",
                }
            )
            mock_mm.return_value = MagicMock()
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.payment import initiate_tarot_subscription

            await initiate_tarot_subscription(mock_callback)

        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Таро-подписка — 390" in text


class TestBuyMatrix:
    """Тесты buy_matrix — callback_data == 'buy_matrix'."""

    @pytest.mark.asyncio
    async def test_user_not_found(
        self, mock_callback
    ):
        """Пользователь не найден."""
        with (
            patch("bot.handlers.payment.UserRepository") as MockRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.main_menu_keyboard") as mock_mm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=None)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_mm.return_value = MagicMock()

            from bot.handlers.payment import buy_matrix

            await buy_matrix(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Пользователь не найден" in text

    @pytest.mark.asyncio
    async def test_already_has_matrix(
        self, mock_callback, mock_user
    ):
        """Матрица уже куплена."""
        mock_user.has_matrix = True

        with (
            patch("bot.handlers.payment.UserRepository") as MockRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.main_menu_keyboard") as mock_mm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_mm.return_value = MagicMock()

            from bot.handlers.payment import buy_matrix

            await buy_matrix(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Матрица уже куплена" in text

    @pytest.mark.asyncio
    async def test_test_mode_activates(
        self, mock_callback, mock_user
    ):
        """Тестовый режим активирует матрицу и ставит отчёт в очередь."""
        with (
            patch("bot.handlers.payment.UserRepository") as MockRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.main_menu_keyboard") as mock_mm,
            patch("bot.handlers.payment.settings") as mock_settings,
            patch("core.repositories.report.ReportRepository") as MockReportRepo,
            patch("core.tasks.generate_full_report") as mock_gen_report,
            patch("core.services.report.ReportService") as MockReportService,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            repo_instance.update_has_matrix = AsyncMock()
            MockRepo.return_value = repo_instance
            report_repo_instance = MagicMock()
            report_repo_instance.get_by_user_id_and_type = AsyncMock(return_value=None)
            MockReportRepo.return_value = report_repo_instance
            mock_gsm.return_value = MagicMock()
            mock_mm.return_value = MagicMock()
            mock_settings.test_mode = True
            mock_gen_report.delay = MagicMock()
            MockReportService.generate_token.return_value = "report-token-abc"

            from bot.handlers.payment import buy_matrix

            await buy_matrix(mock_callback)

        repo_instance.update_has_matrix.assert_awaited_once()
        report_repo_instance.get_by_user_id_and_type.assert_awaited_once()
        mock_gen_report.delay.assert_called_once_with(
            str(mock_user.id), mock_user.birth_date, "report-token-abc"
        )
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Тест-режим" in text

    @pytest.mark.asyncio
    async def test_creates_matrix_payment(
        self, mock_callback, mock_user
    ):
        """Создаёт платёж для матрицы."""
        mock_user.birth_date = None  # не триггерим ReportRepository внутри test_mode

        with (
            patch("bot.handlers.payment.UserRepository") as MockRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.PaymentService") as mock_ps,
            patch("bot.handlers.payment.main_menu_keyboard") as mock_mm,
            patch("bot.handlers.payment.settings") as mock_settings,
            patch("bot.handlers.payment.InlineKeyboardMarkup") as mock_ikm,
            patch("bot.handlers.payment.InlineKeyboardButton") as mock_ikb,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_settings.test_mode = False
            mock_ps.create_matrix_payment = AsyncMock(
                return_value={
                    "id": "pm-789",
                    "payment_url": "https://pay.example.com/890",
                }
            )
            mock_ps.save_matrix_payment = AsyncMock()
            mock_mm.return_value = MagicMock()
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.payment import buy_matrix

            await buy_matrix(mock_callback)

        mock_ps.create_matrix_payment.assert_awaited_once()
        mock_ps.save_matrix_payment.assert_awaited_once()
        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Матрица Судьбы — 890" in text

    @pytest.mark.asyncio
    async def test_payment_service_value_error(
        self, mock_callback, mock_user
    ):
        """ValueError при создании платежа."""
        with (
            patch("bot.handlers.payment.UserRepository") as MockRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.PaymentService") as mock_ps,
            patch("bot.handlers.payment.main_menu_keyboard") as mock_mm,
            patch("bot.handlers.payment.settings") as mock_settings,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_settings.test_mode = False
            mock_ps.create_matrix_payment = AsyncMock(
                side_effect=ValueError("Invalid payment")
            )
            mock_mm.return_value = MagicMock()

            from bot.handlers.payment import buy_matrix

            await buy_matrix(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Оплата временно недоступна" in text


class TestOpenReport:
    """Тесты open_report — callback_data.startswith('open_report:')."""

    @pytest.mark.asyncio
    async def test_report_not_found(
        self, mock_callback
    ):
        """Отчёт не найден."""
        mock_callback.data = "open_report:invalid-token"

        with (
            patch("bot.handlers.payment.ReportRepository") as MockReportRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.main_menu_keyboard") as mock_mm,
        ):
            report_repo_instance = MagicMock()
            report_repo_instance.get_by_token = AsyncMock(return_value=None)
            MockReportRepo.return_value = report_repo_instance
            mock_gsm.return_value = MagicMock()
            mock_mm.return_value = MagicMock()

            from bot.handlers.payment import open_report

            await open_report(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Отчёт не найден" in text

    @pytest.mark.asyncio
    async def test_shows_report_buttons(
        self, mock_callback
    ):
        """Открывает отчёт с кнопками."""
        mock_report = MagicMock()
        mock_report.token = "valid-token"
        mock_report.matrix_data = {"archetype_name": "Маг"}
        mock_report.kitchen_analysis = None

        mock_callback.data = "open_report:valid-token"

        with (
            patch("bot.handlers.payment.ReportRepository") as MockReportRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.report_ready_pwa_text") as mock_rpt,
            patch("bot.handlers.payment.InlineKeyboardMarkup") as mock_ikm,
            patch("bot.handlers.payment.InlineKeyboardButton") as mock_ikb,
        ):
            report_repo_instance = MagicMock()
            report_repo_instance.get_by_token = AsyncMock(
                return_value=mock_report
            )
            MockReportRepo.return_value = report_repo_instance
            mock_gsm.return_value = MagicMock()
            mock_rpt.return_value = "Отчёт готов"
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.payment import open_report

            await open_report(mock_callback)

        mock_callback.message.answer.assert_awaited_once()
        text = mock_callback.message.answer.await_args[0][0]
        assert "Отчёт готов" in text

    @pytest.mark.asyncio
    async def test_shows_kitchen_button_if_available(
        self, mock_callback
    ):
        """Если есть kitchen_analysis — показываем кнопку."""
        mock_report = MagicMock()
        mock_report.token = "kitchen-token"
        mock_report.matrix_data = {"archetype_name": "Маг"}
        mock_report.kitchen_analysis = {"main_archetype": {"logic": "test"}}

        mock_callback.data = "open_report:kitchen-token"

        with (
            patch("bot.handlers.payment.ReportRepository") as MockReportRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.report_ready_pwa_text") as mock_rpt,
            patch("bot.handlers.payment.InlineKeyboardMarkup") as mock_ikm,
            patch("bot.handlers.payment.InlineKeyboardButton") as mock_ikb,
        ):
            report_repo_instance = MagicMock()
            report_repo_instance.get_by_token = AsyncMock(
                return_value=mock_report
            )
            MockReportRepo.return_value = report_repo_instance
            mock_gsm.return_value = MagicMock()
            mock_rpt.return_value = "Отчёт с кухней"
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.payment import open_report

            await open_report(mock_callback)

        # Должна быть кнопка "Показать расчёт"
        # ikm был вызван хотя бы раз
        mock_ikm.assert_called()


class TestKitchenAnalysis:
    """Тесты show_kitchen_analysis — callback_data.startswith('kitchen:')."""

    @pytest.mark.asyncio
    async def test_no_report_or_no_kitchen(
        self, mock_callback
    ):
        """Отчёт не найден или нет kitchen_analysis."""
        mock_callback.data = "kitchen:bad-token"

        with (
            patch("bot.handlers.payment.ReportRepository") as MockReportRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.main_menu_keyboard") as mock_mm,
        ):
            report_repo_instance = MagicMock()
            report_repo_instance.get_by_token = AsyncMock(return_value=None)
            MockReportRepo.return_value = report_repo_instance
            mock_gsm.return_value = MagicMock()
            mock_mm.return_value = MagicMock()

            from bot.handlers.payment import show_kitchen_analysis

            await show_kitchen_analysis(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Кухонный слой не найден" in text

    @pytest.mark.asyncio
    async def test_shows_kitchen_analysis(
        self, mock_callback
    ):
        """Показывает кухонный слой."""
        mock_report = MagicMock()
        mock_report.token = "good-token"
        mock_report.kitchen_analysis = {
            "main_archetype": {
                "positions": ["центр"],
                "energies": ["8"],
                "logic": "8 аркан = Сила в центре",
            },
        }

        mock_callback.data = "kitchen:good-token"

        with (
            patch("bot.handlers.payment.ReportRepository") as MockReportRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.InlineKeyboardMarkup") as mock_ikm,
            patch("bot.handlers.payment.InlineKeyboardButton") as mock_ikb,
        ):
            report_repo_instance = MagicMock()
            report_repo_instance.get_by_token = AsyncMock(
                return_value=mock_report
            )
            MockReportRepo.return_value = report_repo_instance
            mock_gsm.return_value = MagicMock()
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.payment import show_kitchen_analysis

            await show_kitchen_analysis(mock_callback)

        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Кухонный слой" in text
        assert "Сила" in text


class TestDownloadPdf:
    """Тесты download_pdf — callback_data.startswith('download_pdf:')."""

    @pytest.mark.asyncio
    async def test_report_not_found(
        self, mock_callback
    ):
        """Отчёт не найден."""
        mock_callback.data = "download_pdf:bad-token"

        with (
            patch("bot.handlers.payment.ReportRepository") as MockReportRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.main_menu_keyboard") as mock_mm,
        ):
            report_repo_instance = MagicMock()
            report_repo_instance.get_by_token = AsyncMock(return_value=None)
            MockReportRepo.return_value = report_repo_instance
            mock_gsm.return_value = MagicMock()
            mock_mm.return_value = MagicMock()

            from bot.handlers.payment import download_pdf

            await download_pdf(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Отчёт не найден" in text

    @pytest.mark.asyncio
    async def test_shows_pdf_link(
        self, mock_callback
    ):
        """Показывает ссылку на PDF."""
        mock_report = MagicMock()
        mock_report.token = "pdf-token"

        mock_callback.data = "download_pdf:pdf-token"

        with (
            patch("bot.handlers.payment.ReportRepository") as MockReportRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.InlineKeyboardMarkup") as mock_ikm,
            patch("bot.handlers.payment.InlineKeyboardButton") as mock_ikb,
        ):
            report_repo_instance = MagicMock()
            report_repo_instance.get_by_token = AsyncMock(
                return_value=mock_report
            )
            MockReportRepo.return_value = report_repo_instance
            mock_gsm.return_value = MagicMock()
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.payment import download_pdf

            await download_pdf(mock_callback)

        mock_callback.message.answer.assert_awaited_once()
        text = mock_callback.message.answer.await_args[0][0]
        assert "PDF-отчёт готов" in text


# =====================================================================
# COMPATIBILITY HANDLER TESTS
# =====================================================================


class TestCompatibility:
    """Тесты ask_compatibility — callback_data == 'compatibility'."""

    @pytest.mark.asyncio
    async def test_user_not_found(
        self, mock_callback, mock_state
    ):
        """Пользователь не найден."""
        with (
            patch("bot.handlers.compatibility.UserRepository") as MockRepo,
            patch("bot.handlers.compatibility.get_async_sessionmaker") as mock_gsm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=None)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()

            from bot.handlers.compatibility import ask_compatibility

            await ask_compatibility(mock_callback, mock_state)

        mock_callback.answer.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Пользователь не найден" in text

    @pytest.mark.asyncio
    async def test_no_matrix_shows_paywall(
        self, mock_callback, mock_user, mock_state
    ):
        """Без матрицы — предложение купить."""
        mock_user.has_matrix = False

        with (
            patch("bot.handlers.compatibility.UserRepository") as MockRepo,
            patch("bot.handlers.compatibility.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.compatibility.InlineKeyboardMarkup") as mock_ikm,
            patch("bot.handlers.compatibility.InlineKeyboardButton") as mock_ikb,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.compatibility import ask_compatibility

            await ask_compatibility(mock_callback, mock_state)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Доступно с покупкой Матрицы судьбы" in text

    @pytest.mark.asyncio
    async def test_compatibility_used_free(
        self, mock_callback, mock_state
    ):
        """Бесплатный расклад уже использован."""
        user = MagicMock()
        user.has_matrix = True
        user.compatibility_used = True
        user.tarot_subscription = False
        user.subscription_status = "free"

        with (
            patch("bot.handlers.compatibility.UserRepository") as MockRepo,
            patch("bot.handlers.compatibility.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.compatibility.InlineKeyboardMarkup") as mock_ikm,
            patch("bot.handlers.compatibility.InlineKeyboardButton") as mock_ikb,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.compatibility import ask_compatibility

            await ask_compatibility(mock_callback, mock_state)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "уже использовал бесплатный расклад" in text

    @pytest.mark.asyncio
    async def test_starts_compatibility_flow(
        self, mock_callback, mock_state
    ):
        """Запускает поток совместимости."""
        user = MagicMock()
        user.has_matrix = True
        user.compatibility_used = False
        user.tarot_subscription = False
        user.subscription_status = "free"

        with (
            patch("bot.handlers.compatibility.UserRepository") as MockRepo,
            patch("bot.handlers.compatibility.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.compatibility.ask_partner_name_text") as mock_apn,
            patch("bot.handlers.compatibility.InlineKeyboardMarkup") as mock_ikm,
            patch("bot.handlers.compatibility.InlineKeyboardButton") as mock_ikb,
            patch("bot.handlers.compatibility.CompatibilityStates"),
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_apn.return_value = "Введи имя партнёра"
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.compatibility import ask_compatibility

            await ask_compatibility(mock_callback, mock_state)

        mock_state.set_state.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Введи имя партнёра" in text

    @pytest.mark.asyncio
    async def test_tarot_user_has_unlimited(
        self, mock_callback, mock_state
    ):
        """Пользователь с таро имеет безлимит."""
        user = MagicMock()
        user.has_matrix = True
        user.compatibility_used = True  # уже использовал, но у него таро
        user.tarot_subscription = True
        user.subscription_status = "free"

        with (
            patch("bot.handlers.compatibility.UserRepository") as MockRepo,
            patch("bot.handlers.compatibility.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.compatibility.ask_partner_name_text") as mock_apn,
            patch("bot.handlers.compatibility.InlineKeyboardMarkup") as mock_ikm,
            patch("bot.handlers.compatibility.InlineKeyboardButton") as mock_ikb,
            patch("bot.handlers.compatibility.CompatibilityStates"),
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_apn.return_value = "Введи имя партнёра"
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.compatibility import ask_compatibility

            await ask_compatibility(mock_callback, mock_state)

        # Должен пропустить проверку compatibility_used
        mock_state.set_state.assert_awaited_once()


# =====================================================================
# COMPATIBILITY FLOW TESTS
# =====================================================================


class TestProcessPartnerName:
    """Тесты process_partner_name."""

    @pytest.mark.asyncio
    async def test_saves_name_and_asks_relation(self, mock_message, mock_state):
        """Сохраняет имя партнёра."""
        mock_message.text = "Анна"

        with (
            patch("bot.handlers.compatibility.ask_relation_type_text") as mock_art,
            patch("bot.handlers.compatibility.InlineKeyboardMarkup") as mock_ikm,
            patch("bot.handlers.compatibility.InlineKeyboardButton") as mock_ikb,
            patch("bot.handlers.compatibility.CompatibilityStates"),
        ):
            mock_art.return_value = "Тип отношений?"
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.compatibility import process_partner_name

            await process_partner_name(mock_message, mock_state)

        mock_state.update_data.assert_awaited_once_with(partner_name="Анна")
        mock_state.set_state.assert_awaited_once()
        mock_message.answer.assert_awaited_once()


class TestProcessRelationType:
    """Тесты process_relation_type."""

    @pytest.mark.asyncio
    async def test_saves_romance_type(self, mock_callback, mock_state):
        """Сохраняет тип 'романтика'."""
        mock_callback.data = "reltype_romance"
        mock_state.get_data = AsyncMock(return_value={"partner_name": "Анна"})

        with (
            patch("bot.handlers.compatibility.ask_partner_date_text") as mock_apd,
            patch("bot.handlers.compatibility.InlineKeyboardMarkup") as mock_ikm,
            patch("bot.handlers.compatibility.InlineKeyboardButton") as mock_ikb,
            patch("bot.handlers.compatibility.CompatibilityStates"),
        ):
            mock_apd.return_value = "Дата рождения партнёра?"
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.compatibility import process_relation_type

            await process_relation_type(mock_callback, mock_state)

        mock_state.update_data.assert_awaited_once_with(relation_type="романтика")
        mock_callback.message.edit_text.assert_awaited_once()

# =====================================================================
# EDGE CASE TESTS
# =====================================================================


class TestTarotEdgeCases:
    """Крайние случаи для tarot."""

    @pytest.mark.asyncio
    async def test_show_tarot_spheres_user_not_found(
        self, mock_callback, mock_state
    ):
        """show_tarot_spheres: пользователь не найден."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot.main_menu_keyboard") as mock_mm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=None)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_mm.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_spheres

            await show_tarot_spheres(mock_callback, mock_state)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Пользователь не найден" in text

    @pytest.mark.asyncio
    async def test_sphere_result_ai_failure(
        self, mock_callback, mock_tarot_user, mock_state
    ):
        """show_sphere_result: ошибка AI."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot._daily_arcana_number") as mock_daily,
            patch("bot.handlers.tarot.AIService") as mock_ai,
            patch("bot.handlers.tarot.animated_loading") as mock_load,
            patch("bot.handlers.tarot.tarot_back_keyboard") as mock_tbk,
            patch("bot.handlers.tarot.ARCANA", {
                5: {"name": "Иерофант"},
            }),
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_tarot_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_daily.return_value = 5
            mock_load.return_value = AsyncMock()
            mock_load.return_value.__aenter__ = AsyncMock()
            mock_load.return_value.__aexit__ = AsyncMock()
            mock_ai._load_prompt.return_value = "prompt"
            mock_ai.chat = AsyncMock(side_effect=Exception("API error"))
            mock_tbk.return_value = MagicMock()

            from bot.handlers.tarot import show_sphere_result

            mock_callback.data = "tarot_money"
            await show_sphere_result(mock_callback, mock_state)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Карты молчат" in text

    @pytest.mark.asyncio
    async def test_tarot_twins_ai_failure(
        self, mock_callback, mock_tarot_user
    ):
        """show_tarot_twins: ошибка AI."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot._daily_arcana_number") as mock_daily,
            patch("bot.handlers.tarot.AIService") as mock_ai,
            patch("bot.handlers.tarot.animated_loading") as mock_load,
            patch("bot.handlers.tarot.tarot_back_keyboard") as mock_tbk,
            patch("bot.handlers.tarot.ARCANA", {
                5: {"name": "Иерофант"},
            }),
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_tarot_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_daily.return_value = 5
            mock_load.return_value = AsyncMock()
            mock_load.return_value.__aenter__ = AsyncMock()
            mock_load.return_value.__aexit__ = AsyncMock()
            mock_ai._load_prompt.return_value = "prompt"
            mock_ai.chat = AsyncMock(side_effect=Exception("API error"))
            mock_tbk.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_twins

            await show_tarot_twins(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Карты молчат" in text

    @pytest.mark.asyncio
    async def test_tarot_portal_ai_failure(
        self, mock_callback, mock_tarot_user
    ):
        """show_tarot_portal: ошибка AI."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot.AIService") as mock_ai,
            patch("bot.handlers.tarot.animated_loading") as mock_load,
            patch("bot.handlers.tarot.tarot_back_keyboard") as mock_tbk,
            patch("bot.handlers.tarot.ARCANA", {
                1: {"name": "Маг"},
            }),
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_tarot_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_load.return_value = AsyncMock()
            mock_load.return_value.__aenter__ = AsyncMock()
            mock_load.return_value.__aexit__ = AsyncMock()
            mock_ai._load_prompt.return_value = "prompt"
            mock_ai.chat = AsyncMock(side_effect=Exception("API error"))
            mock_tbk.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_portal

            await show_tarot_portal(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Карты молчат" in text

    @pytest.mark.asyncio
    async def test_tarot_blocks_ai_failure(
        self, mock_callback, mock_tarot_user
    ):
        """show_tarot_blocks: ошибка AI."""
        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot._daily_arcana_number") as mock_daily,
            patch("bot.handlers.tarot.AIService") as mock_ai,
            patch("bot.handlers.tarot.animated_loading") as mock_load,
            patch("bot.handlers.tarot.tarot_back_keyboard") as mock_tbk,
            patch("bot.handlers.tarot.ARCANA", {
                5: {"name": "Иерофант"},
            }),
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(
                return_value=mock_tarot_user
            )
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_daily.return_value = 5
            mock_load.return_value = AsyncMock()
            mock_load.return_value.__aenter__ = AsyncMock()
            mock_load.return_value.__aexit__ = AsyncMock()
            mock_ai._load_prompt.return_value = "prompt"
            mock_ai.chat = AsyncMock(side_effect=Exception("API error"))
            mock_tbk.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_blocks

            await show_tarot_blocks(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Карты молчат" in text

    @pytest.mark.asyncio
    async def test_payment_error_handling(
        self, mock_callback, mock_user
    ):
        """buy_subscription: общая ошибка."""
        with (
            patch("bot.handlers.payment.UserRepository") as MockRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.PaymentService") as mock_ps,
            patch("bot.handlers.payment.main_menu_keyboard") as mock_mm,
            patch("bot.handlers.payment.settings") as mock_settings,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_settings.test_mode = False
            mock_ps.create_subscription = AsyncMock(
                side_effect=Exception("Service unavailable")
            )
            mock_mm.return_value = MagicMock()

            from bot.handlers.payment import initiate_subscription

            await initiate_subscription(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "ошибка" in text.lower() or "Попробуй" in text

    @pytest.mark.asyncio
    async def test_profile_callback_user_not_found(
        self, mock_callback
    ):
        """callback_profile: пользователь не найден."""
        with (
            patch("bot.handlers.profile.UserRepository") as MockRepo,
            patch("bot.handlers.profile.ReportRepository") as MockReportRepo,
            patch("bot.handlers.profile.get_async_sessionmaker") as mock_gsm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=None)
            MockRepo.return_value = repo_instance

            MockReportRepo.return_value = MagicMock()
            mock_gsm.return_value = MagicMock()

            from bot.handlers.profile import callback_profile

            await callback_profile(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Пользователь не найден" in text

    @pytest.mark.asyncio
    async def test_cancel_subscription_no_user(
        self, mock_callback
    ):
        """cancel_subscription_do: пользователь не найден."""
        with (
            patch("bot.handlers.profile.UserRepository") as MockRepo,
            patch("bot.handlers.profile.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.profile.InlineKeyboardMarkup") as mock_ikm,
            patch("bot.handlers.profile.InlineKeyboardButton") as mock_ikb,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=None)
            MockRepo.return_value = repo_instance

            mock_gsm.return_value = MagicMock()
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.profile import cancel_subscription_do

            await cancel_subscription_do(mock_callback)

        # Должен отработать без ошибки
        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Подписка отменена" in text

    @pytest.mark.asyncio
    async def test_buy_tarot_subscription_payment_error(
        self, mock_callback, mock_user
    ):
        """buy_tarot_subscription: ошибка."""
        with (
            patch("bot.handlers.payment.UserRepository") as MockRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.PaymentService") as mock_ps,
            patch("bot.handlers.payment.main_menu_keyboard") as mock_mm,
            patch("bot.handlers.payment.settings") as mock_settings,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_settings.test_mode = False
            mock_ps.create_subscription = AsyncMock(
                side_effect=Exception("Payment error")
            )
            mock_mm.return_value = MagicMock()

            from bot.handlers.payment import initiate_tarot_subscription

            await initiate_tarot_subscription(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "ошибка" in text.lower() or "Попробуй" in text

    @pytest.mark.asyncio
    async def test_buy_matrix_value_error(
        self, mock_callback, mock_user
    ):
        """buy_matrix: ValueError."""
        with (
            patch("bot.handlers.payment.UserRepository") as MockRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.PaymentService") as mock_ps,
            patch("bot.handlers.payment.main_menu_keyboard") as mock_mm,
            patch("bot.handlers.payment.settings") as mock_settings,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_settings.test_mode = False
            mock_ps.create_matrix_payment = AsyncMock(
                side_effect=ValueError("Bad value")
            )
            mock_mm.return_value = MagicMock()

            from bot.handlers.payment import buy_matrix

            await buy_matrix(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Оплата временно недоступна" in text

    @pytest.mark.asyncio
    async def test_manage_subscription_user_not_found(
        self, mock_callback
    ):
        """manage_subscription: пользователь не найден."""
        with (
            patch("bot.handlers.profile.UserRepository") as MockRepo,
            patch("bot.handlers.profile.ReportRepository") as MockReportRepo,
            patch("bot.handlers.profile.get_async_sessionmaker") as mock_gsm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=None)
            MockRepo.return_value = repo_instance

            MockReportRepo.return_value = MagicMock()
            mock_gsm.return_value = MagicMock()

            from bot.handlers.profile import manage_subscription

            await manage_subscription(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Пользователь не найден" in text

    @pytest.mark.asyncio
    async def test_back_to_profile_user_not_found(
        self, mock_callback
    ):
        """back_to_profile: пользователь не найден."""
        with (
            patch("bot.handlers.profile.UserRepository") as MockRepo,
            patch("bot.handlers.profile.ReportRepository") as MockReportRepo,
            patch("bot.handlers.profile.get_async_sessionmaker") as mock_gsm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=None)
            MockRepo.return_value = repo_instance

            MockReportRepo.return_value = MagicMock()
            mock_gsm.return_value = MagicMock()

            from bot.handlers.profile import back_to_profile

            await back_to_profile(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Пользователь не найден" in text

    @pytest.mark.asyncio
    async def test_view_reports_user_not_found(
        self, mock_callback
    ):
        """view_reports: пользователь не найден."""
        with (
            patch("bot.handlers.profile.UserRepository") as MockRepo,
            patch("bot.handlers.profile.ReportRepository") as MockReportRepo,
            patch("bot.handlers.profile.get_async_sessionmaker") as mock_gsm,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=None)
            MockRepo.return_value = repo_instance

            MockReportRepo.return_value = MagicMock()
            mock_gsm.return_value = MagicMock()

            from bot.handlers.profile import view_reports

            await view_reports(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Пользователь не найден" in text

    @pytest.mark.asyncio
    async def test_show_kitchen_analysis_no_data(
        self, mock_callback
    ):
        """show_kitchen_analysis: отчёт есть, но kitchen_analysis = None."""
        mock_report = MagicMock()
        mock_report.kitchen_analysis = None

        mock_callback.data = "kitchen:good-token"

        with (
            patch("bot.handlers.payment.ReportRepository") as MockReportRepo,
            patch("bot.handlers.payment.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.payment.main_menu_keyboard") as mock_mm,
        ):
            report_repo_instance = MagicMock()
            report_repo_instance.get_by_token = AsyncMock(
                return_value=mock_report
            )
            MockReportRepo.return_value = report_repo_instance
            mock_gsm.return_value = MagicMock()
            mock_mm.return_value = MagicMock()

            from bot.handlers.payment import show_kitchen_analysis

            await show_kitchen_analysis(mock_callback)

        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Кухонный слой не найден" in text

    @pytest.mark.asyncio
    async def test_show_tarot_daily_card_arcana_data(
        self, mock_callback, mock_user
    ):
        """Проверка корректных ключей ARCANA в карте дня."""
        mock_user.main_archetype_number = 8

        with (
            patch("bot.handlers.tarot.UserRepository") as MockRepo,
            patch("bot.handlers.tarot.get_async_sessionmaker") as mock_gsm,
            patch("bot.handlers.tarot._daily_arcana_number") as mock_daily,
            patch("bot.handlers.tarot._personal_arcana_number") as mock_personal,
            patch("bot.handlers.tarot.AIService") as mock_ai,
            patch("bot.handlers.tarot.animated_loading") as mock_load,
            patch("aiogram.types.InlineKeyboardMarkup") as mock_ikm,
            patch("aiogram.types.InlineKeyboardButton") as mock_ikb,
            patch("bot.handlers.tarot.ARCANA", {
                8: {"name": "Сила"},
                10: {"name": "Колесо Фортуны"},
            }),
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_gsm.return_value = MagicMock()
            mock_daily.return_value = 8
            mock_personal.return_value = 10
            mock_load.return_value = AsyncMock()
            mock_load.return_value.__aenter__ = AsyncMock()
            mock_load.return_value.__aexit__ = AsyncMock()
            mock_ai._load_prompt.return_value = "prompt {arcana_number}"
            mock_ai.chat = AsyncMock(return_value="Твоя сила — внутри.")
            mock_ikm.return_value = MagicMock()
            mock_ikb.return_value = MagicMock()

            from bot.handlers.tarot import show_tarot_daily_card

            await show_tarot_daily_card(mock_callback)

        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.await_args[0][0]
        assert "Карта дня" in text
