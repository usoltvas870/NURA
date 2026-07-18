from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.dependencies import SESSION_COOKIE_NAME, set_session_cookie
from api.routes.auth import vk_auth
from core.models import User
from core.repositories.user import UserRepository
from core.schemas.auth import VKTokenRequest
from core.services.auth import (
    AuthService,
    VKAuthConflictError,
    VKIdentityAmbiguousError,
    VKProviderFailureError,
    VKProviderRejectedError,
)


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.store[key] = value

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


class ProviderResponse:
    def __init__(
        self,
        payload: object = None,
        error: Exception | None = None,
        json_error: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.error = error
        self.json_error = json_error
        self.status_code = 503

    def raise_for_status(self) -> None:
        if self.error:
            raise self.error

    def json(self) -> object:
        if self.json_error:
            raise self.json_error
        return self.payload


class ProviderClient:
    response = ProviderResponse({"user": {"user_id": "vk-default"}})

    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self) -> ProviderClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(self, *_: object, **__: object) -> ProviderResponse:
        return self.response


@pytest_asyncio.fixture
async def auth_service(db_engine, monkeypatch: pytest.MonkeyPatch) -> AuthService:
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    redis = FakeRedis()
    monkeypatch.setattr("core.services.auth.get_async_sessionmaker", lambda: factory)
    monkeypatch.setattr("core.services.auth.get_redis", lambda: redis)
    monkeypatch.setattr("core.services.auth.httpx.AsyncClient", ProviderClient)
    return AuthService()


def provider(
    payload: object = None,
    error: Exception | None = None,
    json_error: Exception | None = None,
) -> None:
    ProviderClient.response = ProviderResponse(payload, error, json_error)


async def user_count(service: AuthService) -> int:
    async with service._session_factory() as session:
        return int((await session.execute(select(func.count()).select_from(User))).scalar_one())


async def make_user(service: AuthService, *, vk_id: str | None = None, **values: object) -> User:
    repo = UserRepository(service._session_factory)
    suffix = uuid.uuid4().hex[:8]
    return await repo.create_web_user(
        name=str(values.get("name", f"Existing {suffix}")),
        birth_date=str(values.get("birth_date", f"01.01.{suffix[:4]}")),
        web_session_id=str(values.get("web_session_id", uuid.uuid4().hex)),
        email=values.get("email") if isinstance(values.get("email"), str) else None,
        vk_id=vk_id,
    )


@pytest.mark.parametrize("token", ["a" * 20, "b" * 4096])
def test_vk_request_schema_accepts_boundary_tokens(token: str) -> None:
    assert VKTokenRequest(access_token=token).access_token == token


@pytest.mark.parametrize("token", ["a" * 19, "b" * 4097])
def test_vk_request_schema_rejects_invalid_token_length(token: str) -> None:
    with pytest.raises(ValueError):
        VKTokenRequest(access_token=token)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"user": {"user_id": "vk-nested", "first_name": "N", "email": "n@example.test"}},
    {"user_id": "vk-top", "first_name": "T"},
])
async def test_vk_provider_identity_creates_user_and_session(auth_service: AuthService, payload: dict) -> None:
    provider(payload)
    result = await auth_service.vk_auth("a" * 20)
    assert result["success"] is True and result["web_session_id"]
    assert await user_count(auth_service) == 1
    user = await UserRepository(auth_service._session_factory).get(uuid.UUID(result["user_id"]))
    assert user is not None and "access_token" not in user.__dict__


@pytest.mark.asyncio
async def test_existing_vk_login_reuses_account_without_duplicate(auth_service: AuthService) -> None:
    existing = await make_user(auth_service, vk_id="vk-existing")
    provider({"user": {"user_id": "vk-existing"}})
    result = await auth_service.vk_auth("a" * 20)
    assert result["user_id"] == str(existing.id)
    assert await user_count(auth_service) == 1


@pytest.mark.asyncio
async def test_authenticated_user_links_unclaimed_vk_identity(auth_service: AuthService) -> None:
    current = await make_user(auth_service, name="Kept", email="kept@example.test")
    provider({"user": {"user_id": "vk-free", "first_name": "Ignored", "email": "other@example.test"}})
    result = await auth_service.vk_auth("a" * 20, current_user=current)
    repo = UserRepository(auth_service._session_factory)
    refreshed = await repo.get(current.id)
    assert result["user_id"] == str(current.id) and refreshed and refreshed.vk_id == "vk-free"
    assert refreshed.name == "Kept" and refreshed.email == "kept@example.test"
    assert await user_count(auth_service) == 1


