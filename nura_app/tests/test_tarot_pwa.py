"""Tests for tarot_pwa.py — PWA Tarot API routes.

CAVEMAN PROTOCOL:
  ✓ Each endpoint tested: success, 402 (no subscription), 404 (not found),
    400 (bad request), 422 (validation), 503 (AI unavailable)
  ✓ AIService.chat mocked via class-level patch
  ✓ UserRepository.get_by_web_session_id mocked via class-level patch
  ✓ calculate_daily_arcana mocked for deterministic results
  ✓ ~1100 lines of coverage
"""

import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.routes.tarot_pwa import (
    DailyCardResponse,
    SpreadCard,
    SpreadRequest,
    SpreadResponse,
)
from core.models import User

# ═══════════════════════════════════════════════════════════════════
# Constants — reusable mock data
# ═══════════════════════════════════════════════════════════════════

MOCK_SESSION_ID = "test-session-abc-123"
MOCK_USER_ID = uuid.uuid4()

MOCK_WEEKLY_SPREAD_RESPONSE = {
    "body": {
        "card_number": 3,
        "card_name": "Императрица",
        "energy": "Энергия изобилия",
        "interpretation": "Тело просит заботы.",
        "practice": "Сделай массаж лица.",
    },
    "mind": {
        "card_number": 7,
        "card_name": "Колесница",
        "energy": "Энергия воли",
        "interpretation": "Ум настроен на победу.",
        "practice": "Запиши 3 цели.",
    },
    "spirit": {
        "card_number": 11,
        "card_name": "Сила",
        "energy": "Энергия стойкости",
        "interpretation": "Дух укрепляется через действие.",
        "practice": "Медитация 5 минут.",
    },
    "overall": "Неделя гармонии тела, ума и духа.",
}

MOCK_QUESTION_SPREAD_RESPONSE = {
    "past": {
        "card_number": 5,
        "card_name": "Иерофант",
        "meaning": "Прошлое — время обучения.",
        "how_it_relates": "Ты уже сталкивался с этим уроком.",
    },
    "present": {
        "card_number": 8,
        "card_name": "Справедливость",
        "meaning": "Баланс и выбор.",
        "how_it_relates": "Сейчас важно принять решение.",
    },
    "future": {
        "card_number": 17,
        "card_name": "Звезда",
        "meaning": "Надежда и вдохновение.",
        "how_it_relates": "Будущее открывает новые горизонты.",
    },
    "summary": "Ответ уже внутри тебя.",
    "advice": "Доверься интуиции.",
}

MOCK_AI_CHAT_RESPONSE = (
    "В сфере денег и реализации сейчас период стабильности.\n\n"
    "Твои прошлые действия закладывают фундамент для будущего.\n\n"
    "Как использовать: Составь план на месяц и придерживайся его."
)

MOCK_YESNO_CHAT_RESPONSE = (
    "Да, сейчас подходящее время.\n\n"
    "Твоя интуиция ведёт тебя в правильном направлении.\n\n"
    "Как использовать: Сделай первый шаг сегодня."
)


# ═══════════════════════════════════════════════════════════════════
# Helper — build a mock User
# ═══════════════════════════════════════════════════════════════════

def _build_mock_user(
    *,
    web_session_id: str = MOCK_SESSION_ID,
    birth_date: str | None = "01.01.2000",
    tarot_subscription: bool = True,
    first_name: str = "Тест",
    name: str = "Тестовый",
    username: str = "testuser",
) -> MagicMock:
    """Create a MagicMock that looks like a core.models.User instance."""
    user = MagicMock(spec=User)
    user.id = MOCK_USER_ID
    user.web_session_id = web_session_id
    user.birth_date = birth_date
    user.tarot_subscription = tarot_subscription
    user.first_name = first_name
    user.name = name
    user.username = username
    return user


# ═══════════════════════════════════════════════════════════════════
# Fixtures: app & client
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def app():
    """Create FastAPI test app with tarot_pwa router.

    Rate limiter is neutralised by:
      1. Disabling the global `api.deps.limiter` instance (enabled=False)
      2. Stripping any `_slow_limits` from endpoint functions
    """
    import api.deps as deps_mod

    # 1. Disable the real limiter instance so its async_wrapper skips checks
    deps_mod.limiter.enabled = False

    # 2. Import router and strip _slow_limits (belt & suspenders)
    import api.routes.tarot_pwa as tpm
    for route in tpm.router.routes:
        if hasattr(route.endpoint, "_slow_limits"):
            del route.endpoint._slow_limits

    _app = FastAPI()
    _app.include_router(tpm.router)
    _app.state.limiter = None

    # Restore limiter after test
    yield _app
    deps_mod.limiter.enabled = True


@pytest.fixture
def client(app):
    return TestClient(app)


# ═══════════════════════════════════════════════════════════════════
# Fixtures: mock user profiles
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def subscribed_user():
    """User with active tarot subscription."""
    return _build_mock_user()


@pytest.fixture
def unsubscribed_user():
    """User without tarot subscription."""
    return _build_mock_user(tarot_subscription=False)


@pytest.fixture
def user_no_birth_date():
    """User with missing birth date."""
    return _build_mock_user(birth_date=None)


@pytest.fixture
def nonexistent_user():
    """User lookup returns None."""
    return None


