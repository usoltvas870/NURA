from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from core.models import (
    BroadcastCampaign,
    BroadcastCTAClick,
    BroadcastCTAClickEvent,
    BroadcastDelivery,
    BroadcastDeliveryState,
    Order,
    OrderStatus,
    Report,
    ReportType,
    TelegramSuppression,
    User,
)
from core.repositories.broadcast import BroadcastRepository
from core.schemas.broadcast import CampaignCreate, CampaignUpdate
from core.services.broadcast import BroadcastCampaignService, BroadcastServiceError
from core.services.broadcast_telegram import (
    BroadcastSendResult,
    BroadcastTelegramError,
)
from core.services.account_deletion import AccountDeletionService


class FakeBroadcastTelegram:
    def __init__(self, outcomes: list[object] | None = None) -> None:
        self.outcomes = list(outcomes or [])
        self.media_calls: list[tuple] = []
        self.text_calls: list[tuple] = []
        self.next_id = 100

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    def _result(self) -> BroadcastSendResult:
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            if isinstance(outcome, int):
                return BroadcastSendResult(outcome)
        self.next_id += 1
        return BroadcastSendResult(self.next_id)

    async def send_media(self, chat_id: int, media_type: str, file_id: str):
        self.media_calls.append((chat_id, media_type, file_id))
        return self._result()

    async def send_text(self, chat_id: int, text: str, ctas: list[dict], token: str, *, test: bool = False):
        self.text_calls.append((chat_id, text, ctas, token, test))
        return self._result()


def campaign_body(
    *,
    segment_type: str = "all_editorial_enabled",
    segment_parameters: dict[str, int] | None = None,
    media: bool = False,
) -> CampaignCreate:
    return CampaignCreate.model_validate(
        {
            "campaign_type": "editorial",
            "text": "<b>Полезное сообщение NURA</b>",
            "media_type": "photo" if media else None,
            "media_file_id": "telegram-file-id" if media else None,
            "ctas": [
                {"key": "primary", "label": "Открыть профиль", "destination": "profile"},
                {"key": "secondary", "label": "Настройки", "destination": "settings"},
            ],
            "segment_type": segment_type,
            "segment_parameters": segment_parameters or {},
        }
    )


