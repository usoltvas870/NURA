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
    async def test_create_payment_returns_url(self):
        with patch("core.services.payment.YooPayment.create") as mock_create:
            payment = MagicMock()
            payment.id = "pm-123"
            payment.status = "pending"
            payment.confirmation.confirmation_url = "https://test.url/pay"
            mock_create.return_value = payment

            result = await PaymentService.create_payment(
                telegram_id=12345, amount=690, description="Test"
            )

        assert result["id"] == "pm-123"
        assert result["status"] == "pending"
        assert result["payment_url"] == "https://test.url/pay"

    async def test_check_payment_returns_status(self):
        with patch("core.services.payment.YooPayment.find_one") as mock_find:
            payment = MagicMock()
            payment.id = "pm-456"
            payment.status = "succeeded"
            payment.paid = True
            mock_find.return_value = payment

            result = await PaymentService.check_payment("pm-456")

        assert result["id"] == "pm-456"
        assert result["status"] == "succeeded"
        assert result["paid"] is True


@pytest.mark.asyncio
class TestReportAccess:
    async def test_subscriber_cannot_generate_report_for_other_date(self):
        user = _make_user(subscription_status="premium", birth_date="01.01.2000")
        result = await can_access_full_report(user, "15.06.1998")
        assert result == (False, "other_person")

    async def test_subscriber_can_generate_report_for_own_date(self):
        user = _make_user(subscription_status="premium", birth_date="01.01.2000")
        result = await can_access_full_report(user, "01.01.2000")
        assert result == (True, "subscription")

    async def test_free_user_can_buy_report_for_other_person(self):
        user = _make_user(subscription_status="free", birth_date="01.01.2000")
        result = await can_access_full_report(user, "15.06.1998")
        assert result == (False, "other_person")

    async def test_free_user_needs_to_pay_for_own_date(self):
        user = _make_user(subscription_status="free", birth_date="01.01.2000")
        result = await can_access_full_report(user, "01.01.2000")
        assert result == (False, "pay")
