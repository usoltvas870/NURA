"""Owner-prelaunch broadcast and background-task safety."""

from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from core.models import BroadcastDelivery
from core.schemas.broadcast import CampaignCreate
from core.services.broadcast import BroadcastCampaignService, BroadcastServiceError
from core.services.broadcast_telegram import BroadcastSendResult
from core.tasks import (
    beat_schedule_for,
    delete_inactive_users,
    send_daily_card,
    send_daily_tarot_card,
    send_monthly_tarot_portal,
    send_weekly_tarot_spread,
)


class FakeBroadcastTelegram:
    def __init__(self) -> None:
        self.text_calls: list[int] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def send_text(self, chat_id, *_args, **_kwargs):
        self.text_calls.append(chat_id)
        return BroadcastSendResult(message_id=100 + len(self.text_calls))

    async def send_media(self, chat_id, *_args, **_kwargs):
        return BroadcastSendResult(message_id=200 + chat_id)


def campaign_body() -> CampaignCreate:
    return CampaignCreate.model_validate(
        {
            "campaign_type": "editorial",
            "text": "Owner-only bounded test",
            "ctas": [
                {
                    "key": "primary",
                    "label": "Профиль",
                    "destination": "profile",
                }
            ],
            "segment_type": "all_editorial_enabled",
            "segment_parameters": {},
        }
    )


@pytest.fixture(autouse=True)
def owner_prelaunch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "prelaunch_owner_only", True)
    monkeypatch.setattr(settings, "prelaunch_telegram_allowed_user_ids", "101")
    monkeypatch.setattr(settings, "payments_enabled", False)
    monkeypatch.setattr(settings, "broadcast_admin_telegram_ids", "101,999")
    monkeypatch.setattr(settings, "admin_telegram_id", None)


@pytest.mark.asyncio
async def test_broadcast_test_send_is_intersected_with_global_allowlist(
    db_engine,
) -> None:
    factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    adapter = FakeBroadcastTelegram()
    service = BroadcastCampaignService(factory, adapter=adapter)
    campaign = await service.create(campaign_body(), actor="owner")

    tested = await service.test_send(
        campaign.public_id,
        actor="owner",
        reason="prelaunch verification",
    )

    assert tested.tested_version == 1
    assert adapter.text_calls == [101]


@pytest.mark.asyncio
async def test_public_campaign_launch_is_forbidden_without_materialization(
    db_engine,
) -> None:
    factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    service = BroadcastCampaignService(factory, adapter=FakeBroadcastTelegram())
    campaign = await service.create(campaign_body(), actor="owner")

    with pytest.raises(
        BroadcastServiceError,
        match="prelaunch_campaign_launch_forbidden",
    ):
        await service.launch(
            campaign.public_id,
            expected_version=1,
            idempotency_key="owner-prelaunch-launch",
            actor="owner",
            reason="must stay closed",
        )

    async with factory() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(BroadcastDelivery)
            )
            == 0
        )


def test_prelaunch_beat_contains_only_launch_critical_recovery_tasks() -> None:
    schedule = beat_schedule_for(settings)

    assert set(schedule) == {
        "reconcile-chat-deliveries",
        "dispatch-report-generation-jobs",
        "reconcile-report-generation-jobs",
    }
    assert all(
        "payment" not in item
        and "broadcast" not in item
        and "delete" not in item
        and "tarot" not in item
        for item in schedule
    )


@pytest.mark.parametrize(
    "task",
    [
        send_daily_card,
        send_daily_tarot_card,
        send_weekly_tarot_spread,
        send_monthly_tarot_portal,
    ],
)
def test_mass_editorial_and_expanded_tarot_tasks_do_not_execute(task) -> None:
    with patch("core.tasks._run_async") as run_async:
        result = task.run()

    assert result["disabled"] is True
    assert result["sent"] == 0
    run_async.assert_not_called()


def test_destructive_inactive_user_deletion_does_not_execute() -> None:
    with patch("core.tasks.get_async_sessionmaker") as session_factory:
        result = delete_inactive_users.run()

    assert result == {
        "deleted": 0,
        "error_code": "prelaunch_inactive_user_deletion_disabled",
    }
    session_factory.assert_not_called()