async def add_user(factory, telegram_id: int, **values) -> User:
    async with factory() as session:
        account_status = values.pop("account_status", "active")
        user = User(
            id=uuid.uuid4(),
            telegram_id=telegram_id,
            first_name=f"User {telegram_id}",
            account_status=account_status,
            **values,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.mark.asyncio
async def test_campaign_lifecycle_requires_exact_test_and_launch_is_idempotent(
    db_engine, monkeypatch
):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    await add_user(factory, 101, birth_date="01.01.2000", pd_consent_at=datetime.now(timezone.utc))
    fake = FakeBroadcastTelegram()
    service = BroadcastCampaignService(factory, adapter=fake)
    monkeypatch.setattr(settings, "broadcast_admin_telegram_ids", "9001,9002")
    monkeypatch.setattr(settings, "admin_telegram_id", None)
    dispatches: list[str] = []
    monkeypatch.setattr(
        "core.tasks.dispatch_broadcast_campaign.delay", lambda campaign_id: dispatches.append(campaign_id)
    )

    campaign = await service.create(campaign_body(), actor="operator.one")
    with pytest.raises(BroadcastServiceError, match="exact_version_not_tested"):
        await service.launch(
            campaign.public_id,
            expected_version=1,
            idempotency_key="launch-key-001",
            actor="operator.one",
            reason="launch",
        )

    estimated, count = await service.estimate(campaign.public_id, actor="operator.one", reason=None)
    assert count == 1 and estimated.preview_version == 1
    tested = await service.test_send(campaign.public_id, actor="operator.one", reason="review")
    assert tested.tested_version == 1
    assert len(fake.text_calls) == 2

    launched, new_launch = await service.launch(
        campaign.public_id,
        expected_version=1,
        idempotency_key="launch-key-001",
        actor="operator.one",
        reason="approved",
    )
    repeated, repeated_new = await service.launch(
        campaign.public_id,
        expected_version=1,
        idempotency_key="launch-key-001",
        actor="operator.one",
        reason="approved",
    )
    assert new_launch is True and repeated_new is False
    assert repeated.id == launched.id and dispatches == [str(launched.id)]
    async with factory() as session:
        assert await session.scalar(select(func.count(BroadcastDelivery.id))) == 1


@pytest.mark.asyncio
async def test_zero_recipient_launch_completes_without_dispatch(db_engine, monkeypatch):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    fake = FakeBroadcastTelegram()
    service = BroadcastCampaignService(factory, adapter=fake)
    monkeypatch.setattr(settings, "broadcast_admin_telegram_ids", "9001")
    monkeypatch.setattr(settings, "admin_telegram_id", None)
    dispatches: list[str] = []
    monkeypatch.setattr(
        "core.tasks.dispatch_broadcast_campaign.delay", lambda campaign_id: dispatches.append(campaign_id)
    )
    campaign = await service.create(campaign_body(), actor="operator")
    _, count = await service.estimate(campaign.public_id, actor="operator", reason=None)
    await service.test_send(campaign.public_id, actor="operator", reason=None)
    launched, is_new = await service.launch(
        campaign.public_id,
        expected_version=1,
        idempotency_key="zero-recipient-launch",
        actor="operator",
        reason=None,
    )
    repeated, repeated_new = await service.launch(
        campaign.public_id,
        expected_version=1,
        idempotency_key="zero-recipient-launch",
        actor="operator",
        reason=None,
    )
    assert count == 0
    assert is_new is True and repeated_new is False
    assert launched.status == repeated.status == "completed"
    assert launched.completed_at is not None
    assert dispatches == []


@pytest.mark.asyncio
async def test_update_increments_version_and_invalidates_test_and_preview(db_engine, monkeypatch):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    await add_user(factory, 102)
    monkeypatch.setattr(settings, "broadcast_admin_telegram_ids", "9001")
    monkeypatch.setattr(settings, "admin_telegram_id", None)
    service = BroadcastCampaignService(factory, adapter=FakeBroadcastTelegram())
    campaign = await service.create(campaign_body(), actor="operator.one")
    await service.estimate(campaign.public_id, actor="operator.one", reason=None)
    await service.test_send(campaign.public_id, actor="operator.one", reason=None)
    updated = await service.update(
        campaign.public_id,
        CampaignUpdate(text="Новая версия"),
        actor="operator.two",
    )
    assert updated.content_version == 2
    assert updated.tested_version is None and updated.preview_version is None
    assert updated.status == "draft"


def test_update_rejects_blank_content():
    with pytest.raises(ValueError, match="blank_value"):
        CampaignUpdate(text="   ")
    with pytest.raises(ValueError, match="blank_value"):
        CampaignUpdate(media_type="photo", media_file_id="   ")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("segment_type", "parameters", "expected_ids"),
    [
        ("all_editorial_enabled", {}, {201, 202, 203, 204}),
        ("mini_completed_without_full_purchase", {}, {201}),
        ("full_report_purchasers", {}, {202}),
        ("onboarding_incomplete", {}, {203}),
        ("inactive", {"inactive_days": 30}, {204}),
    ],
)
async def test_canonical_segments_use_current_tables(
    db_engine, segment_type, parameters, expected_ids
):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    mini = await add_user(factory, 201, birth_date="01.01.2000", pd_consent_at=now, last_activity_at=now)
    paid = await add_user(factory, 202, birth_date="01.01.2000", pd_consent_at=now, last_activity_at=now)
    await add_user(factory, 203, birth_date=None, pd_consent_at=None, last_activity_at=now)
    await add_user(factory, 204, birth_date="01.01.2000", pd_consent_at=now, last_activity_at=now - timedelta(days=60))
    await add_user(factory, 205, editorial_messages_enabled=False)
    await add_user(factory, 206, account_status="blocked")
    async with factory() as session:
        session.add(
            Report(
                id=uuid.uuid4(),
                user_id=mini.id,
                report_type=ReportType.MINI.value,
                token="mini-segment",
                matrix_data={"ok": True},
            )
        )
        session.add(
            Order(
                id=uuid.uuid4(),
                public_id="paid-segment-order",
                user_id=paid.id,
                telegram_id_snapshot=paid.telegram_id,
                status=OrderStatus.PAID,
                idempotency_key="paid-segment-key",
                paid_at=now,
            )
        )
        await session.commit()
    service = BroadcastCampaignService(factory)
    campaign = await service.create(
        campaign_body(segment_type=segment_type, segment_parameters=parameters),
        actor="operator",
    )
    repository = BroadcastRepository(factory)
    async with factory() as session:
        stored = await session.get(BroadcastCampaign, campaign.id)
        rows = (await session.execute(repository._eligible_users_statement(stored, now=now))).all()
    assert {telegram_id for _, telegram_id in rows} == expected_ids


