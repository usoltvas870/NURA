import base64
import hashlib
import hmac
import httpx
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from redis.exceptions import WatchError

from core.config import settings
from core.database import get_async_sessionmaker, get_redis
from core.models import ReportType, User
from core.repositories.guest import GuestProfileRepository
from core.repositories.report import ReportRepository
from core.repositories.user import UserRepository

logger = logging.getLogger(__name__)

GUEST_CACHE_PREFIX = "guest_profile"
MAGIC_LINK_PREFIX = "magic_link"
LINK_TOKEN_PREFIX = "link_token"
LINK_TOKEN_TTL_SECONDS = 900
TELEGRAM_LINK_PENDING_PREFIX = "telegram_link_pending"
TELEGRAM_LINK_PENDING_TTL_SECONDS = 600
TELEGRAM_LINK_CONFIRMATION_MAX_ATTEMPTS = 5
TELEGRAM_LINK_CONFIRMATION_TRANSACTION_RETRIES = 8
_SIGNED_BIGINT_MAX = 2**63 - 1
GUEST_NAME_PLACEHOLDER = "Гость"


class VKAuthConflictError(Exception):
    category = "vk_account_conflict"


class VKIdentityAmbiguousError(Exception):
    category = "vk_identity_ambiguous"


class VKProviderRejectedError(ValueError):
    """VK did not provide a usable authenticated identity."""


class VKProviderFailureError(Exception):
    """VK could not be reached or returned a server-side failure."""

class TelegramConfirmationNotFoundError(Exception):
    category = "telegram_confirmation_not_found"


class TelegramConfirmationInvalidError(Exception):
    category = "telegram_confirmation_invalid"

    def __init__(self, attempts_remaining: int) -> None:
        self.attempts_remaining = attempts_remaining


class TelegramConfirmationUnavailableError(Exception):
    category = "telegram_confirmation_unavailable"


