from unittest.mock import MagicMock, patch

import pytest

from core.services.access import can_access_full_report
from core.services.payment import PaymentService


def _make_user(
    subscription_status: str = "free",
    birth_date: str = "01.01.2000",
) -> MagicMock:
    user = MagicMock()
    user.subscription_status = subscription_status
    user.birth_date = birth_date
    return user


@pytest.mark.asyncio
class TestPayment:
    async def test_create_subscription_returns_url(self):
        with patch("core.services.payment.YooPayment.create") as mock_create:
            payment = MagicMock()
            payment.id = "pm-123"
            payment.status = "pending"
            payment.confirmation.confirmation_url = "https://test.url/pay"
            payment.payment_method.id = "pmt-456"
            mock_create.return_value = payment

            result = await PaymentService.create_subscription(telegram_id=12345)

        assert result["id"] == "pm-123"
        assert result["status"] == "pending"
        assert result["payment_url"] == "https://test.url/pay"
        assert result["payment_method_id"] == "pmt-456"


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