@pytest.mark.asyncio
async def test_queued_delivery_rechecks_opt_out_and_frequency_cap(db_engine, monkeypatch):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    user = await add_user(factory, 301)
    service = BroadcastCampaignService(factory, adapter=FakeBroadcastTelegram())
    monkeypatch.setattr(settings, "broadcast_admin_telegram_ids", "9001")
    monkeypatch.setattr(settings, "admin_telegram_id", None)
    monkeypatch.setattr("core.tasks.dispatch_broadcast_campaign.delay", lambda *_: None)
    campaign = await service.create(campaign_body(), actor="operator")
    await service.estimate(campaign.public_id, actor="operator", reason=None)
    await service.test_send(campaign.public_id, actor="operator", reason=None)
    await service.launch(campaign.public_id, expected_version=1, idempotency_key="queued-optout", actor="operator", reason=None)
    await service.set_preference(user.telegram_id, False)
    await service.dispatch_campaign(campaign.id)
    async with factory() as session:
        delivery = await session.scalar(select(BroadcastDelivery).where(BroadcastDelivery.campaign_id == campaign.id))
        assert delivery.status == BroadcastDeliveryState.SUPPRESSED_OPT_OUT

    await service.set_preference(user.telegram_id, True)
    current = await service.create(campaign_body(), actor="operator")
    await service.estimate(current.public_id, actor="operator", reason=None)
    await service.test_send(current.public_id, actor="operator", reason=None)
    await service.launch(current.public_id, expected_version=1, idempotency_key="queued-frequency", actor="operator", reason=None)
    async with factory() as session:
        now = datetime.now(timezone.utc)
        for index in range(3):
            historical = BroadcastCampaign(
                id=uuid.uuid4(), public_id=f"history{index}", campaign_type="editorial",
                status="completed", content_version=1, text_snapshot="x",
                cta_snapshot=[{"key": "primary", "label": "x", "destination": "profile"}],
                segment_type="all_editorial_enabled", segment_parameters={},
                created_by="operator", updated_by="operator",
            )
            session.add(historical)
            await session.flush()
            session.add(BroadcastDelivery(
                id=uuid.uuid4(), campaign_id=historical.id, user_id=user.id,
                telegram_chat_id_snapshot=user.telegram_id, click_token=f"freq{index}",
                status=BroadcastDeliveryState.DELIVERED, delivered_at=now,
            ))
        await session.commit()
    await service.dispatch_campaign(current.id)
    async with factory() as session:
        delivery = await session.scalar(select(BroadcastDelivery).where(BroadcastDelivery.campaign_id == current.id))
        assert delivery.status == BroadcastDeliveryState.SUPPRESSED_FREQUENCY


