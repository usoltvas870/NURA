from unittest.mock import MagicMock, patch

import pytest

from core.services.payment import PaymentService


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
                telegram_id=12345, amount=590, description="Test"
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