class TelegramLinkConfirmationService:
    """Owns short-lived, server-side Telegram link confirmations."""

    def _key(self, web_user_id: uuid.UUID) -> str:
        return f"{TELEGRAM_LINK_PENDING_PREFIX}:{web_user_id}"

    @staticmethod
    def _masked_user_id(web_user_id: uuid.UUID) -> str:
        return hashlib.sha256(str(web_user_id).encode()).hexdigest()[:12]

    @staticmethod
    def _validate_web_user_id(web_user_id: uuid.UUID | str) -> uuid.UUID:
        try:
            return web_user_id if isinstance(web_user_id, uuid.UUID) else uuid.UUID(web_user_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("web_user_id must be a UUID") from exc

    @staticmethod
    def _validate_telegram_id(telegram_id: int) -> None:
        if type(telegram_id) is not int or not 0 < telegram_id <= _SIGNED_BIGINT_MAX:
            raise ValueError("telegram_id must be a positive signed BIGINT")

    @staticmethod
    def _encode_code_hash(code: str, salt: bytes) -> str:
        digest = hashlib.pbkdf2_hmac("sha256", code.encode("ascii"), salt, 200_000)
        return base64.b64encode(digest).decode("ascii")

    @staticmethod
    def _decode_record(value: str | bytes) -> dict[str, Any]:
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        record = json.loads(value)
        if not isinstance(record, dict):
            raise ValueError("invalid pending record")
        return record

    async def _consume_invalid_attempt(
        self,
        user_id: uuid.UUID,
        code: str,
        candidate: bytes,
        original_salt: str | bytes,
    ) -> tuple[bool, int]:
        """Atomically consume one attempt, returning whether the code became valid."""
        key = self._key(user_id)
        redis = get_redis()
        for _ in range(TELEGRAM_LINK_CONFIRMATION_TRANSACTION_RETRIES):
            try:
                async with redis.pipeline() as pipeline:
                    await pipeline.watch(key)
                    value = await pipeline.get(key)
                    ttl_ms = await pipeline.pttl(key)
                    if value is None:
                        raise TelegramConfirmationNotFoundError()
                    if ttl_ms <= 0:
                        pipeline.multi()
                        pipeline.delete(key)
                        await pipeline.execute()
                        raise TelegramConfirmationNotFoundError()
                    try:
                        record = self._decode_record(value)
                        if record.get("web_user_id") != str(user_id):
                            raise ValueError("pending record user mismatch")
                        expires_at = datetime.fromisoformat(record["expires_at"])
                        if expires_at <= datetime.now(timezone.utc):
                            pipeline.multi()
                            pipeline.delete(key)
                            await pipeline.execute()
                            raise TelegramConfirmationNotFoundError()
                        expected = base64.b64decode(record["code_hash"], validate=True)
                        salt_marker = record["code_salt"]
                        if salt_marker != original_salt:
                            salt = base64.b64decode(salt_marker, validate=True)
                            candidate = base64.b64decode(self._encode_code_hash(code, salt), validate=True)
                        telegram_id = record["telegram_id"]
                        self._validate_telegram_id(telegram_id)
                        attempts = int(record.get("attempts", 0))
                    except TelegramConfirmationNotFoundError:
                        raise
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                        pipeline.multi()
                        pipeline.delete(key)
                        await pipeline.execute()
                        raise TelegramConfirmationNotFoundError() from None

                    if hmac.compare_digest(expected, candidate):
                        return True, telegram_id

                    attempts += 1
                    remaining = max(0, TELEGRAM_LINK_CONFIRMATION_MAX_ATTEMPTS - attempts)
                    pipeline.multi()
                    if remaining == 0:
                        pipeline.delete(key)
                    else:
                        record["attempts"] = attempts
                        pipeline.set(key, json.dumps(record), keepttl=True)
                    await pipeline.execute()
                    return False, remaining
            except WatchError:
                continue

        logger.warning(
            "telegram_link_confirmation_transaction_exhausted user=%s",
            self._masked_user_id(user_id),
        )
        raise TelegramConfirmationUnavailableError()

    async def create_pending(
        self,
        web_user_id: uuid.UUID | str,
        telegram_id: int,
        display_label: str | None = None,
    ) -> str:
        user_id = self._validate_web_user_id(web_user_id)
        self._validate_telegram_id(telegram_id)
        if display_label is not None and (not isinstance(display_label, str) or len(display_label) > 128):
            raise ValueError("display_label is invalid")

        code = f"{secrets.randbelow(1_000_000):06d}"
        salt = secrets.token_bytes(16)
        now = datetime.now(timezone.utc)
        record: dict[str, Any] = {
            "version": 1,
            "status": "pending_confirmation",
            "web_user_id": str(user_id),
            "telegram_id": telegram_id,
            "code_hash": self._encode_code_hash(code, salt),
            "code_salt": base64.b64encode(salt).decode("ascii"),
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=TELEGRAM_LINK_PENDING_TTL_SECONDS)).isoformat(),
            "attempts": 0,
        }
        if display_label:
            record["display_label"] = display_label
        await get_redis().setex(self._key(user_id), TELEGRAM_LINK_PENDING_TTL_SECONDS, json.dumps(record))
        logger.info("telegram_link_pending_created user=%s", self._masked_user_id(user_id))
        return code

    async def get_status(self, web_user_id: uuid.UUID | str) -> dict[str, Any]:
        user_id = self._validate_web_user_id(web_user_id)
        value = await get_redis().get(self._key(user_id))
        if value is None:
            return {"status": "idle"}
        try:
            record = self._decode_record(value)
            expires_at = datetime.fromisoformat(record["expires_at"])
            expires_in = max(0, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
            if expires_in == 0:
                await get_redis().delete(self._key(user_id))
                return {"status": "idle"}
            attempts = int(record["attempts"])
            result: dict[str, Any] = {
                "status": "pending_confirmation",
                "expires_in": expires_in,
                "attempts_remaining": max(0, TELEGRAM_LINK_CONFIRMATION_MAX_ATTEMPTS - attempts),
            }
            if isinstance(record.get("display_label"), str):
                result["display_label"] = record["display_label"]
            return result
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            await get_redis().delete(self._key(user_id))
            return {"status": "idle"}

    async def verify_confirmation(self, web_user_id: uuid.UUID | str, code: str) -> int:
        user_id = self._validate_web_user_id(web_user_id)
        value = await get_redis().get(self._key(user_id))
        if value is None:
            raise TelegramConfirmationNotFoundError()
        try:
            record = self._decode_record(value)
            if record.get("web_user_id") != str(user_id):
                raise ValueError("pending record user mismatch")
            expires_at = datetime.fromisoformat(record["expires_at"])
            if expires_at <= datetime.now(timezone.utc):
                await get_redis().delete(self._key(user_id))
                raise TelegramConfirmationNotFoundError()
            expected = base64.b64decode(record["code_hash"], validate=True)
            salt = base64.b64decode(record["code_salt"], validate=True)
            candidate = base64.b64decode(self._encode_code_hash(code, salt), validate=True)
            telegram_id = record["telegram_id"]
            self._validate_telegram_id(telegram_id)
        except TelegramConfirmationNotFoundError:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            await get_redis().delete(self._key(user_id))
            raise TelegramConfirmationNotFoundError() from None

        if not hmac.compare_digest(expected, candidate):
            is_valid, result = await self._consume_invalid_attempt(user_id, code, candidate, record["code_salt"])
            if is_valid:
                return result
            logger.info(
                "telegram_link_confirmation_failed user=%s attempts_remaining=%s",
                self._masked_user_id(user_id),
                result,
            )
            raise TelegramConfirmationInvalidError(result)
        return telegram_id

    async def delete_pending(self, web_user_id: uuid.UUID | str, event: str = "telegram_link_cancelled") -> None:
        user_id = self._validate_web_user_id(web_user_id)
        await get_redis().delete(self._key(user_id))
        logger.info("%s user=%s", event, self._masked_user_id(user_id))


class AuthService:
    def __init__(self) -> None:
        self._session_factory = get_async_sessionmaker()

    async def create_guest_profile(
        self,
        name: str,
        birth_date: str,
        quiz_answers: dict | None = None,
        report_data: dict | None = None,
    ) -> dict:
        token = uuid.uuid4().hex
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.guest_profile_ttl_days
        )
        repo = GuestProfileRepository(self._session_factory)
        await repo.create(
            token=token,
            name=name,
            birth_date=birth_date,
            quiz_answers=quiz_answers,
            report_data=report_data,
            expires_at=expires_at,
        )

        payload: dict[str, Any] = {
            "name": name,
            "birth_date": birth_date,
            "quiz_answers": quiz_answers,
            "report_data": report_data,
            "expires_at": expires_at.isoformat(),
            "merged": False,
        }
        redis = get_redis()
        ttl = settings.guest_profile_ttl_days * 86400
        await redis.setex(
            f"{GUEST_CACHE_PREFIX}:{token}",
            ttl,
            json.dumps(payload, ensure_ascii=False),
        )
        return {"guest_token": token, "expires_at": expires_at}

    async def get_guest(self, token: str) -> dict | None:
        redis = get_redis()
        key = f"{GUEST_CACHE_PREFIX}:{token}"
        raw = await redis.get(key)
        if raw is not None:
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                data = None
            if data is not None:
                return {
                    "guest_token": token,
                    "name": data.get("name"),
                    "birth_date": data.get("birth_date"),
                    "quiz_answers": data.get("quiz_answers"),
                    "report_data": data.get("report_data"),
                    "expires_at": data.get("expires_at"),
                    "merged": bool(data.get("merged", False)),
                }

        repo = GuestProfileRepository(self._session_factory)
        guest = await repo.get_by_token(token)
        if guest is None:
            return None
        guest_expires = guest.expires_at
        if guest_expires.tzinfo is None:
            guest_expires = guest_expires.replace(tzinfo=timezone.utc)
        if guest_expires < datetime.now(timezone.utc):
            return None

        payload: dict[str, Any] = {
            "name": guest.name,
            "birth_date": guest.birth_date,
            "quiz_answers": guest.quiz_answers,
            "report_data": guest.report_data,
            "expires_at": guest.expires_at.isoformat(),
            "merged": guest.merged_to_user_id is not None,
        }
        ttl = settings.guest_profile_ttl_days * 86400
        await redis.setex(key, ttl, json.dumps(payload, ensure_ascii=False))
        return {
            "guest_token": token,
            "name": payload["name"],
            "birth_date": payload["birth_date"],
            "quiz_answers": payload["quiz_answers"],
            "report_data": payload.get("report_data"),
            "expires_at": payload["expires_at"],
            "merged": payload["merged"],
        }

    async def start_email_auth(
        self,
        email: str,
        guest_token: str | None = None,
        current_user: User | None = None,
    ) -> dict:
        user_repo = UserRepository(self._session_factory)

        if current_user is not None:
            if current_user.email is None:
                await user_repo.set_email(current_user.id, email)
            elif current_user.email != email:
                await user_repo.set_email(current_user.id, email)
        else:
            existing = await user_repo.get_by_email(email)
            if existing is None:
                web_session_id = uuid.uuid4().hex
                existing = await user_repo.create_web_user(
                    name=GUEST_NAME_PLACEHOLDER,
                    birth_date="",
                    web_session_id=web_session_id,
                    email=email,
                )

        target_id = current_user.id if current_user is not None else existing.id
        magic_token = uuid.uuid4().hex
        redis = get_redis()
        ttl = settings.magic_link_ttl_minutes * 60
        await redis.setex(
            f"{MAGIC_LINK_PREFIX}:{magic_token}",
            ttl,
            json.dumps(
                {"user_id": str(target_id), "guest_token": guest_token}
            ),
        )

        try:
            from core.tasks import send_magic_link_email

            send_magic_link_email.delay(email, magic_token)
        except Exception:
            logger.exception("Failed to dispatch send_magic_link_email")

        return {"message": "Письмо отправлено", "expires_in": ttl}

    async def verify_magic_link(
        self,
        token: str,
        current_user: User | None = None,
    ) -> dict | None:
        redis = get_redis()
        key = f"{MAGIC_LINK_PREFIX}:{token}"
        raw = await redis.get(key)
        if raw is None:
            return None
        await redis.delete(key)

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

        try:
            user_id = uuid.UUID(data["user_id"])
        except (ValueError, KeyError):
            return None
        guest_token = data.get("guest_token")

        user_repo = UserRepository(self._session_factory)
        user = await user_repo.get(user_id)
        if user is None:
            return None

        await user_repo.set_email_verified(user.id, True)
        await user_repo.set_auth_method(user.id, "email")

        if user.web_session_id is None:
            web_session_id = uuid.uuid4().hex
            await user_repo.update_web_session(user.id, web_session_id)
        else:
            web_session_id = user.web_session_id
            await user_repo.renew_session_expiry(user.id)

        if guest_token:
            try:
                await self.apply_guest_data_and_create_report(guest_token, user)
            except Exception:
                logger.exception("apply_guest_data failed during magic link verify")

        return {
            "success": True,
            "user_id": str(user.id),
            "web_session_id": web_session_id,
        }

    async def apply_guest_data_and_create_report(self, guest_token: str, user: User) -> bool:
        try:
            repo = GuestProfileRepository(self._session_factory)
            guest = await repo.get_by_token(guest_token)
            if guest is None:
                return False
            if guest.merged_to_user_id is not None:
                return False

            user_repo = UserRepository(self._session_factory)
            if user.name in (None, GUEST_NAME_PLACEHOLDER, "") and guest.name:
                await user_repo.update_web_user(user.id, name=guest.name)
            if user.birth_date in (None, "") and guest.birth_date:
                await user_repo.update_web_user(user.id, birth_date=guest.birth_date)

            if guest.report_data:
                report_repo = ReportRepository(self._session_factory)
                await report_repo.create(
                    user_id=user.id,
                    report_type=ReportType.MINI,
                    token=uuid.uuid4().hex,
                    matrix_data=guest.report_data.get("matrix_data"),
                    ai_analysis=guest.report_data,
                )

            await repo.mark_merged(guest.id, user.id)
            redis = get_redis()
            await redis.delete(f"{GUEST_CACHE_PREFIX}:{guest_token}")
            return True
        except Exception:
            logger.exception("apply_guest_data failed")
            return False

    async def generate_telegram_link(self, user: User) -> dict:
        token = uuid.uuid4().hex
        redis = get_redis()
        await redis.setex(
            f"{LINK_TOKEN_PREFIX}:{token}",
            LINK_TOKEN_TTL_SECONDS,
            str(user.id),
        )
        bot_username = settings.bot_username or "nura_ai_bot"
        return {
            "token": token,
            "tg_url": f"https://t.me/{bot_username}?start=link_{token}",
            "expires_in": LINK_TOKEN_TTL_SECONDS,
        }

    async def cleanup_expired_guests(self) -> int:
        repo = GuestProfileRepository(self._session_factory)
        now = datetime.now(timezone.utc)
        return await repo.delete_expired(now)

    async def convert_guest_to_user(self, guest_token: str) -> dict | None:
        guest_repo = GuestProfileRepository(self._session_factory)
        guest = await guest_repo.get_by_token(guest_token)
        if guest is None:
            return None
        if guest.merged_to_user_id is not None:
            return None

        now = datetime.now(timezone.utc)
        if guest.expires_at:
            exp = guest.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < now:
                return None

        user_repo = UserRepository(self._session_factory)
        web_session_id = uuid.uuid4().hex

        existing = await user_repo.get_by_name_and_birth_date(
            guest.name, guest.birth_date
        )
        if existing is not None:
            if existing.account_status == "blocked":
                existing.account_status = "active"
            if existing.web_session_id is None:
                existing.web_session_id = web_session_id
                existing.web_session_expires_at = (
                    now + timedelta(seconds=settings.web_session_ttl_seconds)
                )
            existing.last_activity_at = now
            if guest.report_data:
                rd = guest.report_data
                if rd.get("main_archetype") and not existing.main_archetype:
                    full = rd["main_archetype"]
                    m = full.split("—")
                    name_part = m[1].strip().split("(")[0].strip() if len(m) > 1 else full.split(".")[0]
                    existing.main_archetype = name_part
                if rd.get("archetype_number") and not existing.main_archetype_number:
                    existing.main_archetype_number = rd["archetype_number"]
            user = existing
            await user_repo.update(user)
        else:
            report_data = guest.report_data or {}
            archetype = None
            archetype_number = None
            if report_data.get("main_archetype"):
                full = report_data["main_archetype"]
                m = full.split("—")
                archetype = m[1].strip().split("(")[0].strip() if len(m) > 1 else full.split(".")[0]
            if report_data.get("archetype_number"):
                archetype_number = report_data["archetype_number"]

            user = await user_repo.create_web_user(
                name=guest.name,
                birth_date=guest.birth_date,
                web_session_id=web_session_id,
            )
            if archetype:
                await user_repo.update_archetype(user.id, archetype, archetype_number)
            user.last_activity_at = now
            await user_repo.update(user)

        if guest.report_data:
            report_repo = ReportRepository(self._session_factory)
            existing_report = await report_repo.get_by_user_id_and_type(
                user.id, ReportType.MINI
            )
            if existing_report is None:
                await report_repo.create(
                    user_id=user.id,
                    report_type=ReportType.MINI,
                    token=uuid.uuid4().hex,
                    matrix_data=guest.report_data.get("matrix_data"),
                    ai_analysis=guest.report_data,
                )

        guest.merged_to_user_id = user.id
        await guest_repo.update(guest)

        redis = get_redis()
        cache_key = f"{GUEST_CACHE_PREFIX}:{guest_token}"
        await redis.delete(cache_key)

        return {
            "user_id": str(user.id),
            "web_session_id": user.web_session_id,
            "name": user.name or user.first_name,
        }

    async def vk_auth(
        self,
        access_token: str,
        guest_token: str | None = None,
        current_user: User | None = None,
    ) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://id.vk.com/oauth2/user_info",
                    data={
                        "client_id": settings.vk_client_id,
                        "client_secret": settings.vk_client_secret,
                        "access_token": access_token,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                resp.raise_for_status()
                try:
                    user_info = resp.json()
                except ValueError as exc:
                    logger.warning("vk_auth_provider_rejected category=malformed_response")
                    raise VKProviderRejectedError("VK token validation failed") from exc

            if not isinstance(user_info, dict):
                logger.warning("vk_auth_provider_rejected category=invalid_response")
                raise VKProviderRejectedError("VK token validation failed")

            if user_info.get("error"):
                logger.warning("vk_auth_provider_rejected category=provider_error")
                raise VKProviderRejectedError("VK token validation failed")

            user_data = user_info.get("user") if "user" in user_info else user_info
            if not isinstance(user_data, dict):
                logger.warning("vk_auth_provider_rejected category=invalid_user")
                raise VKProviderRejectedError("VK token validation failed")

            raw_vk_user_id = user_data.get("user_id")
            if (
                not isinstance(raw_vk_user_id, str)
                or not raw_vk_user_id.strip()
                or len(raw_vk_user_id) > 64
            ):
                logger.warning("vk_auth_provider_rejected category=invalid_user_id")
                raise VKProviderRejectedError("VK token validation failed")
            vk_user_id = raw_vk_user_id.strip()

            first_name = user_data.get("first_name", "")
            first_name = first_name if isinstance(first_name, str) else ""
            last_name = user_data.get("last_name", "")
            last_name = last_name if isinstance(last_name, str) else ""
            vk_name = f"{first_name} {last_name}".strip() if last_name else first_name
            email = user_data.get("email")
            email = email if isinstance(email, str) else None
            birthday = user_data.get("birthday", "")
            birthday = birthday if isinstance(birthday, str) else ""

            user_repo = UserRepository(self._session_factory)
            matches = await user_repo.get_all_by_vk_id(vk_user_id)
            if len(matches) > 1:
                logger.warning("vk_auth_identity_ambiguous")
                raise VKIdentityAmbiguousError()
            linked_user = matches[0] if matches else None

            if current_user is not None:
                if current_user.vk_id and current_user.vk_id != vk_user_id:
                    logger.warning("vk_auth_account_conflict category=current_user_has_other_vk")
                    raise VKAuthConflictError()
                if linked_user is not None and linked_user.id != current_user.id:
                    logger.warning("vk_auth_account_conflict category=vk_linked_to_other_user")
                    raise VKAuthConflictError()
                user = current_user
                if user.vk_id is None:
                    await user_repo.set_vk_id(user.id, vk_user_id)
                if user.name in (None, GUEST_NAME_PLACEHOLDER, "Пользователь", "") and vk_name:
                    await user_repo.update_web_user(user.id, name=vk_name)
                if user.birth_date in (None, "") and birthday:
                    await user_repo.update_web_user(user.id, birth_date=birthday)
                if user.email is None and email:
                    await user_repo.set_email(user.id, email)
                web_session_id = user.web_session_id
                if web_session_id is None:
                    web_session_id = uuid.uuid4().hex
                    await user_repo.update_web_session(user.id, web_session_id)
                else:
                    await user_repo.renew_session_expiry(user.id)
            elif linked_user is None:
                name = vk_name or "Пользователь"
                web_session_id = uuid.uuid4().hex
                user = await user_repo.create_web_user(
                    name=name,
                    birth_date=birthday,
                    web_session_id=web_session_id,
                    email=email,
                    vk_id=vk_user_id,
                )
            else:
                user = linked_user
                if user.name in (None, GUEST_NAME_PLACEHOLDER, "Пользователь", "") and vk_name:
                    await user_repo.update_web_user(user.id, name=vk_name)
                if user.birth_date in (None, "") and birthday:
                    await user_repo.update_web_user(user.id, birth_date=birthday)
                if user.email is None and email:
                    await user_repo.set_email(user.id, email)
                web_session_id = user.web_session_id
                if web_session_id is None:
                    web_session_id = uuid.uuid4().hex
                    await user_repo.update_web_session(user.id, web_session_id)
                else:
                    await user_repo.renew_session_expiry(user.id)

            await user_repo.set_auth_method(user.id, "vk")

            if guest_token:
                try:
                    await self.apply_guest_data_and_create_report(guest_token, user)
                except Exception:
                    logger.exception("apply_guest_data failed during vk auth")

            return {
                "success": True,
                "user_id": str(user.id),
                "web_session_id": web_session_id,
            }
        except (VKAuthConflictError, VKIdentityAmbiguousError, VKProviderRejectedError):
            raise
        except httpx.HTTPStatusError as exc:
            logger.warning("vk_auth_provider_failure category=http_status status=%s", exc.response.status_code)
            raise VKProviderFailureError() from exc
        except httpx.HTTPError as exc:
            logger.warning("vk_auth_provider_failure category=transport error=%s", type(exc).__name__)
            raise VKProviderFailureError() from exc
        except Exception:
            logger.exception("vk_auth_provider_failure category=unexpected")
            raise