@pytest.mark.asyncio
async def test_media_progress_survives_retry_and_blocked_user_is_suppressed(db_engine, monkeypatch):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    await add_user(factory, 401)
    monkeypatch.setattr(settings, "broadcast_admin_telegram_ids", "9001")
    monkeypatch.setattr(settings, "admin_telegram_id", None)
    monkeypatch.setattr("core.tasks.dispatch_broadcast_campaign.delay", lambda *_: None)
    first = FakeBroadcastTelegram()
    service = BroadcastCampaignService(factory, adapter=first)
    campaign = await service.create(campaign_body(media=True), actor="operator")
    await service.estimate(campaign.public_id, actor="operator", reason=None)
    await service.test_send(campaign.public_id, actor="operator", reason=None)
    await service.launch(campaign.public_id, expected_version=1, idempotency_key="media-retry", actor="operator", reason=None)
    # Test-send consumed two fake outcomes; use a delivery-specific failure sequence.
    first.outcomes = [601, BroadcastTelegramError("telegram_network", retryable=True)]
    await service.dispatch_campaign(campaign.id)
    async with factory() as session:
        delivery = await session.scalar(select(BroadcastDelivery).where(BroadcastDelivery.campaign_id == campaign.id))
        assert delivery.media_message_id == 601
        assert delivery.status == BroadcastDeliveryState.FAILED_RETRYABLE
        delivery.retry_not_before = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()
    second = FakeBroadcastTelegram()
    await BroadcastCampaignService(factory, adapter=second).dispatch_campaign(campaign.id)
    assert second.media_calls == []
    assert len(second.text_calls) == 1

    blocked_user = await add_user(factory, 402)
    blocked_adapter = FakeBroadcastTelegram()
    blocked_service = BroadcastCampaignService(factory, adapter=blocked_adapter)
    await blocked_service.set_preference(401, False)
    blocked_campaign = await blocked_service.create(campaign_body(), actor="operator")
    await blocked_service.estimate(blocked_campaign.public_id, actor="operator", reason=None)
    await blocked_service.test_send(blocked_campaign.public_id, actor="operator", reason=None)
    await blocked_service.launch(blocked_campaign.public_id, expected_version=1, idempotency_key="blocked-user", actor="operator", reason=None)
    blocked_adapter.outcomes = [BroadcastTelegramError(
        "telegram_forbidden", retryable=False, blocked_reason="bot_blocked"
    )]
    await blocked_service.dispatch_campaign(blocked_campaign.id)
    async with factory() as session:
        suppression = await session.scalar(select(TelegramSuppression).where(TelegramSuppression.user_id == blocked_user.id))
        assert suppression is not None and suppression.active is True


@pytest.mark.asyncio
async def test_retryable_failure_becomes_terminal_at_attempt_limit(db_engine, monkeypatch):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    await add_user(factory, 403)
    monkeypatch.setattr(settings, "broadcast_admin_telegram_ids", "9001")
    monkeypatch.setattr(settings, "admin_telegram_id", None)
    monkeypatch.setattr(settings, "broadcast_retry_max_attempts", 2)
    monkeypatch.setattr("core.tasks.dispatch_broadcast_campaign.delay", lambda *_: None)
    service = BroadcastCampaignService(factory, adapter=FakeBroadcastTelegram())
    campaign = await service.create(campaign_body(), actor="operator")
    await service.estimate(campaign.public_id, actor="operator", reason=None)
    await service.test_send(campaign.public_id, actor="operator", reason=None)
    await service.launch(
        campaign.public_id,
        expected_version=1,
        idempotency_key="bounded-retry",
        actor="operator",
        reason=None,
    )
    repository = BroadcastRepository(factory)
    async with factory() as session:
        delivery_id = await session.scalar(
            select(BroadcastDelivery.id).where(BroadcastDelivery.campaign_id == campaign.id)
        )
    now = datetime.now(timezone.utc)
    first = await repository.claim_delivery(delivery_id, now=now)
    assert first is not None and first.attempt == 1
    assert await repository.fail_delivery(
        delivery_id,
        first.attempt,
        code="telegram_network",
        retryable=True,
        retry_after=1,
        now=now,
    )
    second = await repository.claim_delivery(delivery_id, now=now + timedelta(seconds=2))
    assert second is not None and second.attempt == 2
    assert await repository.fail_delivery(
        delivery_id,
        second.attempt,
        code="telegram_network",
        retryable=True,
        retry_after=1,
        now=now + timedelta(seconds=2),
    )
    refreshed = await repository.refresh_campaign(
        campaign.id, now=now + timedelta(seconds=3)
    )
    async with factory() as session:
        delivery = await session.get(BroadcastDelivery, delivery_id)
        assert delivery.status == BroadcastDeliveryState.FAILED_TERMINAL
        assert delivery.retry_not_before is None
    assert refreshed.status == "completed"
    assert refreshed.error_code == "completed_with_failures"


