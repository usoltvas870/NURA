# ═══════════════════════════════════════════════════════════════════════
# CAVEMAN-PROTOCOL: тесты payment — YooKassa mock, webhook, service
# ═══════════════════════════════════════════════════════════════════════

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.repositories.payment import PaymentRepository
from core.repositories.user import UserRepository
from core.services.access import can_access_full_report
from core.services.payment import PaymentService


# ─────────────────────────────────────────────────────────────────────
# Вспомогательные фабрики
# ─────────────────────────────────────────────────────────────────────

def _make_user(
    subscription_status: str = "free",
    birth_date: str = "01.01.2000",
) -> MagicMock:
    user = MagicMock()
    user.subscription_status = subscription_status
    user.birth_date = birth_date
    return user


def _mock_yoo_payment(
    payment_id: str = "pm-test-001",
    status: str = "pending",
    confirmation_url: str = "https://test.url/pay",
    payment_method_id: str = "pmt-test-001",
) -> MagicMock:
    """Фабрика мок-объекта YooKassa Payment."""
    pm = MagicMock()
    pm.id = payment_id
    pm.status = status
    pm.confirmation.confirmation_url = confirmation_url
    pm.payment_method.id = payment_method_id
    return pm


# ─────────────────────────────────────────────────────────────────────
# Фикстуры для реальной БД (SQLite in-memory)
# ─────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def session_factory(db_engine):
    """async_sessionmaker поверх in-memory SQLite (берём engine из conftest)."""
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    return factory


@pytest_asyncio.fixture
async def payment_in_db(session_factory, test_user):
    """Создаём реальный Payment в БД для webhook-тестов."""
    repo = PaymentRepository(session_factory)
    payment = await repo.create(
        user_id=test_user.id,
        amount=890,
        yookassa_id="yo-tg-001",
        payment_type="subscription",
    )
    return payment


@pytest_asyncio.fixture
async def matrix_payment_in_db(session_factory, test_user):
    """Matrix-платёж в БД."""
    repo = PaymentRepository(session_factory)
    payment = await repo.create(
        user_id=test_user.id,
        amount=890,
        yookassa_id="yo-matrix-001",
        payment_type="matrix",
    )
    return payment


@pytest_asyncio.fixture
async def web_matrix_payment_in_db(session_factory, test_user):
    """Web-matrix платёж в БД."""
    repo = PaymentRepository(session_factory)
    payment = await repo.create(
        user_id=test_user.id,
        amount=890,
        yookassa_id="yo-web-matrix-001",
        payment_type="web_matrix",
    )
    return payment


# ─────────────────────────────────────────────────────────────────────
# Фикстура FastAPI TestClient для эндпоинта /api/v1/payment/webhook
# ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def app():
    """Изолированное FastAPI-приложение с роутером payment, без лимитера."""
    import api.deps as deps_mod
    from api.routes.payment import router as payment_router

    deps_mod.limiter.enabled = False

    _app = FastAPI()
    _app.include_router(payment_router)
    _app.state.limiter = None

    yield _app

    deps_mod.limiter.enabled = True


@pytest.fixture
def client(app):
    return TestClient(app)


