from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.schemas import DailyInsightResult


@pytest.mark.asyncio
class TestInsightsHandler:
    async def test_free_user_shows_static(self):
        mock_user = MagicMock()
        mock_user.main_archetype = "Маг"
        mock_user.main_archetype_number = 1
        mock_user.subscription_status = "free"
        mock_user.first_name = "Test"

        mock_callback = AsyncMock()
        mock_callback.from_user.id = 123
        mock_callback.message.edit_text = AsyncMock()

        with (
            patch("bot.handlers.insights.UserRepository") as MockRepo,
            patch("bot.handlers.insights.insight_keyboard") as mock_ikb,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_ikb.return_value = None

            from bot.handlers.insights import show_insight
            from aiogram.fsm.context import FSMContext

            mock_state = AsyncMock(spec=FSMContext)
            mock_state.get_data.return_value = {}

            await show_insight(mock_callback, mock_state)

        mock_callback.message.edit_text.assert_awaited_once()
        call_text = mock_callback.message.edit_text.await_args[0][0]
        assert "Маг" in call_text

    async def test_subscriber_shows_ai(self):
        mock_user = MagicMock()
        mock_user.main_archetype = "Маг"
        mock_user.main_archetype_number = 1
        mock_user.subscription_status = "premium"
        mock_user.first_name = "Test"
        mock_user.username = "testuser"
        mock_user.birth_date = "01.01.2000"
        mock_user.telegram_id = 123

        mock_callback = AsyncMock()
        mock_callback.from_user.id = 123
        mock_callback.message.edit_text = AsyncMock()

        mock_insight = DailyInsightResult(insight="AI insight for premium user", focus_area="карьера")

        with (
            patch("bot.handlers.insights.UserRepository") as MockRepo,
            patch("bot.handlers.insights.AIService.generate_daily_insight", new_callable=AsyncMock) as mock_ai,
            patch("bot.handlers.insights.insight_keyboard_subscriber") as mock_iks,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_ai.return_value = mock_insight
            mock_iks.return_value = None

            from bot.handlers.insights import show_insight
            from aiogram.fsm.context import FSMContext

            mock_state = AsyncMock(spec=FSMContext)
            mock_state.get_data.return_value = {}

            await show_insight(mock_callback, mock_state)

        mock_callback.message.edit_text.assert_awaited_once()
        call_text = mock_callback.message.edit_text.await_args[0][0]
        assert "AI insight" in call_text
        mock_ai.assert_awaited_once()

    async def test_subscriber_cached_insight(self):
        mock_user = MagicMock()
        mock_user.main_archetype = "Маг"
        mock_user.main_archetype_number = 1
        mock_user.subscription_status = "premium"
        mock_user.first_name = "Test"
        mock_user.telegram_id = 123

        mock_callback = AsyncMock()
        mock_callback.from_user.id = 123
        mock_callback.message.edit_text = AsyncMock()

        with (
            patch("bot.handlers.insights.UserRepository") as MockRepo,
            patch("bot.handlers.insights.insight_keyboard_subscriber") as mock_iks,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_iks.return_value = None

            from bot.handlers.insights import show_insight
            from aiogram.fsm.context import FSMContext

            mock_state = AsyncMock(spec=FSMContext)
            mock_state.get_data.return_value = {
                "ai_insight_date": "2026-05-15",
                "ai_insight_text": "Cached AI insight",
            }

            with patch("bot.handlers.insights.date") as mock_date:
                mock_date.today.return_value.isoformat.return_value = "2026-05-15"

                await show_insight(mock_callback, mock_state)

        mock_callback.message.edit_text.assert_awaited_once()
        call_text = mock_callback.message.edit_text.await_args[0][0]
        assert "Cached AI insight" in call_text

    async def test_free_user_exhausted_shows_subscription(self):
        mock_user = MagicMock()
        mock_user.main_archetype = "Маг"
        mock_user.main_archetype_number = 1
        mock_user.subscription_status = "free"
        mock_user.first_name = "Test"

        mock_callback = AsyncMock()
        mock_callback.from_user.id = 123
        mock_callback.message.edit_text = AsyncMock()

        with (
            patch("bot.handlers.insights.UserRepository") as MockRepo,
            patch("bot.handlers.insights.subscription_keyboard") as mock_skb,
            patch("bot.handlers.insights.date") as mock_date,
        ):
            repo_instance = MagicMock()
            repo_instance.get_by_telegram_id = AsyncMock(return_value=mock_user)
            MockRepo.return_value = repo_instance
            mock_skb.return_value = None
            mock_date.today.return_value.isoformat.return_value = "2026-05-15"

            from bot.handlers.insights import show_insight
            from aiogram.fsm.context import FSMContext

            mock_state = AsyncMock(spec=FSMContext)
            mock_state.get_data.return_value = {
                "insights_shown_2026-05-15": [0, 1, 2, 3, 4],
            }

            await show_insight(mock_callback, mock_state)

        mock_callback.message.edit_text.assert_awaited_once()
        call_text = mock_callback.message.edit_text.await_args[0][0]
        assert "достаточно услышал" in call_text