@pytest.mark.asyncio
async def test_stale_claim_at_attempt_limit_is_terminal_and_fenced(db_engine, monkeypatch):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    await add_user(factory, 404)
    monkeypatch.setattr(settings, "broadcast_admin_telegram_ids", "9001")
    monkeypatch.setattr(settings, "admin_telegram_id", None)
    monkeypatch.setattr(settings, "broadcast_retry_max_attempts", 2)
    monkeypatch.setattr("core.tasks.dispatch_broadcast_campaign.delay", lambda *_: None)
    service = BroadcastCampaignService(factory, adapter=FakeBroadcastTelegram())
    campaign = await service.create(campaign_body(), actor="operator")
    await service.estimate(campaign.public_id, actor="operator", reason=None)
    await service.test_send(campaign.public_id, actor="operator", reason=None)
    await service.launch(
        campaign.public_id,
        expected_version=1,
        idempotency_key="stale-max-attempt",
        actor="operator",
        reason=None,
    )
    stale_at = datetime.now(timezone.utc) - timedelta(hours=1)
    async with factory() as session:
        delivery = await session.scalar(
            select(BroadcastDelivery).where(BroadcastDelivery.campaign_id == campaign.id)
        )
        delivery.status = BroadcastDeliveryState.SENDING
        delivery.attempt_count = 2
        delivery.claimed_at = stale_at
        await session.commit()
        delivery_id = delivery.id
    repository = BroadcastRepository(factory)
    now = datetime.now(timezone.utc)
    assert await repository.claim_delivery(delivery_id, now=now) is None
    assert not await repository.complete_delivery(delivery_id, 2, 999, now=now)
    refreshed = await repository.refresh_campaign(campaign.id, now=now)
    async with factory() as session:
        delivery = await session.get(BroadcastDelivery, delivery_id)
        assert delivery.status == BroadcastDeliveryState.FAILED_TERMINAL
        assert delivery.claimed_at is None
        assert delivery.retry_not_before is None
        assert delivery.error_code == "retry_attempts_exhausted"
    assert refreshed.status == "completed"
    assert refreshed.error_code == "completed_with_failures"


def test_attribution_query_is_target_bounded_without_global_window_scan():
    campaign_id = uuid.uuid4()
    statement = BroadcastRepository._attributed_paid_orders_statement(campaign_id)
    sql = str(statement.compile(dialect=postgresql.dialect())).lower()
    assert "row_number" not in sql
    assert sql.count("exists") == 1
    assert "join broadcast_cta_click_events" in sql
    assert "campaign_id =" in sql


@pytest.mark.asyncio
async def test_cta_ownership_click_counter_and_last_click_purchase_attribution(db_engine, monkeypatch):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    user = await add_user(factory, 501)
    await add_user(factory, 502)
    monkeypatch.setattr(settings, "broadcast_admin_telegram_ids", "9001")
    monkeypatch.setattr(settings, "admin_telegram_id", None)
    monkeypatch.setattr("core.tasks.dispatch_broadcast_campaign.delay", lambda *_: None)

    campaigns = []
    deliveries = []
    for index in range(2):
        service = BroadcastCampaignService(factory, adapter=FakeBroadcastTelegram())
        campaign = await service.create(campaign_body(), actor="operator")
        await service.estimate(campaign.public_id, actor="operator", reason=None)
        await service.test_send(campaign.public_id, actor="operator", reason=None)
        await service.launch(campaign.public_id, expected_version=1, idempotency_key=f"cta-launch-{index}", actor="operator", reason=None)
        await service.dispatch_campaign(campaign.id)
        campaigns.append(campaign)
        async with factory() as session:
            delivery = await session.scalar(select(BroadcastDelivery).where(
                BroadcastDelivery.campaign_id == campaign.id,
                BroadcastDelivery.user_id == user.id,
            ))
        deliveries.append(delivery)
        assert await service.record_click(delivery.click_token, "primary", user.telegram_id) == "profile"
        await service.record_click(delivery.click_token, "primary", user.telegram_id)
        with pytest.raises(BroadcastServiceError, match="invalid_or_unowned_cta"):
            await service.record_click(delivery.click_token, "primary", 999999)

    async with factory() as session:
        paid_at = datetime.now(timezone.utc)
        events = list(
            (
                await session.execute(
                    select(BroadcastCTAClickEvent).where(
                        BroadcastCTAClickEvent.user_id == user.id
                    )
                )
            ).scalars()
        )
        for event in events:
            offset = 2 if event.campaign_id == campaigns[0].id else 1
            event.clicked_at = paid_at - timedelta(minutes=offset)
            event.attribution_expires_at = event.clicked_at + timedelta(days=7)
        session.add(Order(
            id=uuid.uuid4(), public_id="cta-paid-order", user_id=user.id,
            telegram_id_snapshot=user.telegram_id, status=OrderStatus.PAID,
            idempotency_key="cta-paid-order-key", paid_at=paid_at,
        ))
        await session.commit()
    first_stats = await BroadcastCampaignService(factory).stats(campaigns[0].public_id)
    second_stats = await BroadcastCampaignService(factory).stats(campaigns[1].public_id)
    assert first_stats["post_click_purchases"] == 0
    assert second_stats["post_click_purchases"] == 1
    assert second_stats["ctas"][0]["unique_clickers"] >= 1
    assert second_stats["ctas"][0]["total_clicks"] >= 2
    await BroadcastCampaignService(factory).record_click(
        deliveries[0].click_token,
        "primary",
        user.telegram_id,
    )
    first_after_post_purchase_click = await BroadcastCampaignService(factory).stats(
        campaigns[0].public_id
    )
    second_after_post_purchase_click = await BroadcastCampaignService(factory).stats(
        campaigns[1].public_id
    )
    assert first_after_post_purchase_click["post_click_purchases"] == 0
    assert second_after_post_purchase_click["post_click_purchases"] == 1