# ═══════════════════════════════════════════════════════════════════════
# 1. PaymentService — создание платежей (YooKassa mocked)
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestPaymentCreate:
    """Мокаем YooKassa.Payment.create и проверяем что возвращается."""

    async def test_create_subscription_returns_url(self):
        """Уже есть — дублируем для completeness (перезапись)."""
        with patch("core.services.payment.YooPayment.create") as mock_create:
            pm = _mock_yoo_payment(
                payment_id="pm-123",
                status="pending",
                confirmation_url="https://test.url/pay",
                payment_method_id="pmt-456",
            )
            mock_create.return_value = pm

            result = await PaymentService.create_subscription(telegram_id=12345)

        assert result["id"] == "pm-123"
        assert result["status"] == "pending"
        assert result["payment_url"] == "https://test.url/pay"
        assert result["payment_method_id"] == "pmt-456"

    async def test_create_tarot_payment(self):
        """Создание таро-подписки — метаданные содержат payment_type=tarot."""
        with patch("core.services.payment.YooPayment.create") as mock_create:
            pm = _mock_yoo_payment(payment_id="pm-tarot-1")
            mock_create.return_value = pm

            result = await PaymentService.create_tarot_payment(telegram_id=67890)

        assert result["id"] == "pm-tarot-1"
        assert result["status"] == "pending"

        # Проверяем что YooKassa вызван с нужными параметрами
        call_args, call_kwargs = mock_create.call_args
        body = call_args[0]
        assert body["metadata"]["telegram_id"] == 67890
        assert body["metadata"]["payment_type"] == "tarot"
        assert body["description"] == "NURA — Таро-ритуалы (подписка)"

    async def test_create_matrix_payment(self):
        """Матрица (разовая) — save_payment_method=False."""
        with patch("core.services.payment.YooPayment.create") as mock_create:
            pm = _mock_yoo_payment(payment_id="pm-matrix-1")
            mock_create.return_value = pm

            result = await PaymentService.create_matrix_payment(telegram_id=111)

        assert result["id"] == "pm-matrix-1"
        call_body = mock_create.call_args[0][0]
        assert call_body["metadata"]["payment_type"] == "matrix"
        assert call_body["save_payment_method"] is False
        assert "разовый" in call_body["description"]

    async def test_create_web_matrix_payment(self):
        """Веб-матрица — метаданные с user_id, report_token, payment_type=web_matrix."""
        import uuid

        uid = uuid.uuid4()
        with patch("core.services.payment.YooPayment.create") as mock_create:
            pm = _mock_yoo_payment(payment_id="pm-web-matrix-1")
            mock_create.return_value = pm

            result = await PaymentService.create_web_matrix_payment(
                user_id=uid, report_token="tok-abc"
            )

        assert result["id"] == "pm-web-matrix-1"
        call_body = mock_create.call_args[0][0]
        assert call_body["metadata"]["user_id"] == str(uid)
        assert call_body["metadata"]["payment_type"] == "web_matrix"
        assert call_body["metadata"]["report_token"] == "tok-abc"
        assert call_body["save_payment_method"] is False

    async def test_create_web_tarot_payment(self):
        """Веб-таро — метаданные с user_id, payment_type=web_tarot."""
        import uuid

        uid = uuid.uuid4()
        with patch("core.services.payment.YooPayment.create") as mock_create:
            pm = _mock_yoo_payment(payment_id="pm-web-tarot-1")
            mock_create.return_value = pm

            result = await PaymentService.create_web_tarot_payment(user_id=uid)

        assert result["id"] == "pm-web-tarot-1"
        call_body = mock_create.call_args[0][0]
        assert call_body["metadata"]["user_id"] == str(uid)
        assert call_body["metadata"]["payment_type"] == "web_tarot"

    async def test_create_payment_sets_idempotence_key(self):
        """Каждый вызов create использует свой idempotence_key (uuid хэш)."""
        with patch("core.services.payment.YooPayment.create") as mock_create:
            mock_create.return_value = _mock_yoo_payment()

            await PaymentService.create_subscription(telegram_id=999)

            # Второй аргумент — idempotence_key
            _key = mock_create.call_args[0][1]
            assert isinstance(_key, str)
            assert len(_key) == 32  # uuid4().hex[:32]


# ═══════════════════════════════════════════════════════════════════════
# 2. PaymentService.process_webhook — реальная БД + мок YooKassa (не нужен)
# ═══════════════════════════════════════════════════════════════════════
# process_webhook общается только с PaymentRepository / UserRepository.
# Используем реальную SQLite in-memory БД из фикстур conftest.

