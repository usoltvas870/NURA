import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import load_only

from core.config import settings
from core.models import Report, ReportType, User
from core.repositories.base import SQLAlchemyRepository


class UserRepository(SQLAlchemyRepository[User]):
    def __init__(self, session_factory: async_sessionmaker):
        super().__init__(session_factory, User)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            return result.scalar_one_or_none()

    async def create(
        self,
        telegram_id: int,
        username: str | None = None,
        first_name: str | None = None,
    ) -> User:
        user = User(
            id=uuid.uuid4(),
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
        )
        return await self.add(user)

    async def get_or_create_by_telegram_id(
        self,
        telegram_id: int,
        username: str | None = None,
        first_name: str | None = None,
    ) -> User:
        async with self._session_factory() as session:
            stmt = pg_insert(User).values(
                id=uuid.uuid4(),
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
            ).on_conflict_do_nothing()
            await session.execute(stmt)
            await session.commit()
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            return result.scalar_one()

    async def update_archetype(
        self,
        user_id: uuid.UUID,
        archetype: str,
        number: int,
    ) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            user.main_archetype = archetype
            user.main_archetype_number = number
            await session.commit()
            await session.refresh(user)
            return user

    async def update_birth_date(
        self,
        user_id: uuid.UUID,
        birth_date: str,
    ) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            user.birth_date = birth_date
            await session.commit()
            await session.refresh(user)
            return user

    async def update_subscription(
        self,
        user_id: uuid.UUID,
        status: str,
        until: datetime | None = None,
    ) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            user.subscription_status = status
            user.subscription_until = until
            await session.commit()
            await session.refresh(user)
            return user

    async def update_tarot_subscription(
        self,
        user_id: uuid.UUID,
        active: bool,
        until: datetime | None = None,
    ) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            user.tarot_subscription = active
            user.tarot_subscription_until = until
            await session.commit()
            await session.refresh(user)
            return user

    async def update_has_matrix(
        self,
        user_id: uuid.UUID,
        has_matrix: bool,
    ) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            user.has_matrix = has_matrix
            await session.commit()
            await session.refresh(user)
            return user

    async def get_users_with_tarot(self) -> list[User]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(User)
                .options(
                    load_only(
                        User.id,
                        User.telegram_id,
                        User.has_pwa_push,
                        User.push_endpoint,
                        User.push_p256dh,
                        User.push_auth,
                        User.main_archetype,
                        User.main_archetype_number,
                        User.first_name,
                        User.username,
                    )
                )
                .where(
                    User.tarot_subscription == True,  # noqa: E712
                    User.subscription_status.in_(["free", "premium", "active"]),
                )
            )
            return list(result.scalars().all())

    async def mark_compatibility_used(self, user_id: uuid.UUID) -> None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is not None:
                user.compatibility_used = True
                await session.commit()

    async def get_has_matrix(self, user_id: uuid.UUID) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Report).where(
                    Report.user_id == user_id,
                    Report.report_type == ReportType.FULL.value,
                    Report.matrix_data.isnot(None),
                ).limit(1)
            )
            report = result.scalar_one_or_none()
            return report is not None

    async def get_by_web_session_id(self, web_session_id: str) -> User | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(User).where(User.web_session_id == web_session_id)
            )
            return result.scalar_one_or_none()

    async def get_by_name_and_birth_date(
        self, name: str, birth_date: str
    ) -> User | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(User).where(
                    User.name == name.strip(),
                    User.birth_date == birth_date.strip(),
                )
            )
            return result.scalar_one_or_none()

    async def create_web_user(
        self,
        name: str,
        birth_date: str,
        web_session_id: str,
        email: str | None = None,
        vk_id: str | None = None,
    ) -> User:
        now = datetime.now(timezone.utc)
        user = User(
            id=uuid.uuid4(),
            name=name,
            birth_date=birth_date,
            web_session_id=web_session_id,
            email=email,
            vk_id=vk_id,
            web_session_expires_at=now + timedelta(seconds=settings.web_session_ttl_seconds),
        )
        return await self.add(user)

    async def update_web_session(
        self,
        user_id: uuid.UUID,
        web_session_id: str,
    ) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            user.web_session_id = web_session_id
            user.web_session_expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=settings.web_session_ttl_seconds)
            )
            await session.commit()
            await session.refresh(user)
            return user

    async def update_web_user(
        self,
        user_id: uuid.UUID,
        name: str | None = None,
        birth_date: str | None = None,
        email: str | None = None,
    ) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            if name is not None:
                user.name = name
            if birth_date is not None:
                user.birth_date = birth_date
            if email is not None:
                user.email = email
            await session.commit()
            await session.refresh(user)
            return user

    async def set_referred_by(
        self,
        user_id: uuid.UUID,
        referrer_telegram_id: int,
    ) -> bool:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None or user.referred_by is not None:
                return False
            user.referred_by = referrer_telegram_id
            await session.commit()
            return True

    async def get_by_email(self, email: str) -> User | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(User).where(User.email == email)
            )
            return result.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> User | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(User).where(User.phone == phone)
            )
            return result.scalar_one_or_none()

    async def get_by_vk_id(self, vk_id: str) -> User | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(User).where(User.vk_id == vk_id)
            )
            return result.scalar_one_or_none()

    async def set_email_verified(
        self, user_id: uuid.UUID, value: bool = True
    ) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            user.email_verified = value
            await session.commit()
            await session.refresh(user)
            return user

    async def set_phone_verified(
        self, user_id: uuid.UUID, value: bool = True
    ) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            user.phone_verified = value
            await session.commit()
            await session.refresh(user)
            return user

    async def set_auth_method(
        self, user_id: uuid.UUID, auth_method: str
    ) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            user.auth_method = auth_method
            await session.commit()
            await session.refresh(user)
            return user

    async def set_phone(self, user_id: uuid.UUID, phone: str) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            user.phone = phone
            await session.commit()
            await session.refresh(user)
            return user

    async def set_vk_id(self, user_id: uuid.UUID, vk_id: str) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            user.vk_id = vk_id
            await session.commit()
            await session.refresh(user)
            return user

    async def set_email(self, user_id: uuid.UUID, email: str) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            user.email = email
            await session.commit()
            await session.refresh(user)
            return user

    async def update_telegram_id(
        self,
        user_id: uuid.UUID,
        telegram_id: int,
    ) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            if user.telegram_id and user.telegram_id != telegram_id:
                return None
            user.telegram_id = telegram_id
            await session.commit()
            await session.refresh(user)
            return user

    async def update_push_subscription(
        self,
        user_id: uuid.UUID,
        endpoint: str | None,
        p256dh: str | None,
        auth: str | None,
        has_pwa_push: bool,
    ) -> None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return
            user.has_pwa_push = has_pwa_push
            user.push_endpoint = endpoint
            user.push_p256dh = p256dh
            user.push_auth = auth
            await session.commit()

    async def clear_push_subscription_by_endpoint(self, endpoint: str) -> None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(User).where(User.push_endpoint == endpoint)
            )
            user = result.scalar_one_or_none()
            if user:
                user.has_pwa_push = False
                user.push_endpoint = None
                user.push_p256dh = None
                user.push_auth = None
                await session.commit()

    async def update_notification_pref(
        self,
        user_id: uuid.UUID,
        key: str,
        enabled: bool,
    ) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            prefs = dict(user.notification_prefs or {})
            prefs[key] = bool(enabled)
            user.notification_prefs = prefs
            await session.commit()
            await session.refresh(user)
            return user

    async def get_notification_prefs(self, user_id: uuid.UUID) -> dict:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return {}
            return dict(user.notification_prefs or {})

    async def renew_session_expiry(self, user_id: uuid.UUID) -> None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return
            user.web_session_expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=settings.web_session_ttl_seconds)
            )
            await session.commit()

    async def set_pd_consent(self, user_id: uuid.UUID) -> None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None or user.pd_consent_at is not None:
                return
            user.pd_consent_at = datetime.now(timezone.utc)
            await session.commit()

    async def ensure_web_session(
        self,
        telegram_id: int,
        web_session_id: str,
    ) -> User | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            if user is None:
                return None
            user.web_session_id = web_session_id
            user.web_session_expires_at = (
                datetime.now(timezone.utc)
                + timedelta(seconds=settings.web_session_ttl_seconds)
            )
            await session.commit()
            await session.refresh(user)
            return user

    async def extend_subscription(self, user_id: uuid.UUID, days: int) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            now = datetime.now(timezone.utc)
            if user.subscription_until:
                user.subscription_until = user.subscription_until + timedelta(days=days)
            else:
                user.subscription_until = now + timedelta(days=days)
            if user.subscription_status == "free":
                user.subscription_status = "premium"
            await session.commit()
            await session.refresh(user)
            return user

    async def extend_tarot(self, user_id: uuid.UUID, days: int) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            now = datetime.now(timezone.utc)
            user.tarot_subscription = True
            if user.tarot_subscription_until:
                user.tarot_subscription_until = user.tarot_subscription_until + timedelta(days=days)
            else:
                user.tarot_subscription_until = now + timedelta(days=days)
            await session.commit()
            await session.refresh(user)
            return user

    async def grant_premium(self, user_id: uuid.UUID, days: int) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            user.subscription_status = "premium"
            user.subscription_until = datetime.now(timezone.utc) + timedelta(days=days)
            await session.commit()
            await session.refresh(user)
            return user

    async def grant_tarot(self, user_id: uuid.UUID, days: int) -> User | None:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            user.tarot_subscription = True
            user.tarot_subscription_until = datetime.now(timezone.utc) + timedelta(days=days)
            await session.commit()
            await session.refresh(user)
            return user

    async def has_other_auth_method(self, user_id: uuid.UUID) -> bool:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return False
            has_email = bool(user.email and user.email_verified)
            has_vk = bool(user.vk_id)
            return has_email or has_vk

    async def unlink_telegram(self, user_id: uuid.UUID) -> bool:
        async with self._session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return False
            user.telegram_id = None
            user.username = None
            user.first_name = None
            await session.commit()
            return True

    async def get_users_for_recurring_charge(self) -> list[User]:
        now = datetime.now(timezone.utc)
        threshold = now + timedelta(hours=24)
        async with self._session_factory() as session:
            result = await session.execute(
                select(User)
                .options(
                    load_only(
                        User.id,
                        User.telegram_id,
                        User.first_name,
                        User.username,
                        User.payment_method_id,
                        User.subscription_status,
                        User.subscription_until,
                        User.tarot_subscription,
                        User.tarot_subscription_until,
                    )
                )
                .where(
                    User.payment_method_id.isnot(None),
                    (
                        (
                            (User.tarot_subscription == True)  # noqa: E712
                            & (User.tarot_subscription_until <= threshold)
                        )
                        | (
                            (User.subscription_status == "premium")
                            & (User.subscription_until <= threshold)
                        )
                    ),
                )
            )
            return list(result.scalars().all())
