import httpx
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

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
GUEST_NAME_PLACEHOLDER = "Гость"


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

    async def vk_auth(
        self,
        access_token: str | None = None,
        vk_user_id: str | None = None,
        code: str | None = None,
        guest_token: str | None = None,
        current_user: User | None = None,
        vk_email: str | None = None,
    ) -> dict:
        vk_email_from_token = None
        try:
            async with httpx.AsyncClient() as client:
                if code:
                    token_resp = await client.post(
                        "https://oauth.vk.com/access_token",
                        data={
                            "client_id": settings.vk_client_id,
                            "client_secret": settings.vk_client_secret,
                            "code": code,
                            "redirect_uri": settings.vk_redirect_uri,
                        },
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    token_resp.raise_for_status()
                    token_data = token_resp.json()
                    logger.info("VK OAuth token response: %s", json.dumps(token_data, ensure_ascii=False))

                    if not isinstance(token_data, dict) or token_data.get("error"):
                        logger.error("VK OAuth error: %s", token_data if isinstance(token_data, dict) else type(token_data).__name__)
                        raise ValueError("VK code exchange failed")

                    access_token = token_data.get("access_token")
                    vk_user_id = str(token_data.get("user_id")) if token_data.get("user_id") is not None else None

                    if not access_token or not vk_user_id:
                        logger.error("VK OAuth missing access_token or user_id")
                        raise ValueError("VK code exchange failed")

                resp = await client.get(
                    "https://api.vk.com/method/users.get",
                    params={
                        "user_ids": vk_user_id,
                        "fields": "first_name,last_name,bdate",
                        "access_token": access_token,
                        "v": "5.131",
                    },
                )
                resp.raise_for_status()
                user_info = resp.json()
                logger.info("VK API users.get response: %s", json.dumps(user_info, ensure_ascii=False))

                vk_email_from_token = token_data.get("email") if code else None

            if not isinstance(user_info, dict):
                logger.error("VK API response is not a dict: %s", type(user_info).__name__)
                raise ValueError("VK user_info is invalid")

            if user_info.get("error"):
                logger.error("VK API error: %s", json.dumps(user_info, ensure_ascii=False))
                raise ValueError("VK user_info is invalid")

            user_data_list = user_info.get("response")
            if not isinstance(user_data_list, list) or len(user_data_list) == 0:
                logger.error("VK API users.get returned empty response: %s", json.dumps(user_info, ensure_ascii=False))
                raise ValueError("VK user_info is invalid")

            user_data = user_data_list[0]
            info_user_id = str(user_data.get("id")) if user_data.get("id") is not None else None
            if info_user_id is None or info_user_id != str(vk_user_id):
                logger.error(
                    "VK user_id mismatch: exchange=%s, user_info=%s",
                    vk_user_id,
                    info_user_id,
                )
                raise ValueError("VK user_id mismatch")

            first_name = user_data.get("first_name", "")
            last_name = user_data.get("last_name", "")
            vk_name = f"{first_name} {last_name}".strip() if last_name else first_name
            email = vk_email or vk_email_from_token
            bdate = user_data.get("bdate", "")
            birthday = bdate if len(bdate.split(".")) == 3 else ""

            user_repo = UserRepository(self._session_factory)
            user = await user_repo.get_by_vk_id(vk_user_id)

            if user is None:
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
        except httpx.HTTPStatusError as e:
            logger.error("VK OAuth API error: %s", e.response.text if e.response is not None else "no response")
            raise
        except Exception:
            logger.exception("vk_auth failed")
            raise