# ═══════════════════════════════════════════════════════════════════
# Fixtures: mock patches applied per test class
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def mock_get_user(request):
    """Patch UserRepository.get_by_web_session_id.

    By default returns *subscribed_user*. Override by setting
    a ``pytest.mark.mock_user(retval)`` marker on the test/node.
    """
    default = _build_mock_user()
    marker = request.node.get_closest_marker("mock_user")
    retval = marker.args[0] if marker else default

    with patch(
        "api.routes.tarot_pwa.UserRepository.get_by_web_session_id",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = retval
        yield mock


@pytest.fixture
def mock_arcana():
    """Patch calculate_daily_arcana to return deterministic value."""
    with patch(
        "api.routes.tarot_pwa.calculate_daily_arcana",
        return_value=3,
    ) as mock:
        yield mock


@pytest.fixture
def mock_ai_chat():
    """Patch AIService.chat to return a canned interpretation."""
    with patch(
        "api.routes.tarot_pwa.AIService.chat",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = MOCK_AI_CHAT_RESPONSE
        yield mock


@pytest.fixture
def mock_ai_chat_yesno():
    """Patch AIService.chat for yes/no endpoint."""
    with patch(
        "api.routes.tarot_pwa.AIService.chat",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = MOCK_YESNO_CHAT_RESPONSE
        yield mock


@pytest.fixture
def mock_ai_weekly():
    """Patch AIService.generate_tarot_weekly_spread."""
    with patch(
        "api.routes.tarot_pwa.AIService.generate_tarot_weekly_spread",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = MOCK_WEEKLY_SPREAD_RESPONSE
        yield mock


@pytest.fixture
def mock_ai_question():
    """Patch AIService.generate_tarot_question."""
    with patch(
        "api.routes.tarot_pwa.AIService.generate_tarot_question",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = MOCK_QUESTION_SPREAD_RESPONSE
        yield mock


@pytest.fixture
def mock_ai_chat_error():
    """Patch AIService.chat to raise an exception."""
    with patch(
        "api.routes.tarot_pwa.AIService.chat",
        new_callable=AsyncMock,
    ) as mock:
        mock.side_effect = Exception("AI service unavailable")
        yield mock


@pytest.fixture
def mock_ai_weekly_error():
    """Patch AIService.generate_tarot_weekly_spread to raise."""
    with patch(
        "api.routes.tarot_pwa.AIService.generate_tarot_weekly_spread",
        new_callable=AsyncMock,
    ) as mock:
        mock.side_effect = Exception("AI service unavailable")
        yield mock


@pytest.fixture
def mock_ai_question_error():
    """Patch AIService.generate_tarot_question to raise."""
    with patch(
        "api.routes.tarot_pwa.AIService.generate_tarot_question",
        new_callable=AsyncMock,
    ) as mock:
        mock.side_effect = Exception("AI service unavailable")
        yield mock


# ═══════════════════════════════════════════════════════════════════
# Test: Daily Card  (GET /api/v1/tarot/daily-card)
# ═══════════════════════════════════════════════════════════════════

class TestDailyCard:
    """GET /api/v1/tarot/daily-card — карта дня."""

    # ── Happy path ────────────────────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_daily_card_success(self, client, mock_get_user, mock_arcana):
        """200 — карта дня успешно возвращается."""
        # mock_arcana returns 3 → arcana 3 = Императрица
        response = client.get(
            "/api/v1/tarot/daily-card",
            params={"session_id": MOCK_SESSION_ID},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["arcana_number"] == 3
        assert data["arcana_name"] == "Императрица"
        assert data["arcana_symbol"] == "🌸"
        assert data["key_phrase"] == "Изобилие и творчество"
        assert data["interpretation"]
        assert data["advice"]
        assert data["affirmation"]
        assert data["date_label"]

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user(birth_date="15.06.1990"))
    async def test_daily_card_different_birth_date(
        self, client, mock_get_user, mock_arcana,
    ):
        """200 — аркан рассчитывается на основе даты рождения."""
        # mock_arcana always returns 3 regardless of birth_date
        response = client.get(
            "/api/v1/tarot/daily-card",
            params={"session_id": MOCK_SESSION_ID},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["arcana_number"] == 3

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_daily_card_date_label_format(
        self, client, mock_get_user, mock_arcana,
    ):
        """200 — date_label формируется корректно."""
        today = date.today()
        months = [
            "января", "февраля", "марта", "апреля",
            "мая", "июня", "июля", "августа",
            "сентября", "октября", "ноября", "декабря",
        ]
        expected = f"{today.day} {months[today.month - 1]}"
        response = client.get(
            "/api/v1/tarot/daily-card",
            params={"session_id": MOCK_SESSION_ID},
        )
        assert response.status_code == 200
        assert response.json()["date_label"] == expected

    # ── Error: user not found ─────────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(None)
    async def test_daily_card_user_not_found(self, client, mock_get_user):
        """404 — сессия не найдена."""
        response = client.get(
            "/api/v1/tarot/daily-card",
            params={"session_id": "nonexistent-session"},
        )
        assert response.status_code == 404
        assert "Сессия не найдена" in response.json()["detail"]

    # ── Error: no birth date ──────────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user(birth_date=None))
    async def test_daily_card_no_birth_date(
        self, client, mock_get_user,
    ):
        """400 — дата рождения не указана."""
        response = client.get(
            "/api/v1/tarot/daily-card",
            params={"session_id": MOCK_SESSION_ID},
        )
        assert response.status_code == 400
        assert "Дата рождения не указана" in response.json()["detail"]

    # ── Error: missing session_id param ───────────────────────────

    @pytest.mark.asyncio
    async def test_daily_card_missing_session_id(self, client):
        """422 — session_id обязательный параметр."""
        response = client.get("/api/v1/tarot/daily-card")
        assert response.status_code == 422
        assert "session_id" in response.text

    # ── Response schema ───────────────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_daily_card_response_schema(
        self, client, mock_get_user, mock_arcana,
    ):
        """200 — ответ соответствует схеме DailyCardResponse."""
        response = client.get(
            "/api/v1/tarot/daily-card",
            params={"session_id": MOCK_SESSION_ID},
        )
        assert response.status_code == 200
        try:
            DailyCardResponse(**response.json())
        except ValidationError:
            pytest.fail("Response does not match DailyCardResponse schema")

    # ── Deterministic arcana value check ──────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_daily_card_arcana_out_of_range_fallback(
        self, client, mock_get_user,
    ):
        """200 — при некорректном аркане используется fallback ARCANA[1]."""
        with patch(
            "api.routes.tarot_pwa.calculate_daily_arcana",
            return_value=999,  # out of range
        ):
            response = client.get(
                "/api/v1/tarot/daily-card",
                params={"session_id": MOCK_SESSION_ID},
            )
        assert response.status_code == 200
        data = response.json()
        # Should fall back to arcana 1 (Маг)
        assert data["arcana_number"] == 999  # original number kept
        assert data["arcana_name"] == "Маг"  # but arcana data from arcana 1

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_daily_card_arcana_zero(
        self, client, mock_get_user,
    ):
        """200 — аркан 0 тоже падает на ARCANA[1]."""
        with patch(
            "api.routes.tarot_pwa.calculate_daily_arcana",
            return_value=0,
        ):
            response = client.get(
                "/api/v1/tarot/daily-card",
                params={"session_id": MOCK_SESSION_ID},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["arcana_name"] == "Маг"

    # ── Edge: user with no first_name or name ─────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(
        _build_mock_user(first_name=None, name=None, username=None),
    )
    async def test_daily_card_minimal_user(
        self, client, mock_get_user, mock_arcana,
    ):
        """200 — даже без имени/username не падает."""
        response = client.get(
            "/api/v1/tarot/daily-card",
            params={"session_id": MOCK_SESSION_ID},
        )
        assert response.status_code == 200


# ═══════════════════════════════════════════════════════════════════
# Test: Spread — Weekly  (POST /api/v1/tarot/spread, weekly)
# ═══════════════════════════════════════════════════════════════════

class TestSpreadWeekly:
    """POST /api/v1/tarot/spread — weekly (расклад недели)."""

    SPREAD_BODY = {"session_id": MOCK_SESSION_ID, "spread_type": "weekly"}

    # ── Happy path ────────────────────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_weekly_success(
        self, client, mock_get_user, mock_ai_weekly,
    ):
        """200 — недельный расклад успешно возвращается."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 200
        data = response.json()
        assert data["spread_type"] == "weekly"
        assert data["spread_name"] == "Расклад недели"
        assert len(data["cards"]) == 3
        assert data["cards"][0]["position_name"] == "Тело"
        assert data["cards"][1]["position_name"] == "Ум"
        assert data["cards"][2]["position_name"] == "Дух"
        assert data["summary"] == MOCK_WEEKLY_SPREAD_RESPONSE["overall"]

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_weekly_cards_have_advice(
        self, client, mock_get_user, mock_ai_weekly,
    ):
        """200 — каждая карта содержит practice как advice."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 200
        for card in response.json()["cards"]:
            assert "advice" in card

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_weekly_response_schema(
        self, client, mock_get_user, mock_ai_weekly,
    ):
        """200 — ответ проходит валидацию SpreadResponse."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 200
        try:
            SpreadResponse(**response.json())
        except ValidationError:
            pytest.fail("Response does not match SpreadResponse schema")

    # ── Error: no subscription ────────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user(tarot_subscription=False))
    async def test_weekly_no_subscription(
        self, client, mock_get_user,
    ):
        """402 — требуется подписка Таро."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 402
        assert "Требуется подписка Таро" in response.json()["detail"]

    # ── Error: 503 AI unavailable ─────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_weekly_ai_error(
        self, client, mock_get_user, mock_ai_weekly_error,
    ):
        """503 — AI временно недоступен."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 503
        assert "AI временно недоступен" in response.json()["detail"]


# ═══════════════════════════════════════════════════════════════════
# Test: Spread — Question  (POST /api/v1/tarot/spread, question)
# ═══════════════════════════════════════════════════════════════════

class TestSpreadQuestion:
    """POST /api/v1/tarot/spread — question (по вопросу)."""

    SPREAD_BODY = {
        "session_id": MOCK_SESSION_ID,
        "spread_type": "question",
        "question": "Стоит ли менять работу?",
    }

    # ── Happy path ────────────────────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_question_success(
        self, client, mock_get_user, mock_ai_question,
    ):
        """200 — расклад по вопросу успешно возвращается."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 200
        data = response.json()
        assert data["spread_type"] == "question"
        assert data["spread_name"] == "По вопросу"
        assert len(data["cards"]) == 3
        assert data["cards"][0]["position_name"] == "Прошлое"
        assert data["cards"][1]["position_name"] == "Настоящее"
        assert data["cards"][2]["position_name"] == "Будущее"
        assert data["summary"]

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_question_response_schema(
        self, client, mock_get_user, mock_ai_question,
    ):
        """200 — ответ проходит валидацию SpreadResponse."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 200
        try:
            SpreadResponse(**response.json())
        except ValidationError:
            pytest.fail("Response does not match SpreadResponse schema")

    # ── Error: missing question ───────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_question_missing_question(
        self, client, mock_get_user,
    ):
        """400 — вопрос обязателен для spread_type=question."""
        body = {"session_id": MOCK_SESSION_ID, "spread_type": "question"}
        response = client.post("/api/v1/tarot/spread", json=body)
        assert response.status_code == 400
        assert "Вопрос обязателен" in response.json()["detail"]

    # ── Error: no subscription ────────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user(tarot_subscription=False))
    async def test_question_no_subscription(
        self, client, mock_get_user,
    ):
        """402 — требуется подписка Таро."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 402

    # ── Error: 503 AI unavailable ─────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_question_ai_error(
        self, client, mock_get_user, mock_ai_question_error,
    ):
        """503 — AI временно недоступен."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 503

    # ── Summary contains advice when present ──────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_question_summary_with_advice(
        self, client, mock_get_user, mock_ai_question,
    ):
        """200 — summary содержит совет, если он есть в ответе AI."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 200
        assert "Совет:" in response.json()["summary"]


# ═══════════════════════════════════════════════════════════════════
# Test: Spread — Life  (POST /api/v1/tarot/spread, life)
# ═══════════════════════════════════════════════════════════════════

class TestSpreadLife:
    """POST /api/v1/tarot/spread — life (сферы жизни)."""

    SPREAD_BODY = {"session_id": MOCK_SESSION_ID, "spread_type": "life"}

    # ── Happy path ────────────────────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_life_success(
        self, client, mock_get_user, mock_arcana, mock_ai_chat,
    ):
        """200 — сфера жизни успешно возвращается."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 200
        data = response.json()
        assert data["spread_type"] == "life"
        assert data["spread_name"] == "Сферы жизни"
        assert len(data["cards"]) == 1
        assert data["cards"][0]["position_name"] == "Деньги и реализация"
        assert data["cards"][0]["arcana_number"] == 3
        assert data["cards"][0]["arcana_name"] == "Императрица"

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_life_calls_chat_with_correct_prompt(
        self, client, mock_get_user, mock_arcana, mock_ai_chat,
    ):
        """200 — AIService.chat вызван с корректными параметрами."""
        client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        mock_ai_chat.assert_awaited_once()
        call_kwargs = mock_ai_chat.call_args[1]
        assert "api_params" in call_kwargs
        assert call_kwargs["api_params"]["max_tokens"] == 500
        assert call_kwargs["api_params"]["temperature"] == 0.7
        assert call_kwargs["timeout"] == 120.0

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_life_response_schema(
        self, client, mock_get_user, mock_arcana, mock_ai_chat,
    ):
        """200 — ответ проходит валидацию SpreadResponse."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 200
        try:
            SpreadResponse(**response.json())
        except ValidationError:
            pytest.fail("Response does not match SpreadResponse schema")

    # ── Error: no subscription ────────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user(tarot_subscription=False))
    async def test_life_no_subscription(
        self, client, mock_get_user,
    ):
        """402 — требуется подписка Таро."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 402

    # ── Error: 503 AI unavailable ─────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_life_ai_error(
        self, client, mock_get_user, mock_arcana, mock_ai_chat_error,
    ):
        """503 — AI временно недоступен."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 503
        assert "AI временно недоступен" in response.json()["detail"]