@pytest.mark.asyncio
async def test_authenticated_user_with_same_vk_continues_session(auth_service: AuthService) -> None:
    current = await make_user(auth_service, vk_id="vk-same")
    provider({"user_id": "vk-same"})
    result = await auth_service.vk_auth("a" * 20, current_user=current)
    assert result["user_id"] == str(current.id) and result["web_session_id"] == current.web_session_id


@pytest.mark.asyncio
async def test_conflicting_vk_identity_does_not_switch_account(auth_service: AuthService) -> None:
    current = await make_user(auth_service, vk_id=None)
    other = await make_user(auth_service, vk_id="vk-other")
    provider({"user_id": "vk-other"})
    with pytest.raises(VKAuthConflictError):
        await auth_service.vk_auth("a" * 20, current_user=current)
    assert current.web_session_id != other.web_session_id and await user_count(auth_service) == 2


@pytest.mark.asyncio
async def test_current_user_cannot_replace_existing_vk_identity(auth_service: AuthService) -> None:
    current = await make_user(auth_service, vk_id="vk-old")
    provider({"user_id": "vk-new"})
    with pytest.raises(VKAuthConflictError):
        await auth_service.vk_auth("a" * 20, current_user=current)
    assert (await UserRepository(auth_service._session_factory).get(current.id)).vk_id == "vk-old"


@pytest.mark.asyncio
async def test_duplicate_vk_identity_is_rejected_without_selecting_user(auth_service: AuthService) -> None:
    await make_user(auth_service, vk_id="vk-duplicate")
    await make_user(auth_service, vk_id="vk-duplicate")
    provider({"user_id": "vk-duplicate"})
    with pytest.raises(VKIdentityAmbiguousError):
        await auth_service.vk_auth("a" * 20)


@pytest.mark.asyncio
async def test_guest_merge_happens_only_after_identity_resolution(auth_service: AuthService) -> None:
    guest = await auth_service.create_guest_profile("Guest", "01.01.2000")
    provider({"user_id": "vk-guest"})
    result = await auth_service.vk_auth("a" * 20, guest_token=guest["guest_token"])
    assert result["success"] is True
    provider({"user_id": "vk-guest"})
    assert await auth_service.vk_auth("a" * 20, guest_token=guest["guest_token"])


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"error": "invalid_token"}, {}, {"user": {"user_id": ""}},
    {"user_id": 123}, [], {"user": []},
])
async def test_provider_rejections_are_safe_401_domain_errors(auth_service: AuthService, payload: object) -> None:
    provider(payload)
    with pytest.raises(VKProviderRejectedError):
        await auth_service.vk_auth("a" * 20)


@pytest.mark.asyncio
async def test_malformed_provider_json_is_rejected(auth_service: AuthService) -> None:
    provider(json_error=ValueError("invalid json"))
    with pytest.raises(VKProviderRejectedError):
        await auth_service.vk_auth("a" * 20)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    httpx.HTTPStatusError("bad", request=MagicMock(), response=MagicMock(status_code=503)),
    httpx.ReadTimeout("timeout"),
])
async def test_provider_transport_failures_are_502_domain_errors(auth_service: AuthService, error: Exception) -> None:
    provider(error=error)
    with pytest.raises(VKProviderFailureError):
        await auth_service.vk_auth("a" * 20)


@pytest.mark.asyncio
async def test_route_maps_conflict_without_setting_cookie(auth_service: AuthService) -> None:
    current = await make_user(auth_service)
    await make_user(auth_service, vk_id="vk-route-conflict")
    provider({"user_id": "vk-route-conflict"})
    response = Response()
    with pytest.raises(HTTPException) as exc:
        await vk_auth.__wrapped__(
            MagicMock(), VKTokenRequest(access_token="a" * 20), response, current
        )
    assert exc.value.status_code == 409 and exc.value.detail == "vk_account_conflict"
    assert "set-cookie" not in response.headers


def test_session_cookie_contract() -> None:
    response = Response()
    set_session_cookie(response, "session-value")
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE_NAME}=session-value;")
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie and "Max-Age=" in cookie


def test_no_token_or_guest_token_is_in_domain_error_text() -> None:
    assert "secret-token" not in str(VKProviderRejectedError("VK token validation failed"))
    assert "guest-token" not in str(VKAuthConflictError())