@pytest.mark.asyncio
async def test_start_releases_only_automatic_suppression_and_preference_is_idempotent(db_engine):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    user = await add_user(factory, 601)
    async with factory() as session:
        suppression = TelegramSuppression(
            id=uuid.uuid4(), user_id=user.id, reason="bot_blocked", created_by="telegram"
        )
        session.add(suppression)
        await session.commit()
    service = BroadcastCampaignService(factory)
    await service.release_start_suppression(user.id)
    assert await service.set_preference(user.telegram_id, False) is False
    assert await service.set_preference(user.telegram_id, False) is False
    assert await service.set_preference(user.telegram_id, True) is True
    async with factory() as session:
        suppression = await session.scalar(select(TelegramSuppression).where(TelegramSuppression.user_id == user.id))
        assert suppression.active is False and suppression.released_at is not None
        suppression.active = True
        suppression.reason = "operator"
        suppression.released_at = None
        await session.commit()
    await service.release_start_suppression(user.id)
    async with factory() as session:
        suppression = await session.scalar(select(TelegramSuppression).where(TelegramSuppression.user_id == user.id))
        assert suppression.active is True and suppression.reason == "operator"


@pytest.mark.asyncio
async def test_account_deletion_removes_recipient_data_but_retains_campaign(db_engine):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    user = await add_user(factory, 602)
    campaign = await BroadcastCampaignService(factory).create(campaign_body(), actor="operator")
    now = datetime.now(timezone.utc)
    async with factory() as session:
        delivery = BroadcastDelivery(
            id=uuid.uuid4(), campaign_id=campaign.id, user_id=user.id,
            telegram_chat_id_snapshot=user.telegram_id, click_token="deletion-token",
            status=BroadcastDeliveryState.DELIVERED, delivered_at=now,
        )
        session.add(delivery)
        await session.flush()
        click = BroadcastCTAClick(
            id=uuid.uuid4(), campaign_id=campaign.id, delivery_id=delivery.id,
            user_id=user.id, cta_key="primary", destination="profile",
            first_clicked_at=now, last_clicked_at=now,
        )
        session.add(click)
        await session.flush()
        session.add(BroadcastCTAClickEvent(
            id=uuid.uuid4(), click_id=click.id, campaign_id=campaign.id,
            delivery_id=delivery.id, user_id=user.id, cta_key="primary",
            destination="profile", clicked_at=now,
            attribution_expires_at=now + timedelta(days=7),
        ))
        session.add(TelegramSuppression(
            id=uuid.uuid4(), user_id=user.id, reason="bot_blocked", created_by="telegram"
        ))
        await session.commit()
    await AccountDeletionService(factory).delete(user.id)
    async with factory() as session:
        assert await session.get(User, user.id) is None
        assert await session.get(BroadcastCampaign, campaign.id) is not None
        assert await session.scalar(select(func.count(BroadcastDelivery.id))) == 0
        assert await session.scalar(select(func.count(BroadcastCTAClick.id))) == 0
        assert await session.scalar(select(func.count(BroadcastCTAClickEvent.id))) == 0
        assert await session.scalar(select(func.count(TelegramSuppression.id))) == 0