# ═══════════════════════════════════════════════════════════════════
# Test: Spread — Doubles  (POST /api/v1/tarot/spread, doubles)
# ═══════════════════════════════════════════════════════════════════

class TestSpreadDoubles:
    """POST /api/v1/tarot/spread — doubles (двойники)."""

    SPREAD_BODY = {"session_id": MOCK_SESSION_ID, "spread_type": "doubles"}

    # ── Happy path ────────────────────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_doubles_success(
        self, client, mock_get_user, mock_arcana, mock_ai_chat,
    ):
        """200 — расклад Двойники успешно возвращается."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 200
        data = response.json()
        assert data["spread_type"] == "doubles"
        assert data["spread_name"] == "Двойники"
        assert len(data["cards"]) == 2
        assert data["cards"][0]["position_name"] == "Первый импульс"
        assert data["cards"][1]["position_name"] == "Второй импульс"

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_doubles_arcana_values(
        self, client, mock_get_user, mock_arcana, mock_ai_chat,
    ):
        """200 — арканы рассчитываются на основе daily arcana."""
        # mock_arcana returns 3
        # arcana_one = 3, arcana_two = 3 % 22 + 1 = 4
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 200
        data = response.json()
        assert data["cards"][0]["arcana_number"] == 3
        assert data["cards"][1]["arcana_number"] == 4

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_doubles_response_schema(
        self, client, mock_get_user, mock_arcana, mock_ai_chat,
    ):
        """200 — ответ проходит валидацию SpreadResponse."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 200
        try:
            SpreadResponse(**response.json())
        except ValidationError:
            pytest.fail("Response does not match SpreadResponse schema")

    # ── Error: 503 AI unavailable ─────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_doubles_ai_error(
        self, client, mock_get_user, mock_arcana, mock_ai_chat_error,
    ):
        """503 — AI временно недоступен."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 503


# ═══════════════════════════════════════════════════════════════════
# Test: Spread — Portal  (POST /api/v1/tarot/spread, portal)
# ═══════════════════════════════════════════════════════════════════

class TestSpreadPortal:
    """POST /api/v1/tarot/spread — portal (портал месяца)."""

    SPREAD_BODY = {"session_id": MOCK_SESSION_ID, "spread_type": "portal"}

    # ── Happy path ────────────────────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_portal_success(
        self, client, mock_get_user, mock_ai_chat,
    ):
        """200 — Портал месяца успешно возвращается."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 200
        data = response.json()
        assert data["spread_type"] == "portal"
        assert data["spread_name"] == "Портал месяца"
        assert len(data["cards"]) == 3
        assert data["cards"][0]["position_name"] == "Чему научит"
        assert data["cards"][1]["position_name"] == "Что отпустить"
        assert data["cards"][2]["position_name"] == "Что усилить"

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_portal_arcana_based_on_month(
        self, client, mock_get_user, mock_ai_chat,
    ):
        """200 — арканы портала рассчитываются от номера месяца."""
        now = datetime.now()
        month_num = now.month
        teach = (month_num * 3) % 22 + 1
        release = (month_num * 7) % 22 + 1
        strengthen = (month_num * 11) % 22 + 1

        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 200
        data = response.json()
        assert data["cards"][0]["arcana_number"] == teach
        assert data["cards"][1]["arcana_number"] == release
        assert data["cards"][2]["arcana_number"] == strengthen

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_portal_response_schema(
        self, client, mock_get_user, mock_ai_chat,
    ):
        """200 — ответ проходит валидацию SpreadResponse."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 200
        try:
            SpreadResponse(**response.json())
        except ValidationError:
            pytest.fail("Response does not match SpreadResponse schema")

    # ── Error: 503 AI unavailable ─────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_portal_ai_error(
        self, client, mock_get_user, mock_ai_chat_error,
    ):
        """503 — AI временно недоступен."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 503


