from datetime import datetime, timedelta, timezone
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.models import Payment, PromoCode, PromoReservation, User
from core.repositories.promo_reservation import PromoReservationRepository


class CommitFailsOnceSession(AsyncSession):
    fail_next_commit = True

    async def commit(self) -> None:
        if type(self).fail_next_commit:
            type(self).fail_next_commit = False
            raise RuntimeError("controlled_reservation_commit_failure")
        await super().commit()


class SameSessionContext:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def __aenter__(self) -> AsyncSession:
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        return False


class SameSessionFactory:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.identities: list[int] = []

    def __call__(self) -> SameSessionContext:
        self.identities.append(id(self.session))
        return SameSessionContext(self.session)


@pytest_asyncio.fixture
async def session_factory(db_engine):
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


async def _promo(session_factory, maximum: int = 1) -> PromoCode:
    promo = PromoCode(id=uuid.uuid4(), code=uuid.uuid4().hex, discount_percent=25, max_uses=maximum, used_count=0, reserved_count=0, is_active=True)
    async with session_factory() as session:
        session.add(promo)
        await session.commit()
    return promo


@pytest.mark.asyncio
async def test_reservation_and_slot_are_committed_together(session_factory, test_user):
    promo = await _promo(session_factory)
    repo = PromoReservationRepository(session_factory)
    reservation = await repo.create_or_get(promo_code_id=promo.id, user_id=test_user.id, payment_type="web_matrix", final_amount_kopecks=66750, currency="RUB", idempotency_key="key-1", expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    same = await repo.create_or_get(promo_code_id=promo.id, user_id=test_user.id, payment_type="web_matrix", final_amount_kopecks=66750, currency="RUB", idempotency_key="key-1", expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    assert same.id == reservation.id and reservation.state == "reserved"
    async with session_factory() as session:
        stored = await session.get(PromoCode, promo.id)
    assert stored is not None and stored.reserved_count == 1


@pytest.mark.asyncio
async def test_capacity_and_terminal_transitions_are_safe(session_factory, test_user):
    promo = await _promo(session_factory)
    repo = PromoReservationRepository(session_factory)
    reservation = await repo.create_or_get(promo_code_id=promo.id, user_id=test_user.id, payment_type="web_matrix", final_amount_kopecks=66750, currency="RUB", idempotency_key="key-1", expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    with pytest.raises(ValueError, match="promo_capacity_exhausted"):
        await repo.create_or_get(promo_code_id=promo.id, user_id=test_user.id, payment_type="web_matrix", final_amount_kopecks=66750, currency="RUB", idempotency_key="key-2", expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    assert (await repo.mark_consumed(reservation.id)).state == "consumed"
    assert (await repo.mark_consumed(reservation.id)).state == "consumed"
    with pytest.raises(ValueError, match="invalid_reservation_transition"):
        await repo.mark_released(reservation.id)


@pytest.mark.asyncio
async def test_conflicting_key_and_attachments_are_rejected(session_factory, test_user):
    promo = await _promo(session_factory, maximum=2)
    repo = PromoReservationRepository(session_factory)
    reservation = await repo.create_or_get(promo_code_id=promo.id, user_id=test_user.id, payment_type="web_matrix", final_amount_kopecks=66750, currency="RUB", idempotency_key="key-1", expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    with pytest.raises(ValueError, match="idempotency_key_conflict"):
        await repo.create_or_get(promo_code_id=promo.id, user_id=test_user.id, payment_type="web_tarot", final_amount_kopecks=29250, currency="RUB", idempotency_key="key-1", expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    assert (await repo.attach_provider_payment(reservation.id, "provider-1")).provider_payment_id == "provider-1"
    assert (await repo.attach_provider_payment(reservation.id, "provider-1")).provider_payment_id == "provider-1"
    with pytest.raises(ValueError, match="reservation_attachment_conflict"):
        await repo.attach_provider_payment(reservation.id, "provider-2")
    payment = Payment(id=uuid.uuid4(), user_id=test_user.id, amount=667, payment_type="web_matrix")
    async with session_factory() as session:
        session.add(payment)
        await session.commit()
    assert (await repo.attach_local_payment(reservation.id, payment.id)).payment_id == payment.id


@pytest.mark.asyncio
async def test_released_and_stale_contracts(session_factory, test_user):
    promo = await _promo(session_factory, maximum=3)
    repo = PromoReservationRepository(session_factory)
    old = await repo.create_or_get(promo_code_id=promo.id, user_id=test_user.id, payment_type="web_matrix", final_amount_kopecks=66750, currency="RUB", idempotency_key="old", expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    fresh = await repo.create_or_get(promo_code_id=promo.id, user_id=test_user.id, payment_type="web_matrix", final_amount_kopecks=66750, currency="RUB", idempotency_key="fresh", expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    assert [item.id for item in await repo.list_stale_nonterminal(datetime.now(timezone.utc))] == [old.id]
    assert (await repo.mark_released(old.id)).state == "released"
    assert (await repo.mark_released(old.id)).state == "released"
    with pytest.raises(ValueError, match="invalid_reservation_transition"):
        await repo.mark_consumed(old.id)
    assert fresh.state == "reserved"


@pytest.mark.asyncio
async def test_create_reservation_rolls_back_slot_and_row_and_reuses_session(
    db_engine, session_factory, test_user,
):
    promo = await _promo(session_factory)
    CommitFailsOnceSession.fail_next_commit = True
    session = CommitFailsOnceSession(bind=db_engine, expire_on_commit=False)
    session_identity = id(session)
    same_session_factory = SameSessionFactory(session)
    repo = PromoReservationRepository(same_session_factory)
    kwargs = dict(promo_code_id=promo.id, user_id=test_user.id, payment_type="web_matrix", final_amount_kopecks=66750, currency="RUB", idempotency_key="rollback-key", expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    with pytest.raises(RuntimeError, match="controlled_reservation_commit_failure"):
        await repo.create_or_get(**kwargs)
    assert id(session) == session_identity
    assert session.is_active and not session.in_transaction()
    assert await session.get(PromoCode, promo.id) is not None
    assert (await session.execute(select(PromoReservation))).scalars().all() == []
    assert id(session) == session_identity
    async with session_factory() as verification_session:
        stored_promo = await verification_session.get(PromoCode, promo.id)
        rows = (await verification_session.execute(select(PromoReservation))).scalars().all()
    assert stored_promo is not None and stored_promo.reserved_count == 0 and rows == []
    reservation = await repo.create_or_get(**kwargs)
    assert reservation.idempotency_key == "rollback-key"
    assert same_session_factory.identities == [session_identity, session_identity]
    assert id(session) == session_identity
    await session.close()
    async with session_factory() as session:
        assert await session.get(PromoCode, promo.id) is not None


@pytest.mark.asyncio
async def test_provider_payment_unique_conflict_rolls_back_and_reuses_same_session(
    db_engine, session_factory, test_user, caplog,
):
    promo = await _promo(session_factory, maximum=2)
    repo = PromoReservationRepository(session_factory)
    first = await repo.create_or_get(
        promo_code_id=promo.id,
        user_id=test_user.id,
        payment_type="web_matrix",
        final_amount_kopecks=66750,
        currency="RUB",
        idempotency_key="provider-conflict-first",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    second = await repo.create_or_get(
        promo_code_id=promo.id,
        user_id=test_user.id,
        payment_type="web_matrix",
        final_amount_kopecks=66750,
        currency="RUB",
        idempotency_key="provider-conflict-second",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    shared_provider_id = "provider-shared"
    free_provider_id = "provider-free"
    await repo.attach_provider_payment(first.id, shared_provider_id)
    entitlement_before = (
        test_user.subscription_status,
        test_user.subscription_until,
        test_user.tarot_subscription,
        test_user.tarot_subscription_until,
        test_user.has_matrix,
    )
    loser_session = AsyncSession(bind=db_engine, expire_on_commit=False)
    loser_session_id = id(loser_session)
    loser_factory = SameSessionFactory(loser_session)
    loser_repo = PromoReservationRepository(loser_factory)
    database_unique_conflict_observed = False

    def record_database_error(exception_context):
        nonlocal database_unique_conflict_observed
        if "provider_payment_id" in str(exception_context.original_exception):
            database_unique_conflict_observed = True

    event.listen(db_engine.sync_engine, "handle_error", record_database_error)
    try:
        with pytest.raises(ValueError, match="reservation_attachment_conflict") as error:
            await loser_repo.attach_provider_payment(second.id, shared_provider_id)
    finally:
        event.remove(db_engine.sync_engine, "handle_error", record_database_error)

    assert database_unique_conflict_observed
    assert shared_provider_id not in str(error.value)
    assert shared_provider_id not in caplog.text
    assert id(loser_session) == loser_session_id
    assert loser_session.is_active and not loser_session.in_transaction()
    attached_first = await loser_session.get(PromoReservation, first.id)
    unattached_second = await loser_session.get(PromoReservation, second.id)
    assert attached_first is not None and attached_first.provider_payment_id == shared_provider_id
    assert unattached_second is not None and unattached_second.provider_payment_id is None
    assert attached_first.state == unattached_second.state == "reserved"

    attached_second = await loser_repo.attach_provider_payment(second.id, free_provider_id)
    assert attached_second.provider_payment_id == free_provider_id
    assert loser_factory.identities == [loser_session_id, loser_session_id]
    assert loser_session.is_active
    await loser_session.close()

    async with session_factory() as verification_session:
        verified_first = await verification_session.get(PromoReservation, first.id)
        verified_second = await verification_session.get(PromoReservation, second.id)
        verified_promo = await verification_session.get(PromoCode, promo.id)
        verified_user = await verification_session.get(User, test_user.id)
        payments = (await verification_session.execute(select(Payment))).scalars().all()
        shared_provider_rows = (
            await verification_session.execute(
                select(PromoReservation).where(
                    PromoReservation.provider_payment_id == shared_provider_id,
                ),
            )
        ).scalars().all()
    assert verified_first is not None and verified_first.provider_payment_id == shared_provider_id
    assert verified_second is not None and verified_second.provider_payment_id == free_provider_id
    assert verified_first.state == verified_second.state == "reserved"
    assert verified_promo is not None and verified_promo.reserved_count == 2 and verified_promo.used_count == 0
    assert verified_user is not None and (
        verified_user.subscription_status,
        verified_user.subscription_until,
        verified_user.tarot_subscription,
        verified_user.tarot_subscription_until,
        verified_user.has_matrix,
    ) == entitlement_before
    assert payments == []
    assert [reservation.id for reservation in shared_provider_rows] == [first.id]


@pytest.mark.asyncio
async def test_local_payment_unique_conflict_rolls_back_and_reuses_same_session(
    db_engine, session_factory, test_user, caplog,
):
    promo = await _promo(session_factory, maximum=2)
    repo = PromoReservationRepository(session_factory)
    first = await repo.create_or_get(
        promo_code_id=promo.id,
        user_id=test_user.id,
        payment_type="web_matrix",
        final_amount_kopecks=66750,
        currency="RUB",
        idempotency_key="local-conflict-first",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    second = await repo.create_or_get(
        promo_code_id=promo.id,
        user_id=test_user.id,
        payment_type="web_matrix",
        final_amount_kopecks=66750,
        currency="RUB",
        idempotency_key="local-conflict-second",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    foreign_user = User(id=uuid.uuid4(), name="Foreign", birth_date="02.02.2000")
    shared_payment = Payment(
        id=uuid.uuid4(),
        user_id=test_user.id,
        amount=667,
        amount_kopecks=66750,
        status="pending",
        yookassa_id="local-provider-shared",
        payment_type="web_matrix",
    )
    free_payment = Payment(
        id=uuid.uuid4(),
        user_id=test_user.id,
        amount=667,
        amount_kopecks=66750,
        status="pending",
        yookassa_id="local-provider-free",
        payment_type="web_matrix",
    )
    foreign_payment = Payment(
        id=uuid.uuid4(),
        user_id=foreign_user.id,
        amount=667,
        amount_kopecks=66750,
        status="pending",
        yookassa_id="local-provider-foreign",
        payment_type="web_matrix",
    )
    wrong_type_payment = Payment(
        id=uuid.uuid4(),
        user_id=test_user.id,
        amount=292,
        amount_kopecks=29250,
        status="pending",
        yookassa_id="local-provider-wrong-type",
        payment_type="web_tarot",
    )
    async with session_factory() as session:
        session.add_all(
            [foreign_user, shared_payment, free_payment, foreign_payment, wrong_type_payment],
        )
        await session.commit()
    shared_payment_snapshot = (
        shared_payment.user_id,
        shared_payment.amount,
        shared_payment.amount_kopecks,
        shared_payment.status,
        shared_payment.yookassa_id,
        shared_payment.payment_type,
    )
    entitlement_before = (
        test_user.subscription_status,
        test_user.subscription_until,
        test_user.tarot_subscription,
        test_user.tarot_subscription_until,
        test_user.has_matrix,
    )
    foreign_entitlement_before = (
        foreign_user.subscription_status,
        foreign_user.subscription_until,
        foreign_user.tarot_subscription,
        foreign_user.tarot_subscription_until,
        foreign_user.has_matrix,
    )
    with pytest.raises(ValueError, match="invalid_reservation_transition"):
        await repo.attach_local_payment(second.id, foreign_payment.id)
    with pytest.raises(ValueError, match="invalid_reservation_transition"):
        await repo.attach_local_payment(second.id, wrong_type_payment.id)
    assert (await repo.attach_local_payment(first.id, shared_payment.id)).payment_id == shared_payment.id

    loser_session = AsyncSession(bind=db_engine, expire_on_commit=False)
    loser_session_id = id(loser_session)
    loser_factory = SameSessionFactory(loser_session)
    loser_repo = PromoReservationRepository(loser_factory)
    database_unique_conflict_observed = False

    def record_database_error(exception_context):
        nonlocal database_unique_conflict_observed
        if "promo_reservations.payment_id" in str(exception_context.original_exception):
            database_unique_conflict_observed = True

    event.listen(db_engine.sync_engine, "handle_error", record_database_error)
    try:
        with pytest.raises(ValueError, match="reservation_attachment_conflict") as error:
            await loser_repo.attach_local_payment(second.id, shared_payment.id)
    finally:
        event.remove(db_engine.sync_engine, "handle_error", record_database_error)

    assert database_unique_conflict_observed
    for sensitive_value in (
        str(shared_payment.id),
        shared_payment.yookassa_id,
        str(test_user.id),
        promo.code,
    ):
        assert sensitive_value not in str(error.value)
        assert sensitive_value not in caplog.text
    assert id(loser_session) == loser_session_id
    assert loser_session.is_active and not loser_session.in_transaction()
    attached_first = await loser_session.get(PromoReservation, first.id)
    unattached_second = await loser_session.get(PromoReservation, second.id)
    stored_payment = await loser_session.get(Payment, shared_payment.id)
    stored_promo = await loser_session.get(PromoCode, promo.id)
    assert attached_first is not None and attached_first.payment_id == shared_payment.id
    assert unattached_second is not None and unattached_second.payment_id is None
    assert attached_first.state == unattached_second.state == "reserved"
    assert stored_payment is not None and (
        stored_payment.user_id,
        stored_payment.amount,
        stored_payment.amount_kopecks,
        stored_payment.status,
        stored_payment.yookassa_id,
        stored_payment.payment_type,
    ) == shared_payment_snapshot
    assert stored_promo is not None and stored_promo.reserved_count == 2 and stored_promo.used_count == 0
    await loser_session.rollback()

    async with session_factory() as verification_session:
        verified_first = await verification_session.get(PromoReservation, first.id)
        verified_second = await verification_session.get(PromoReservation, second.id)
        verified_payment = await verification_session.get(Payment, shared_payment.id)
        verified_promo = await verification_session.get(PromoCode, promo.id)
        verified_user = await verification_session.get(User, test_user.id)
        verified_foreign_user = await verification_session.get(User, foreign_user.id)
        shared_payment_rows = (
            await verification_session.execute(
                select(PromoReservation).where(PromoReservation.payment_id == shared_payment.id),
            )
        ).scalars().all()
    assert verified_first is not None and verified_first.payment_id == shared_payment.id
    assert verified_second is not None and verified_second.payment_id is None
    assert verified_first.state == verified_second.state == "reserved"
    assert verified_payment is not None and (
        verified_payment.user_id,
        verified_payment.amount,
        verified_payment.amount_kopecks,
        verified_payment.status,
        verified_payment.yookassa_id,
        verified_payment.payment_type,
    ) == shared_payment_snapshot
    assert [reservation.id for reservation in shared_payment_rows] == [first.id]
    assert verified_promo is not None and verified_promo.reserved_count == 2 and verified_promo.used_count == 0
    assert verified_user is not None and (
        verified_user.subscription_status,
        verified_user.subscription_until,
        verified_user.tarot_subscription,
        verified_user.tarot_subscription_until,
        verified_user.has_matrix,
    ) == entitlement_before
    assert verified_foreign_user is not None and (
        verified_foreign_user.subscription_status,
        verified_foreign_user.subscription_until,
        verified_foreign_user.tarot_subscription,
        verified_foreign_user.tarot_subscription_until,
        verified_foreign_user.has_matrix,
    ) == foreign_entitlement_before

    attached_second = await loser_repo.attach_local_payment(second.id, free_payment.id)
    assert attached_second.payment_id == free_payment.id
    assert loser_factory.identities == [loser_session_id, loser_session_id]
    assert loser_session.is_active
    await loser_session.close()

    async with session_factory() as verification_session:
        final_first = await verification_session.get(PromoReservation, first.id)
        final_second = await verification_session.get(PromoReservation, second.id)
    assert final_first is not None and final_first.payment_id == shared_payment.id
    assert final_second is not None and final_second.payment_id == free_payment.id
