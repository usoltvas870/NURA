"""Focused acceptance checks for durable Telegram and web-chat delivery."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.models import ChatMessageUsage, User
from core.services.chat_quota import ChatChannel, ChatQuotaService, QuotaReservationKind
from core.services.chat_telegram_delivery import TelegramChatDeliveryService


async def _user(factory, telegram_id: int) -> User:
    user = User(id=uuid.uuid4(), telegram_id=telegram_id)
    async with factory() as session:
        session.add(user)
        await session.commit()
    return user


@pytest.mark.asyncio
async def test_telegram_middle_failure_resumes_without_resending_completed_chunks(db_engine) -> None:
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    user = await _user(factory, 701)
    quota = ChatQuotaService(factory)
    reservation = await quota.reserve(user.id, "tg-retry", ChatChannel.TELEGRAM, subscriber=False)
    assert reservation.kind == QuotaReservationKind.RESERVED_NEW
    answer = "x" * 5000
    await quota.store_result(reservation.usage_id, answer)
    service = TelegramChatDeliveryService(quota)
    chunks = service.chunks(answer)
    assert len(chunks) >= 1
    await quota.configure_telegram_delivery(reservation.usage_id, chat_id=701, total_chunks=len(chunks))

    sent: list[str] = []
    calls = 0

    async def fail_once(chunk: str) -> None:
        nonlocal calls
        calls += 1
        if calls == min(2, len(chunks)):
            raise ConnectionError("temporary")
        sent.append(chunk)

    first = await service.deliver(reservation.usage_id, send_chunk=fail_once)
    assert first.retryable
    async with factory() as session:
        row = await session.get(ChatMessageUsage, reservation.usage_id)
        assert row is not None
        assert row.status == "result_ready"
        assert row.delivery_next_chunk_index == len(sent)
        assert row.delivery_status == "retryable"

    resumed: list[str] = []

    async def succeed(chunk: str) -> None:
        resumed.append(chunk)

    second = await service.deliver(reservation.usage_id, send_chunk=succeed)
    assert second.status == "delivered"
    assert sent + resumed == chunks
    async with factory() as session:
        row = await session.get(ChatMessageUsage, reservation.usage_id)
        assert row is not None
        assert row.status == "consumed"
        assert row.delivery_status == "delivered"
        assert row.delivery_next_chunk_index == len(chunks)


@pytest.mark.asyncio
async def test_telegram_terminal_failure_releases_reservation_without_consuming(db_engine) -> None:
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    user = await _user(factory, 702)
    quota = ChatQuotaService(factory)
    reservation = await quota.reserve(user.id, "tg-terminal", ChatChannel.TELEGRAM, subscriber=False)
    await quota.store_result(reservation.usage_id, "answer")
    service = TelegramChatDeliveryService(quota)
    await quota.configure_telegram_delivery(reservation.usage_id, chat_id=702, total_chunks=1)

    class TerminalAdapter:
        @staticmethod
        def _classify(_: Exception):
            from core.services.telegram_report_delivery import TelegramDeliveryError
            return TelegramDeliveryError("telegram_forbidden", retryable=False)

    result = await TelegramChatDeliveryService(quota, adapter=TerminalAdapter()).deliver(
        reservation.usage_id, send_chunk=lambda _: (_ for _ in ()).throw(RuntimeError("blocked"))
    )
    assert result.status == "failed"
    async with factory() as session:
        row = await session.get(ChatMessageUsage, reservation.usage_id)
        assert row is not None
        assert row.status == "released"
        assert row.response_text is None
        assert row.delivery_status == "failed"
    assert (await quota.state(user.id, subscriber=False)).messages_left == 5


@pytest.mark.asyncio
async def test_web_ack_is_owned_idempotent_and_commits_once(db_engine) -> None:
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    owner = await _user(factory, 703)
    other = await _user(factory, 704)
    quota = ChatQuotaService(factory)
    reservation = await quota.reserve(owner.id, "web-ack", ChatChannel.WEB, subscriber=False)
    await quota.store_result(reservation.usage_id, "answer")
    assert (await quota.state(owner.id, subscriber=False)).messages_left == 4
    assert await quota.acknowledge_web_delivery(other.id, reservation.usage_id) is None
    first = await quota.acknowledge_web_delivery(owner.id, reservation.usage_id)
    assert first is not None and first.status == "delivered" and first.state.used == 1
    second = await quota.acknowledge_web_delivery(owner.id, reservation.usage_id)
    assert second is not None and second.state.used == 1


@pytest.mark.asyncio
async def test_six_parallel_reservations_leave_only_five_delivery_slots(db_engine) -> None:
    if db_engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-lock semantics are required for this race proof")
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    user = await _user(factory, 705)

    async def reserve(index: int):
        return await ChatQuotaService(factory).reserve(
            user.id, f"race-{index}", ChatChannel.WEB, subscriber=False
        )

    reservations = await asyncio.gather(*[reserve(index) for index in range(6)])
    assert sum(item.kind == QuotaReservationKind.RESERVED_NEW for item in reservations) == 5
    assert sum(item.kind == QuotaReservationKind.EXHAUSTED for item in reservations) == 1
