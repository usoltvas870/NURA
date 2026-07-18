import asyncio
import uuid

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.models import Base, Payment, PromoCode, PromoReservation, User
from core.repositories.promo_reservation import PromoReservationRepository


class FixedSessionContext:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def __aenter__(self) -> AsyncSession:
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        return False


class FixedSessionFactory:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.identities: list[int] = []

    def __call__(self) -> FixedSessionContext:
        self.identities.append(id(self.session))
        return FixedSessionContext(self.session)


@pytest.mark.asyncio
async def test_concurrent_reservations_cannot_exceed_promo_capacity(tmp_path, caplog):
    database_path = tmp_path / "promo_capacity_race.sqlite3"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
        poolclass=NullPool,
    )
    checked_out_connections: set[int] | None = None

    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite_connection(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
        dbapi_connection.execute("PRAGMA busy_timeout=100")

    @event.listens_for(engine.sync_engine, "checkout")
    def record_physical_connection(dbapi_connection, connection_record, connection_proxy):
        if checked_out_connections is not None:
            checked_out_connections.add(id(dbapi_connection))

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("PRAGMA journal_mode=WAL"))
            await connection.run_sync(Base.metadata.create_all)

        cycle_results: list[tuple[int, int, int, int]] = []
        for cycle in range(10):
            promo = PromoCode(
                id=uuid.uuid4(),
                code=f"race-main-{cycle}",
                discount_percent=25,
                max_uses=1,
                used_count=0,
                reserved_count=0,
                is_active=True,
            )
            other_promo = PromoCode(
                id=uuid.uuid4(),
                code=f"race-other-{cycle}",
                discount_percent=25,
                max_uses=1,
                used_count=0,
                reserved_count=0,
                is_active=True,
            )
            first_user = User(id=uuid.uuid4(), name=f"Race A {cycle}", birth_date="01.01.2000")
            second_user = User(id=uuid.uuid4(), name=f"Race B {cycle}", birth_date="02.02.2000")
            async with session_factory() as session:
                session.add_all([promo, other_promo, first_user, second_user])
                await session.commit()
            first_entitlement_before = (
                first_user.subscription_status,
                first_user.subscription_until,
                first_user.tarot_subscription,
                first_user.tarot_subscription_until,
                first_user.has_matrix,
            )
            second_entitlement_before = (
                second_user.subscription_status,
                second_user.subscription_until,
                second_user.tarot_subscription,
                second_user.tarot_subscription_until,
                second_user.has_matrix,
            )

            barrier = asyncio.Barrier(2)
            hook_calls = 0

            async def wait_before_claim() -> None:
                nonlocal hook_calls
                hook_calls += 1
                if hook_calls <= 2:
                    await asyncio.wait_for(barrier.wait(), timeout=1)

            first_session = AsyncSession(bind=engine, expire_on_commit=False)
            second_session = AsyncSession(bind=engine, expire_on_commit=False)
            assert id(first_session) != id(second_session)
            first_factory = FixedSessionFactory(first_session)
            second_factory = FixedSessionFactory(second_session)
            first_repo = PromoReservationRepository(first_factory, wait_before_claim)
            second_repo = PromoReservationRepository(second_factory, wait_before_claim)
            checked_out_connections = set()

            async def reserve(repo, user_id: uuid.UUID, idempotency_key: str):
                try:
                    return "success", await repo.create_or_get(
                        promo_code_id=promo.id,
                        user_id=user_id,
                        payment_type="web_matrix",
                        final_amount_kopecks=66750,
                        currency="RUB",
                        idempotency_key=idempotency_key,
                        expires_at=promo.created_at,
                    )
                except ValueError as error:
                    return "conflict", str(error)
                except Exception as error:
                    await barrier.abort()
                    return "exception", type(error).__name__

            first_key = f"race-first-{cycle}"
            second_key = f"race-second-{cycle}"
            results = await asyncio.gather(
                reserve(first_repo, first_user.id, first_key),
                reserve(second_repo, second_user.id, second_key),
                return_exceptions=True,
            )
            assert all(not isinstance(result, BaseException) for result in results)
            assert checked_out_connections is not None and len(checked_out_connections) >= 2

            successes = [(index, result[1]) for index, result in enumerate(results) if result[0] == "success"]
            conflicts = [result for result in results if result[0] == "conflict"]
            assert len(successes) == 1
            assert conflicts == [("conflict", "promo_capacity_exhausted")]
            winner_index, winner_reservation = successes[0]
            winner_repo = (first_repo, second_repo)[winner_index]
            winner_session = (first_session, second_session)[winner_index]
            loser_index = 1 - winner_index
            loser_repo = (first_repo, second_repo)[loser_index]
            loser_session = (first_session, second_session)[loser_index]
            loser_factory = (first_factory, second_factory)[loser_index]
            loser_key = (first_key, second_key)[loser_index]

            loser_session_identity = id(loser_session)
            assert loser_factory.identities == [loser_session_identity]
            assert loser_session.is_active and not loser_session.in_transaction()
            loser_promo = await loser_session.get(PromoCode, promo.id)
            loser_reservations = (
                await loser_session.execute(
                    select(PromoReservation).where(PromoReservation.promo_code_id == promo.id),
                )
            ).scalars().all()
            assert loser_promo is not None and loser_promo.reserved_count == 1
            assert len(loser_reservations) == 1
            assert id(loser_session) == loser_session_identity
            await loser_session.rollback()

            repeated_winner = await winner_repo.create_or_get(
                promo_code_id=promo.id,
                user_id=winner_reservation.user_id,
                payment_type="web_matrix",
                final_amount_kopecks=66750,
                currency="RUB",
                idempotency_key=winner_reservation.idempotency_key,
                expires_at=promo.created_at,
            )
            assert repeated_winner.id == winner_reservation.id
            await winner_session.rollback()
            with pytest.raises(ValueError, match="promo_capacity_exhausted") as retry_error:
                await loser_repo.create_or_get(
                    promo_code_id=promo.id,
                    user_id=(first_user.id, second_user.id)[loser_index],
                    payment_type="web_matrix",
                    final_amount_kopecks=66750,
                    currency="RUB",
                    idempotency_key=loser_key,
                    expires_at=promo.created_at,
                )
            assert promo.code not in str(retry_error.value)
            assert loser_key not in str(retry_error.value)
            assert promo.code not in caplog.text
            assert loser_factory.identities == [loser_session_identity, loser_session_identity]

            other_reservation = await PromoReservationRepository(session_factory).create_or_get(
                promo_code_id=other_promo.id,
                user_id=first_user.id,
                payment_type="web_matrix",
                final_amount_kopecks=66750,
                currency="RUB",
                idempotency_key=f"race-other-{cycle}",
                expires_at=other_promo.created_at,
            )
            assert other_reservation.promo_code_id == other_promo.id
            async with session_factory() as verification_session:
                verified_promo = await verification_session.get(PromoCode, promo.id)
                verified_other_promo = await verification_session.get(PromoCode, other_promo.id)
                verified_first_user = await verification_session.get(User, first_user.id)
                verified_second_user = await verification_session.get(User, second_user.id)
                reservations = (
                    await verification_session.execute(
                        select(PromoReservation).where(PromoReservation.promo_code_id == promo.id),
                    )
                ).scalars().all()
                payments = (await verification_session.execute(select(Payment))).scalars().all()
            assert verified_promo is not None and verified_promo.reserved_count == 1
            assert verified_promo.used_count == 0
            assert verified_other_promo is not None and verified_other_promo.reserved_count == 1
            assert len(reservations) == 1 and reservations[0].state == "reserved"
            assert payments == []
            assert verified_first_user is not None and (
                verified_first_user.subscription_status,
                verified_first_user.subscription_until,
                verified_first_user.tarot_subscription,
                verified_first_user.tarot_subscription_until,
                verified_first_user.has_matrix,
            ) == first_entitlement_before
            assert verified_second_user is not None and (
                verified_second_user.subscription_status,
                verified_second_user.subscription_until,
                verified_second_user.tarot_subscription,
                verified_second_user.tarot_subscription_until,
                verified_second_user.has_matrix,
            ) == second_entitlement_before
            cycle_results.append((len(successes), len(conflicts), len(reservations), verified_promo.reserved_count))

            await first_session.close()
            await second_session.close()
            checked_out_connections = None

        assert cycle_results == [(1, 1, 1, 1)] * 10
    finally:
        await engine.dispose()