@pytest.mark.asyncio
class TestProcessWebhook:
    """Проверка логики webhook через PaymentService.process_webhook."""

    async def test_ignores_non_succeeded_event(self, session_factory):
        """Любой event кроме payment.succeeded → ignored."""
        result = await PaymentService.process_webhook(
            session_factory,
            {"event": "payment.waiting_for_capture", "object": {"id": "xxx"}},
        )
        assert result == {"status": "ignored"}

    async def test_ignores_canceled_event(self, session_factory):
        """payment.canceled тоже игнорируем."""
        result = await PaymentService.process_webhook(
            session_factory,
            {"event": "payment.canceled", "object": {"id": "xxx"}},
        )
        assert result == {"status": "ignored"}

    async def test_missing_telegram_id_and_yookassa_id(self, session_factory):
        """Нет telegram_id и yookassa_id → needs_review."""
        result = await PaymentService.process_webhook(
            session_factory,
            {
                "event": "payment.succeeded",
                "object": {"id": None, "metadata": {}},
            },
        )
        assert result["status"] == "needs_review"
        assert "Missing telegram_id or payment id" in result["detail"]

    async def test_missing_yookassa_id(self, session_factory):
        """Есть telegram_id, но нет yookassa_id → needs_review."""
        result = await PaymentService.process_webhook(
            session_factory,
            {
                "event": "payment.succeeded",
                "object": {
                    "id": None,
                    "metadata": {"telegram_id": "12345"},
                },
            },
        )
        assert result["status"] == "needs_review"

    async def test_invalid_telegram_id_format(self, session_factory):
        """telegram_id не число → needs_review."""
        result = await PaymentService.process_webhook(
            session_factory,
            {
                "event": "payment.succeeded",
                "object": {
                    "id": "yo-001",
                    "metadata": {"telegram_id": "not-a-number"},
                },
            },
        )
        assert result["status"] == "needs_review"
        assert "Invalid telegram_id" in result["detail"]

    async def test_payment_not_found_raises(self, session_factory):
        """Платёж с таким yookassa_id нет в БД → ValueError 404."""
        with pytest.raises(ValueError, match="Payment not found"):
            await PaymentService.process_webhook(
                session_factory,
                {
                    "event": "payment.succeeded",
                    "object": {
                        "id": "yo-nonexistent",
                        "metadata": {"telegram_id": "12345"},
                    },
                },
            )

    async def test_idempotent_skip_already_succeeded(
        self, session_factory, test_user, payment_in_db,
    ):
        """Платёж уже succeeded → idempotent skip."""
        # Сначала проводим успешно
        result1 = await PaymentService.process_webhook(
            session_factory,
            {
                "event": "payment.succeeded",
                "object": {
                    "id": "yo-tg-001",
                    "metadata": {"telegram_id": str(test_user.telegram_id)},
                },
            },
        )
        assert result1 == {"ok": True}

        # Повторный вызов — idempotent
        result2 = await PaymentService.process_webhook(
            session_factory,
            {
                "event": "payment.succeeded",
                "object": {
                    "id": "yo-tg-001",
                    "metadata": {"telegram_id": str(test_user.telegram_id)},
                },
            },
        )
        assert result2 == {"ok": True, "idempotent": True}

    async def test_telegram_subscription_activated(
        self, session_factory, test_user, payment_in_db,
    ):
        """Успешный payment.succeeded → подписка активирована."""
        result = await PaymentService.process_webhook(
            session_factory,
            {
                "event": "payment.succeeded",
                "object": {
                    "id": "yo-tg-001",
                    "metadata": {"telegram_id": str(test_user.telegram_id)},
                },
            },
        )
        assert result == {"ok": True}

        # Проверяем что пользователь стал premium
        user_repo = UserRepository(session_factory)
        user = await user_repo.get(test_user.id)
        assert user is not None
        assert user.subscription_status == "premium"

    async def test_telegram_matrix_activated(
        self, session_factory, test_user, matrix_payment_in_db,
    ):
        """Платеж типа matrix → has_matrix=True."""
        await PaymentService.process_webhook(
            session_factory,
            {
                "event": "payment.succeeded",
                "object": {
                    "id": "yo-matrix-001",
                    "metadata": {
                        "telegram_id": str(test_user.telegram_id),
                        "payment_type": "matrix",
                    },
                },
            },
        )
        repo = UserRepository(session_factory)
        user = await repo.get(test_user.id)
        assert user.has_matrix is True

    async def test_telegram_subscription_no_user_reverts(
        self, session_factory, payment_in_db,
    ):
        """Пользователь не найден → revert платежа в pending."""
        result = await PaymentService.process_webhook(
            session_factory,
            {
                "event": "payment.succeeded",
                "object": {
                    "id": "yo-tg-001",
                    "metadata": {"telegram_id": "999999999999"},
                },
            },
        )
        assert result["status"] == "needs_review"
        assert "User not found" in result["detail"]

        # Платёж вернулся в pending
        repo = PaymentRepository(session_factory)
        payment = await repo.get_by_yookassa_id("yo-tg-001")
        assert payment is not None
        assert payment.status == "pending"

    async def test_web_matrix_full_flow(
        self, session_factory, test_user, web_matrix_payment_in_db,
    ):
        """web_matrix — активация has_matrix, статус succeeded."""
        result = await PaymentService.process_webhook(
            session_factory,
            {
                "event": "payment.succeeded",
                "object": {
                    "id": "yo-web-matrix-001",
                    "metadata": {
                        "user_id": str(test_user.id),
                        "payment_type": "web_matrix",
                    },
                },
            },
        )
        assert result["ok"] is True

        repo = UserRepository(session_factory)
        user = await repo.get(test_user.id)
        assert user.has_matrix is True

    async def test_web_matrix_missing_user_id(
        self, session_factory, web_matrix_payment_in_db,
    ):
        """web_matrix без user_id в metadata → needs_review."""
        result = await PaymentService.process_webhook(
            session_factory,
            {
                "event": "payment.succeeded",
                "object": {
                    "id": "yo-web-matrix-001",
                    "metadata": {"payment_type": "web_matrix"},
                },
            },
        )
        assert result["status"] == "needs_review"
        assert "Missing user_id" in result["detail"]

    async def test_web_matrix_invalid_user_id(
        self, session_factory, web_matrix_payment_in_db,
    ):
        """web_matrix с некорректным user_id → needs_review."""
        result = await PaymentService.process_webhook(
            session_factory,
            {
                "event": "payment.succeeded",
                "object": {
                    "id": "yo-web-matrix-001",
                    "metadata": {
                        "user_id": "not-a-uuid",
                        "payment_type": "web_matrix",
                    },
                },
            },
        )
        assert result["status"] == "needs_review"
        assert "Invalid user_id" in result["detail"]

    async def test_web_matrix_user_id_mismatch(
        self, session_factory, test_user, web_matrix_payment_in_db,
    ):
        """web_matrix — несовпадение user_id в метаданных с payment.user_id → needs_review."""
        import uuid

        fake_uuid = uuid.uuid4()
        result = await PaymentService.process_webhook(
            session_factory,
            {
                "event": "payment.succeeded",
                "object": {
                    "id": "yo-web-matrix-001",
                    "metadata": {
                        "user_id": str(fake_uuid),
                        "payment_type": "web_matrix",
                    },
                },
            },
        )
        assert result["status"] == "needs_review"
        assert "Payment user_id mismatch" in result["detail"]

    async def test_web_matrix_missing_yookassa_id(
        self, session_factory, web_matrix_payment_in_db,
    ):
        """web_matrix без yookassa_id → needs_review."""
        result = await PaymentService.process_webhook(
            session_factory,
            {
                "event": "payment.succeeded",
                "object": {
                    "id": None,
                    "metadata": {
                        "user_id": "00000000-0000-0000-0000-000000000000",
                        "payment_type": "web_matrix",
                    },
                },
            },
        )
        assert result["status"] == "needs_review"
        assert "Missing payment id" in result["detail"]

    async def test_web_tarot_full_flow(
        self, session_factory, test_user,
    ):
        """web_tarot — активация таро-подписки."""
        # Сначала создаём платёж
        pay_repo = PaymentRepository(session_factory)
        await pay_repo.create(
            user_id=test_user.id,
            amount=990,
            yookassa_id="yo-web-tarot-001",
            payment_type="web_tarot",
        )

        result = await PaymentService.process_webhook(
            session_factory,
            {
                "event": "payment.succeeded",
                "object": {
                    "id": "yo-web-tarot-001",
                    "metadata": {
                        "user_id": str(test_user.id),
                        "payment_type": "web_tarot",
                    },
                },
            },
        )
        assert result["ok"] is True

        user_repo = UserRepository(session_factory)
        user = await user_repo.get(test_user.id)
        assert user.tarot_subscription is True