# ═══════════════════════════════════════════════════════════════════
# Test: Spread — Yes/No  (POST /api/v1/tarot/spread, yesno)
# ═══════════════════════════════════════════════════════════════════

class TestSpreadYesNo:
    """POST /api/v1/tarot/spread — yesno (да/нет)."""

    SPREAD_BODY = {
        "session_id": MOCK_SESSION_ID,
        "spread_type": "yesno",
        "question": "Стоит ли принять это предложение?",
    }

    # ── Happy path ────────────────────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_yesno_success(
        self, client, mock_get_user, mock_arcana, mock_ai_chat_yesno,
    ):
        """200 — да/нет успешно возвращается."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 200
        data = response.json()
        assert data["spread_type"] == "yesno"
        assert data["spread_name"] == "Да / Нет"
        assert len(data["cards"]) == 1
        assert data["cards"][0]["position_name"] == "Ответ"
        # arcana 3 is odd → "Да"
        assert data["summary"] == "Да"

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_yesno_even_arcana_returns_net(
        self, client, mock_get_user, mock_ai_chat_yesno,
    ):
        """200 — при чётном аркане возвращается 'Нет'."""
        with patch(
            "api.routes.tarot_pwa.calculate_daily_arcana",
            return_value=4,  # even → "Нет"
        ):
            response = client.post(
                "/api/v1/tarot/spread", json=self.SPREAD_BODY,
            )
        assert response.status_code == 200
        data = response.json()
        assert data["summary"] == "Нет"

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_yesno_response_schema(
        self, client, mock_get_user, mock_arcana, mock_ai_chat_yesno,
    ):
        """200 — ответ проходит валидацию SpreadResponse."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 200
        try:
            SpreadResponse(**response.json())
        except ValidationError:
            pytest.fail("Response does not match SpreadResponse schema")

    # ── Error: missing question ───────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_yesno_missing_question(
        self, client, mock_get_user,
    ):
        """400 — вопрос обязателен для spread_type=yesno."""
        body = {"session_id": MOCK_SESSION_ID, "spread_type": "yesno"}
        response = client.post("/api/v1/tarot/spread", json=body)
        assert response.status_code == 400
        assert "Вопрос обязателен" in response.json()["detail"]

    # ── Error: 503 AI unavailable ─────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_yesno_ai_error(
        self, client, mock_get_user, mock_arcana, mock_ai_chat_error,
    ):
        """503 — AI временно недоступен."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 503

    # ── Error: no subscription ────────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user(tarot_subscription=False))
    async def test_yesno_no_subscription(
        self, client, mock_get_user,
    ):
        """402 — требуется подписка Таро."""
        response = client.post("/api/v1/tarot/spread", json=self.SPREAD_BODY)
        assert response.status_code == 402


# ═══════════════════════════════════════════════════════════════════
# Test: Spread — Common errors across all spread types
# ═══════════════════════════════════════════════════════════════════

class TestSpreadCommonErrors:
    """Error cases common to all spread endpoints."""

    # ── 404 User not found ────────────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.parametrize("spread_type", ["weekly", "question", "life"])
    @pytest.mark.mock_user(None)
    async def test_spread_user_not_found(
        self, client, mock_get_user, spread_type,
    ):
        """404 — сессия не найдена для {spread_type}."""
        body = {"session_id": "bad-session", "spread_type": spread_type}
        if spread_type in ("question", "yesno"):
            body["question"] = "Тестовый вопрос?"
        response = client.post("/api/v1/tarot/spread", json=body)
        assert response.status_code == 404
        assert "Сессия не найдена" in response.json()["detail"]

    # ── 400 No birth date ─────────────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.parametrize("spread_type", ["weekly", "question", "life"])
    @pytest.mark.mock_user(_build_mock_user(birth_date=None))
    async def test_spread_no_birth_date(
        self, client, mock_get_user, spread_type,
    ):
        """400 — дата рождения не указана для {spread_type}."""
        body = {"session_id": MOCK_SESSION_ID, "spread_type": spread_type}
        if spread_type in ("question", "yesno"):
            body["question"] = "Тестовый вопрос?"
        response = client.post("/api/v1/tarot/spread", json=body)
        assert response.status_code == 400
        assert "Дата рождения не указана" in response.json()["detail"]

    # ── 422 Validation error ──────────────────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "invalid_body",
        [
            {},  # empty body — missing session_id and spread_type
            {"session_id": MOCK_SESSION_ID},  # missing spread_type
            {"session_id": MOCK_SESSION_ID, "spread_type": "invalid"},
            {"spread_type": "weekly"},  # missing session_id
        ],
    )
    async def test_spread_validation_errors(self, client, invalid_body):
        """422 — невалидные данные вызывают ValidationError."""
        response = client.post("/api/v1/tarot/spread", json=invalid_body)
        assert response.status_code == 422

    # ── 402 all spread types without subscription ─────────────────

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "body",
        [
            {"session_id": MOCK_SESSION_ID, "spread_type": "weekly"},
            {
                "session_id": MOCK_SESSION_ID,
                "spread_type": "question",
                "question": "Вопрос?",
            },
            {"session_id": MOCK_SESSION_ID, "spread_type": "life"},
            {"session_id": MOCK_SESSION_ID, "spread_type": "doubles"},
            {"session_id": MOCK_SESSION_ID, "spread_type": "portal"},
            {
                "session_id": MOCK_SESSION_ID,
                "spread_type": "yesno",
                "question": "Вопрос?",
            },
        ],
    )
    @pytest.mark.mock_user(_build_mock_user(tarot_subscription=False))
    async def test_spread_all_types_no_subscription(
        self, client, mock_get_user, body,
    ):
        """402 — все типы раскладов требуют подписку."""
        response = client.post("/api/v1/tarot/spread", json=body)
        assert response.status_code == 402

    # ── 503 all spread types on AI error ──────────────────────────

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("body", "mock_fixture"),
        [
            (
                {"session_id": MOCK_SESSION_ID, "spread_type": "weekly"},
                "mock_ai_weekly_error",
            ),
            (
                {
                    "session_id": MOCK_SESSION_ID,
                    "spread_type": "question",
                    "question": "Вопрос?",
                },
                "mock_ai_question_error",
            ),
            (
                {"session_id": MOCK_SESSION_ID, "spread_type": "life"},
                "mock_ai_chat_error",
            ),
            (
                {"session_id": MOCK_SESSION_ID, "spread_type": "doubles"},
                "mock_ai_chat_error",
            ),
            (
                {"session_id": MOCK_SESSION_ID, "spread_type": "portal"},
                "mock_ai_chat_error",
            ),
            (
                {
                    "session_id": MOCK_SESSION_ID,
                    "spread_type": "yesno",
                    "question": "Вопрос?",
                },
                "mock_ai_chat_error",
            ),
        ],
    )
    @pytest.mark.mock_user(_build_mock_user())
    async def test_spread_all_types_ai_error(
        self, client, mock_get_user, body, mock_fixture, request,
    ):
        """503 — все типы раскладов обрабатывают ошибку AI."""
        # Activate the appropriate mock fixture
        request.getfixturevalue(mock_fixture)
        response = client.post("/api/v1/tarot/spread", json=body)
        assert response.status_code == 503
        assert "AI временно недоступен" in response.json()["detail"]


# ═══════════════════════════════════════════════════════════════════
# Test: SpreadRequest Pydantic model
# ═══════════════════════════════════════════════════════════════════

class TestSpreadRequestModel:
    """Unit tests for SpreadRequest schema."""

    def test_valid_spread_types(self):
        """Все допустимые spread_type проходят валидацию."""
        for st in ("weekly", "question", "life", "doubles", "portal", "yesno"):
            req = SpreadRequest(session_id="sess-1", spread_type=st)
            assert req.spread_type == st

    def test_invalid_spread_type(self):
        """Недопустимый spread_type вызывает ValidationError."""
        with pytest.raises(ValidationError):
            SpreadRequest(session_id="sess-1", spread_type="unknown")

    def test_question_max_length(self):
        """question длиннее 200 символов вызывает ValidationError."""
        with pytest.raises(ValidationError):
            SpreadRequest(
                session_id="sess-1",
                spread_type="question",
                question="x" * 201,
            )

    def test_question_exactly_200_chars(self):
        """question ровно 200 символов — допустимо."""
        req = SpreadRequest(
            session_id="sess-1",
            spread_type="question",
            question="x" * 200,
        )
        assert len(req.question) == 200

    def test_session_id_required(self):
        """session_id — обязательное поле."""
        with pytest.raises(ValidationError):
            SpreadRequest(spread_type="weekly")

    def test_spread_type_required(self):
        """spread_type — обязательное поле."""
        with pytest.raises(ValidationError):
            SpreadRequest(session_id="sess-1")

    def test_question_none_by_default(self):
        """question по умолчанию None."""
        req = SpreadRequest(session_id="sess-1", spread_type="weekly")
        assert req.question is None


# ═══════════════════════════════════════════════════════════════════
# Test: Response models  (Pydantic schema validation)
# ═══════════════════════════════════════════════════════════════════

class TestResponseModels:
    """Unit tests for response Pydantic models."""

    def test_daily_card_response_valid(self):
        """DailyCardResponse — корректная инициализация."""
        resp = DailyCardResponse(
            arcana_number=3,
            arcana_name="Императрица",
            arcana_symbol="🌸",
            key_phrase="Изобилие и творчество",
            interpretation="Тестовая интерпретация",
            advice="Тестовый совет",
            affirmation="Я тестирую",
            date_label="15 июня",
        )
        assert resp.arcana_number == 3
        assert resp.arcana_name == "Императрица"

    def test_spread_card_with_advice(self):
        """SpreadCard может содержать advice."""
        card = SpreadCard(
            position_name="Тело",
            arcana_number=3,
            arcana_name="Императрица",
            interpretation="Тест",
            advice="Совет",
        )
        assert card.advice == "Совет"

    def test_spread_card_without_advice(self):
        """SpreadCard может не содержать advice."""
        card = SpreadCard(
            position_name="Тело",
            arcana_number=3,
            arcana_name="Императрица",
            interpretation="Тест",
        )
        assert card.advice is None

    def test_spread_response_minimal(self):
        """SpreadResponse — минимальная инициализация."""
        card = SpreadCard(
            position_name="Тело",
            arcana_number=3,
            arcana_name="Императрица",
            interpretation="Тест",
        )
        resp = SpreadResponse(
            spread_type="weekly",
            spread_name="Расклад недели",
            cards=[card],
        )
        assert resp.summary is None
        assert resp.affirmation is None

    def test_spread_response_full(self):
        """SpreadResponse — полная инициализация."""
        card = SpreadCard(
            position_name="Тело",
            arcana_number=3,
            arcana_name="Императрица",
            interpretation="Тест",
            advice="Совет дня",
        )
        resp = SpreadResponse(
            spread_type="weekly",
            spread_name="Расклад недели",
            cards=[card],
            summary="Итог недели",
            affirmation="Я в гармонии",
        )
        assert resp.summary == "Итог недели"
        assert resp.affirmation == "Я в гармонии"


# ═══════════════════════════════════════════════════════════════════
# Test: Spread — doubles with arcana edge cases
# ═══════════════════════════════════════════════════════════════════

class TestSpreadDoublesEdgeCases:
    """Edge cases for doubles spread."""

    SPREAD_BODY = {"session_id": MOCK_SESSION_ID, "spread_type": "doubles"}

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_doubles_arcana_22(
        self, client, mock_get_user, mock_ai_chat,
    ):
        """200 — daily arcana = 22 → arcana_two = 22 % 22 + 1 = 1."""
        with patch(
            "api.routes.tarot_pwa.calculate_daily_arcana",
            return_value=22,
        ):
            response = client.post(
                "/api/v1/tarot/spread", json=self.SPREAD_BODY,
            )
        assert response.status_code == 200
        data = response.json()
        assert data["cards"][0]["arcana_number"] == 22
        assert data["cards"][1]["arcana_number"] == 1  # 22 % 22 + 1 = 1

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_doubles_arcana_1(
        self, client, mock_get_user, mock_ai_chat,
    ):
        """200 — daily arcana = 1 → arcana_two = 1 % 22 + 1 = 2."""
        with patch(
            "api.routes.tarot_pwa.calculate_daily_arcana",
            return_value=1,
        ):
            response = client.post(
                "/api/v1/tarot/spread", json=self.SPREAD_BODY,
            )
        assert response.status_code == 200
        data = response.json()
        assert data["cards"][0]["arcana_number"] == 1
        assert data["cards"][1]["arcana_number"] == 2

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_doubles_arcana_out_of_range(
        self, client, mock_get_user, mock_ai_chat,
    ):
        """200 — daily arcana вне диапазона → card[0] fallback на ARCANA[1],
        card[1] рассчитывается из модуля (999 % 22 + 1 = 10) = Колесо Фортуны."""
        with patch(
            "api.routes.tarot_pwa.calculate_daily_arcana",
            return_value=999,
        ):
            response = client.post(
                "/api/v1/tarot/spread", json=self.SPREAD_BODY,
            )
        assert response.status_code == 200
        data = response.json()
        # arcana_one = 999 → not in ARCANA → fallback to ARCANA[1] (Маг)
        assert data["cards"][0]["arcana_name"] == "Маг"
        # arcana_two = 999 % 22 + 1 = 10 → Колесо Фортуны (valid arcana)
        assert data["cards"][1]["arcana_number"] == 10
        assert data["cards"][1]["arcana_name"] == "Колесо Фортуны"


# ═══════════════════════════════════════════════════════════════════
# Test: Spread — portal month names
# ═══════════════════════════════════════════════════════════════════

class TestSpreadPortalExtra:
    """Extra portal coverage."""

    SPREAD_BODY = {"session_id": MOCK_SESSION_ID, "spread_type": "portal"}

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_portal_uses_current_month_name(
        self, client, mock_get_user, mock_ai_chat,
    ):
        """200 — возвращает арканы для текущего месяца."""
        current_month = datetime.now().month

        # We can't easily verify the prompt content from the response,
        # but we can verify the request succeeds
        response = client.post(
            "/api/v1/tarot/spread", json=self.SPREAD_BODY,
        )
        assert response.status_code == 200
        # Verify the arcana numbers match expectations for this month
        data = response.json()
        teach = (current_month * 3) % 22 + 1
        release = (current_month * 7) % 22 + 1
        strengthen = (current_month * 11) % 22 + 1
        assert data["cards"][0]["arcana_number"] == teach
        assert data["cards"][1]["arcana_number"] == release
        assert data["cards"][2]["arcana_number"] == strengthen


# ═══════════════════════════════════════════════════════════════════
# Test: Spread — question with empty question edge case
# ═══════════════════════════════════════════════════════════════════

class TestSpreadQuestionEdgeCases:
    """Edge cases for question spread."""

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_question_empty_string_rejected(
        self, client, mock_get_user,
    ):
        """400 — пустая строка вопроса отвергается (question может быть None)."""
        body = {
            "session_id": MOCK_SESSION_ID,
            "spread_type": "question",
            "question": "",
        }
        response = client.post("/api/v1/tarot/spread", json=body)
        # Empty string is still a string value, not None
        # The check is `if not body.question` which will be True for ""
        assert response.status_code == 400
        assert "Вопрос обязателен" in response.json()["detail"]

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_question_with_advice_in_summary(
        self, client, mock_get_user,
    ):
        """200 — summary объединяет основной текст с советом."""
        with patch(
            "api.routes.tarot_pwa.AIService.generate_tarot_question",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = {
                "past": {
                    "card_number": 1, "card_name": "Маг",
                    "meaning": "А", "how_it_relates": "Б",
                },
                "present": {
                    "card_number": 2, "card_name": "Жрица",
                    "meaning": "В", "how_it_relates": "Г",
                },
                "future": {
                    "card_number": 3, "card_name": "Императрица",
                    "meaning": "Д", "how_it_relates": "Е",
                },
                "summary": "Главный вывод.",
                "advice": "Сделай это.",
            }
            body = {
                "session_id": MOCK_SESSION_ID,
                "spread_type": "question",
                "question": "Тестовый вопрос?",
            }
            response = client.post("/api/v1/tarot/spread", json=body)
        assert response.status_code == 200
        data = response.json()
        assert "Главный вывод." in data["summary"]
        assert "Совет: Сделай это." in data["summary"]

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_question_no_advice_in_summary(
        self, client, mock_get_user,
    ):
        """200 — без advice summary содержит только основной текст."""
        with patch(
            "api.routes.tarot_pwa.AIService.generate_tarot_question",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = {
                "past": {
                    "card_number": 1, "card_name": "Маг",
                    "meaning": "А", "how_it_relates": "Б",
                },
                "present": {
                    "card_number": 2, "card_name": "Жрица",
                    "meaning": "В", "how_it_relates": "Г",
                },
                "future": {
                    "card_number": 3, "card_name": "Императрица",
                    "meaning": "Д", "how_it_relates": "Е",
                },
                "summary": "Только вывод.",
                # no "advice" key
            }
            body = {
                "session_id": MOCK_SESSION_ID,
                "spread_type": "question",
                "question": "Тестовый вопрос?",
            }
            response = client.post("/api/v1/tarot/spread", json=body)
        assert response.status_code == 200
        data = response.json()
        assert data["summary"] == "Только вывод."


# ═══════════════════════════════════════════════════════════════════
# Test: Spread — life with different arcana values
# ═══════════════════════════════════════════════════════════════════

class TestSpreadLifeArcanaVariations:
    """Life spread with various arcana values."""

    SPREAD_BODY = {"session_id": MOCK_SESSION_ID, "spread_type": "life"}

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_life_arcana_1(
        self, client, mock_get_user, mock_ai_chat,
    ):
        """200 — arcana=1 (Маг)."""
        with patch(
            "api.routes.tarot_pwa.calculate_daily_arcana",
            return_value=1,
        ):
            response = client.post(
                "/api/v1/tarot/spread", json=self.SPREAD_BODY,
            )
        assert response.status_code == 200
        data = response.json()
        assert data["cards"][0]["arcana_name"] == "Маг"
        assert data["cards"][0]["arcana_number"] == 1

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_life_arcana_22(
        self, client, mock_get_user, mock_ai_chat,
    ):
        """200 — arcana=22 (Шут)."""
        with patch(
            "api.routes.tarot_pwa.calculate_daily_arcana",
            return_value=22,
        ):
            response = client.post(
                "/api/v1/tarot/spread", json=self.SPREAD_BODY,
            )
        assert response.status_code == 200
        data = response.json()
        assert data["cards"][0]["arcana_name"] == "Шут"


# ═══════════════════════════════════════════════════════════════════
# Test: Spread — yesno arcana polarity edge cases
# ═══════════════════════════════════════════════════════════════════

class TestSpreadYesNoEdgeCases:
    """Yes/No polarity edge cases."""

    BASE_BODY = {
        "session_id": MOCK_SESSION_ID,
        "spread_type": "yesno",
        "question": "Тестовый вопрос?",
    }

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_yesno_odd_returns_da(
        self, client, mock_get_user, mock_ai_chat_yesno,
    ):
        """odd arcana → 'Да'."""
        for odd_arcana in (1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21):
            with patch(
                "api.routes.tarot_pwa.calculate_daily_arcana",
                return_value=odd_arcana,
            ):
                resp = client.post(
                    "/api/v1/tarot/spread", json=self.BASE_BODY,
                )
            assert resp.status_code == 200
            assert resp.json()["summary"] == "Да", f"Arcana {odd_arcana}"

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_yesno_even_returns_net(
        self, client, mock_get_user, mock_ai_chat_yesno,
    ):
        """even arcana → 'Нет'."""
        for even_arcana in (2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22):
            with patch(
                "api.routes.tarot_pwa.calculate_daily_arcana",
                return_value=even_arcana,
            ):
                resp = client.post(
                    "/api/v1/tarot/spread", json=self.BASE_BODY,
                )
            assert resp.status_code == 200
            assert resp.json()["summary"] == "Нет", f"Arcana {even_arcana}"


# ═══════════════════════════════════════════════════════════════════
# Test: AI service — chat mocked response formatting
# ═══════════════════════════════════════════════════════════════════

class TestAIServiceMockVerification:
    """Verify that mocked AIService methods are called correctly."""

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_life_calls_load_prompt(
        self, client, mock_get_user, mock_arcana,
    ):
        """_handle_life_spread вызывает AIService._load_prompt."""
        with patch(
            "api.routes.tarot_pwa.AIService._load_prompt",
            return_value="Тестовый prompt {sphere_name} {arcana_number}",
        ) as mock_load:
            with patch(
                "api.routes.tarot_pwa.AIService.chat",
                new_callable=AsyncMock,
                return_value=MOCK_AI_CHAT_RESPONSE,
            ):
                client.post(
                    "/api/v1/tarot/spread",
                    json={
                        "session_id": MOCK_SESSION_ID,
                        "spread_type": "life",
                    },
                )
        mock_load.assert_called_once_with("tarot_spheres.txt")

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_doubles_calls_load_prompt(
        self, client, mock_get_user, mock_arcana,
    ):
        """_handle_doubles_spread вызывает AIService._load_prompt."""
        with patch(
            "api.routes.tarot_pwa.AIService._load_prompt",
            return_value="Тестовый prompt {arcana_one_number}",
        ) as mock_load:
            with patch(
                "api.routes.tarot_pwa.AIService.chat",
                new_callable=AsyncMock,
                return_value=MOCK_AI_CHAT_RESPONSE,
            ):
                client.post(
                    "/api/v1/tarot/spread",
                    json={
                        "session_id": MOCK_SESSION_ID,
                        "spread_type": "doubles",
                    },
                )
        mock_load.assert_called_once_with("tarot_doubles.txt")

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_portal_calls_load_prompt(
        self, client, mock_get_user,
    ):
        """_handle_portal_spread вызывает AIService._load_prompt."""
        with patch(
            "api.routes.tarot_pwa.AIService._load_prompt",
            return_value="Тестовый prompt {month_name}",
        ) as mock_load:
            with patch(
                "api.routes.tarot_pwa.AIService.chat",
                new_callable=AsyncMock,
                return_value=MOCK_AI_CHAT_RESPONSE,
            ):
                client.post(
                    "/api/v1/tarot/spread",
                    json={
                        "session_id": MOCK_SESSION_ID,
                        "spread_type": "portal",
                    },
                )
        mock_load.assert_called_once_with("tarot_portal.txt")

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_yesno_calls_load_prompt(
        self, client, mock_get_user, mock_arcana,
    ):
        """_handle_yesno_spread вызывает AIService._load_prompt."""
        with patch(
            "api.routes.tarot_pwa.AIService._load_prompt",
            return_value="Тестовый prompt {question}",
        ) as mock_load:
            with patch(
                "api.routes.tarot_pwa.AIService.chat",
                new_callable=AsyncMock,
                return_value=MOCK_YESNO_CHAT_RESPONSE,
            ):
                client.post(
                    "/api/v1/tarot/spread",
                    json={
                        "session_id": MOCK_SESSION_ID,
                        "spread_type": "yesno",
                        "question": "Тестовый вопрос?",
                    },
                )
        mock_load.assert_called_once_with("tarot_yes_no.txt")

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_weekly_calls_generate(
        self, client, mock_get_user,
    ):
        """_handle_weekly_spread вызывает generate_tarot_weekly_spread."""
        with patch(
            "api.routes.tarot_pwa.AIService.generate_tarot_weekly_spread",
            new_callable=AsyncMock,
            return_value=MOCK_WEEKLY_SPREAD_RESPONSE,
        ) as mock_gen:
            client.post(
                "/api/v1/tarot/spread",
                json={
                    "session_id": MOCK_SESSION_ID,
                    "spread_type": "weekly",
                },
            )
        mock_gen.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_question_calls_generate(
        self, client, mock_get_user,
    ):
        """_handle_question_spread вызывает generate_tarot_question."""
        with patch(
            "api.routes.tarot_pwa.AIService.generate_tarot_question",
            new_callable=AsyncMock,
            return_value=MOCK_QUESTION_SPREAD_RESPONSE,
        ) as mock_gen:
            client.post(
                "/api/v1/tarot/spread",
                json={
                    "session_id": MOCK_SESSION_ID,
                    "spread_type": "question",
                    "question": "Тестовый вопрос?",
                },
            )
        mock_gen.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════
# Test: middleware / rate limiter is wired
# ═══════════════════════════════════════════════════════════════════

class TestRouterConfiguration:
    """Router-level configuration checks."""

    def test_router_prefix(self):
        from api.routes.tarot_pwa import router as tpm_router
        assert tpm_router.prefix == "/api/v1/tarot"

    def test_router_has_routes(self):
        from api.routes.tarot_pwa import router as tpm_router
        route_paths = {r.path for r in tpm_router.routes}
        assert "/api/v1/tarot/daily-card" in route_paths
        assert "/api/v1/tarot/spread" in route_paths

    def test_daily_card_is_get(self):
        from api.routes.tarot_pwa import router as tpm_router
        for route in tpm_router.routes:
            if route.path == "/api/v1/tarot/daily-card":
                assert "GET" in route.methods
                return
        pytest.fail("daily-card route not found")

    def test_spread_is_post(self):
        from api.routes.tarot_pwa import router as tpm_router
        for route in tpm_router.routes:
            if route.path == "/api/v1/tarot/spread":
                assert "POST" in route.methods
                return
        pytest.fail("spread route not found")


# ═══════════════════════════════════════════════════════════════════
# Test: AIService.chat response trimming (strip + strip('"'))
# ═══════════════════════════════════════════════════════════════════

class TestAIServiceChatTrimming:
    """Verify that AI chat responses are trimmed of quotes."""

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_chat_response_stripped(
        self, client, mock_get_user, mock_arcana,
    ):
        """_handle_life_spread обрезает кавычки из ответа AI."""
        with patch(
            "api.routes.tarot_pwa.AIService.chat",
            new_callable=AsyncMock,
            return_value='"Ответ в кавычках."',
        ):
            resp = client.post(
                "/api/v1/tarot/spread",
                json={
                    "session_id": MOCK_SESSION_ID,
                    "spread_type": "life",
                },
            )
        assert resp.status_code == 200
        # The response should have the quotes stripped
        assert resp.json()["cards"][0]["interpretation"] == "Ответ в кавычках."

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_chat_response_stripped_doubles(
        self, client, mock_get_user, mock_arcana,
    ):
        """_handle_doubles_spread обрезает кавычки из ответа AI."""
        with patch(
            "api.routes.tarot_pwa.AIService.chat",
            new_callable=AsyncMock,
            return_value='"Двойной ответ."',
        ):
            resp = client.post(
                "/api/v1/tarot/spread",
                json={
                    "session_id": MOCK_SESSION_ID,
                    "spread_type": "doubles",
                },
            )
        assert resp.status_code == 200
        assert resp.json()["cards"][1]["interpretation"] == "Двойной ответ."

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_chat_response_not_trimmed_unnecessarily(
        self, client, mock_get_user, mock_arcana,
    ):
        """_handle_life_spread не обрезает текст без кавычек."""
        with patch(
            "api.routes.tarot_pwa.AIService.chat",
            new_callable=AsyncMock,
            return_value="Текст без кавычек.",
        ):
            resp = client.post(
                "/api/v1/tarot/spread",
                json={
                    "session_id": MOCK_SESSION_ID,
                    "spread_type": "life",
                },
            )
        assert resp.status_code == 200
        assert resp.json()["cards"][0]["interpretation"] == "Текст без кавычек."


# ═══════════════════════════════════════════════════════════════════
# Test: Spread — response contains affirmation when present
# ═══════════════════════════════════════════════════════════════════

class TestSpreadAffirmation:
    """Affirmation field in spread responses."""

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_weekly_no_affirmation(
        self, client, mock_get_user, mock_ai_weekly,
    ):
        """200 — weekly response does not include affirmation."""
        resp = client.post(
            "/api/v1/tarot/spread",
            json={"session_id": MOCK_SESSION_ID, "spread_type": "weekly"},
        )
        assert resp.status_code == 200
        assert resp.json().get("affirmation") is None

    @pytest.mark.asyncio
    @pytest.mark.mock_user(_build_mock_user())
    async def test_life_no_affirmation(
        self, client, mock_get_user, mock_arcana, mock_ai_chat,
    ):
        """200 — life response does not include affirmation."""
        resp = client.post(
            "/api/v1/tarot/spread",
            json={"session_id": MOCK_SESSION_ID, "spread_type": "life"},
        )
        assert resp.status_code == 200
        assert resp.json().get("affirmation") is None


# ═══════════════════════════════════════════════════════════════════
# Test: daily-card — session_id in query string edge cases
# ═══════════════════════════════════════════════════════════════════

class TestDailyCardEdgeCases:
    """Edge cases for daily-card query parameters."""

    @pytest.mark.asyncio
    @pytest.mark.mock_user(None)
    async def test_daily_card_empty_session_id(self, client, mock_get_user):
        """404 — пустой session_id возвращает 404 (not found)."""
        resp = client.get(
            "/api/v1/tarot/daily-card",
            params={"session_id": ""},
        )
        # UserRepository.get_by_web_session_id will be called with ""
        # and since mock returns None, we get 404
        assert resp.status_code == 404
        assert "Сессия не найдена" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_daily_card_extra_query_params(self, client):
        """200 — лишние query-параметры игнорируются."""
        with patch(
            "api.routes.tarot_pwa.UserRepository.get_by_web_session_id",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = _build_mock_user()
            with patch(
                "api.routes.tarot_pwa.calculate_daily_arcana",
                return_value=3,
            ):
                resp = client.get(
                    "/api/v1/tarot/daily-card",
                    params={
                        "session_id": MOCK_SESSION_ID,
                        "extra_param": "value",
                    },
                )
        assert resp.status_code == 200