# ═══════════════════════════════════════════════════════════════════════
# 3. API endpoint — POST /api/v1/payment/webhook
# ═══════════════════════════════════════════════════════════════════════

class TestPaymentWebhookEndpoint:
    """Тестируем роутер через TestClient (мокаем PaymentService.process_webhook)."""

    def test_webhook_returns_200_on_success(self, client):
        """Успешный webhook → 200 + ok."""
        with patch.object(PaymentService, "process_webhook", new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True}

            resp = client.post(
                "/api/v1/payment/webhook",
                json={"event": "payment.succeeded", "object": {"id": "yo-1"}},
            )

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_webhook_returns_404_on_value_error(self, client):
        """ValueError из сервиса → 404."""
        with patch.object(PaymentService, "process_webhook", new_callable=AsyncMock) as mock:
            mock.side_effect = ValueError("Payment not found")

            resp = client.post(
                "/api/v1/payment/webhook",
                json={"event": "payment.succeeded", "object": {"id": "yo-none"}},
            )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Payment not found"

    def test_webhook_invalid_data_ignored_event(self, client):
        """Валидный JSON, но событие не payment.succeeded → 200 + ignored."""
        with patch.object(PaymentService, "process_webhook", new_callable=AsyncMock) as mock:
            mock.return_value = {"status": "ignored"}

            resp = client.post(
                "/api/v1/payment/webhook",
                json={"event": "payment.waiting_for_capture", "object": {}},
            )

            assert resp.status_code == 200
            assert resp.json() == {"status": "ignored"}


# ═══════════════════════════════════════════════════════════════════════
# 4. TestReportAccess (был, оставляем для совместимости)
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestReportAccess:
    async def test_subscriber_can_access(self):
        user = _make_user(subscription_status="premium", birth_date="01.01.2000")
        result = await can_access_full_report(user)
        assert result is True

    async def test_free_user_cannot_access(self):
        user = _make_user(subscription_status="free", birth_date="01.01.2000")
        result = await can_access_full_report(user)
        assert result is False
