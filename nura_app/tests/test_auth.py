import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import core.tasks as core_tasks
from core.repositories.guest import GuestProfileRepository
from core.repositories.user import UserRepository
from core.services.auth import AuthService


# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str | bytes] = {}

    async def setex(self, key, ttl, value):  # noqa: ANN001
        self.store[key] = value

    async def get(self, key):  # noqa: ANN001
        return self.store.get(key)

    async def delete(self, key):  # noqa: ANN001
        self.store.pop(key, None)


@pytest.fixture
def fake_redis() -> _FakeRedis:
    return _FakeRedis()


@pytest.fixture
def mock_send_email(monkeypatch) -> MagicMock:
    m = MagicMock()
    monkeypatch.setattr(core_tasks, "send_magic_link_email", m)
    return m


def _factory(db_engine) -> async_sessionmaker:
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def auth_service(
    db_engine,
    fake_redis: _FakeRedis,
    mock_send_email: MagicMock,
    monkeypatch,
) -> AuthService:
    factory = _factory(db_engine)
    monkeypatch.setattr("core.services.auth.get_async_sessionmaker", lambda: factory)
    monkeypatch.setattr("core.services.auth.get_redis", lambda: fake_redis)
    return AuthService()


# ---------------------------------------------------------------------------
# Repo tests (real SQLite DB, no redis)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guest_repo_create_and_get(db_engine):
    factory = _factory(db_engine)
    repo = GuestProfileRepository(factory)
    expires_at = datetime.now(timezone.utc) + timedelta(days=10)
    guest = await repo.create(
        token="tok-create-001",
        expires_at=expires_at,
        name="Алина",
        birth_date="15.03.1990",
        quiz_answers={"q": "a"},
        report_data={"r": 1},
    )
    assert guest.guest_token == "tok-create-001"
    assert guest.name == "Алина"
    assert guest.birth_date == "15.03.1990"
    assert guest.quiz_answers == {"q": "a"}
    assert guest.report_data == {"r": 1}
    assert guest.merged_to_user_id is None

    fetched = await repo.get_by_token("tok-create-001")
    assert fetched is not None
    assert fetched.id == guest.id
    assert fetched.name == "Алина"
    assert fetched.quiz_answers == {"q": "a"}


@pytest.mark.asyncio
async def test_guest_repo_mark_merged(db_engine, test_user):
    factory = _factory(db_engine)
    repo = GuestProfileRepository(factory)
    expires_at = datetime.now(timezone.utc) + timedelta(days=5)
    guest = await repo.create(
        token="tok-merged-001",
        expires_at=expires_at,
        name="Гость2",
        birth_date="02.02.2000",
    )

    await repo.mark_merged(guest.id, test_user.id)

    fetched = await repo.get_by_token("tok-merged-001")
    assert fetched is not None
    assert fetched.merged_to_user_id == test_user.id


@pytest.mark.asyncio
async def test_guest_repo_delete_expired(db_engine):
    factory = _factory(db_engine)
    repo = GuestProfileRepository(factory)
    past = datetime.now(timezone.utc) - timedelta(days=1)
    future = datetime.now(timezone.utc) + timedelta(days=10)

    await repo.create(token="tok-expired-001", expires_at=past, name="old", birth_date="01.01.1990")
    await repo.create(token="tok-active-001", expires_at=future, name="new", birth_date="02.02.2000")

    now = datetime.now(timezone.utc)
    deleted = await repo.delete_expired(now)
    assert deleted == 1

    assert await repo.get_by_token("tok-expired-001") is None
    active = await repo.get_by_token("tok-active-001")
    assert active is not None
    assert active.name == "new"


@pytest.mark.asyncio
async def test_user_repo_set_email_verified_and_auth_method(db_engine):
    factory = _factory(db_engine)
    repo = UserRepository(factory)
    user = await repo.create_web_user(
        name="Alice",
        birth_date="10.10.1995",
        web_session_id=uuid.uuid4().hex,
        email="alice@example.com",
    )
    assert user.email_verified is False

    await repo.set_email_verified(user.id, True)
    await repo.set_auth_method(user.id, "email")
    await repo.set_phone(user.id, "+79990001122")
    await repo.set_phone_verified(user.id, True)

    fetched = await repo.get(user.id)
    assert fetched is not None
    assert fetched.email_verified is True
    assert fetched.auth_method == "email"
    assert fetched.phone == "+79990001122"
    assert fetched.phone_verified is True


@pytest.mark.asyncio
async def test_user_repo_get_by_email_and_phone(db_engine):
    factory = _factory(db_engine)
    repo = UserRepository(factory)
    user = await repo.create_web_user(
        name="Bob",
        birth_date="20.05.1988",
        web_session_id=uuid.uuid4().hex,
        email="bob@example.com",
    )
    await repo.set_phone(user.id, "+79991230099")

    by_email = await repo.get_by_email("bob@example.com")
    assert by_email is not None
    assert by_email.id == user.id

    by_phone = await repo.get_by_phone("+79991230099")
    assert by_phone is not None
    assert by_phone.id == user.id

    assert await repo.get_by_email("nobody@example.com") is None
    assert await repo.get_by_phone("+70000000000") is None


# ---------------------------------------------------------------------------
# Service tests (patched factory + fake_redis + mock celery)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_guest_profile_returns_token_and_caches(
    auth_service: AuthService, fake_redis: _FakeRedis
):
    result = await auth_service.create_guest_profile(
        "Алина", "15.03.1990", quiz_answers={"q": "a"}
    )
    token = result["guest_token"]
    assert isinstance(token, str)
    assert re.fullmatch(r"[0-9a-f]{32}", token)

    expires_at = result["expires_at"]
    assert expires_at.tzinfo is not None
    assert expires_at > datetime.now(timezone.utc)

    key = f"guest_profile:{token}"
    assert key in fake_redis.store
    payload = json.loads(fake_redis.store[key])
    assert payload["name"] == "Алина"
    assert payload["birth_date"] == "15.03.1990"
    assert payload["quiz_answers"] == {"q": "a"}
    assert payload["merged"] is False


@pytest.mark.asyncio
async def test_get_guest_from_cache(auth_service: AuthService, fake_redis: _FakeRedis):
    token = uuid.uuid4().hex
    payload = {
        "name": "Кэш",
        "birth_date": "11.11.1999",
        "quiz_answers": {"q": "b"},
        "report_data": None,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
        "merged": True,
    }
    fake_redis.store[f"guest_profile:{token}"] = json.dumps(payload, ensure_ascii=False)

    guest = await auth_service.get_guest(token)
    assert guest is not None
    assert guest["guest_token"] == token
    assert guest["name"] == "Кэш"
    assert guest["birth_date"] == "11.11.1999"
    assert guest["quiz_answers"] == {"q": "b"}
    assert guest["merged"] is True


@pytest.mark.asyncio
async def test_get_guest_from_db_when_cache_miss(
    auth_service: AuthService, fake_redis: _FakeRedis
):
    created = await auth_service.create_guest_profile(
        "ДБ", "05.07.2001", quiz_answers={"x": 1}
    )
    token = created["guest_token"]
    fake_redis.store.clear()

    guest = await auth_service.get_guest(token)
    assert guest is not None
    assert guest["guest_token"] == token
    assert guest["name"] == "ДБ"
    assert guest["quiz_answers"] == {"x": 1}
    assert guest["merged"] is False
    # cache repopulated
    assert f"guest_profile:{token}" in fake_redis.store


@pytest.mark.asyncio
async def test_get_guest_unknown_returns_none(auth_service: AuthService):
    assert await auth_service.get_guest("nope") is None


@pytest.mark.asyncio
async def test_start_email_auth_creates_user_and_stores_magic_link(
    auth_service: AuthService,
    fake_redis: _FakeRedis,
    mock_send_email: MagicMock,
    db_engine,
):
    email = "test@example.com"
    result = await auth_service.start_email_auth(email)
    expected_ttl = 15 * 60
    assert result["expires_in"] == expected_ttl

    assert mock_send_email.delay.call_count == 1
    call = mock_send_email.delay.call_args
    sent_email, sent_token = call.args[0], call.args[1]
    assert sent_email == email
    assert re.fullmatch(r"[0-9a-f]{32}", sent_token)

    key = f"magic_link:{sent_token}"
    assert key in fake_redis.store
    data = json.loads(fake_redis.store[key])
    assert data["guest_token"] is None
    assert "user_id" in data
    user_id = uuid.UUID(data["user_id"])

    factory = _factory(db_engine)
    repo = UserRepository(factory)
    user = await repo.get(user_id)
    assert user is not None
    assert user.email == email
    assert user.email_verified is False


@pytest.mark.asyncio
async def test_verify_magic_link_success_sets_verified_and_session(
    auth_service: AuthService,
    fake_redis: _FakeRedis,
    db_engine,
):
    factory = _factory(db_engine)
    repo = UserRepository(factory)
    user = await repo.create_web_user(
        name="Verify",
        birth_date="01.01.1990",
        web_session_id=uuid.uuid4().hex,
        email="verify@example.com",
    )
    token = uuid.uuid4().hex
    fake_redis.store[f"magic_link:{token}"] = json.dumps(
        {"user_id": str(user.id), "guest_token": None}
    )

    result = await auth_service.verify_magic_link(token)
    assert result is not None
    assert result["success"] is True
    assert result["user_id"] == str(user.id)
    assert result["web_session_id"] is not None

    assert f"magic_link:{token}" not in fake_redis.store

    fetched = await repo.get(user.id)
    assert fetched is not None
    assert fetched.email_verified is True
    assert fetched.auth_method == "email"


@pytest.mark.asyncio
async def test_verify_magic_link_expired_returns_none(
    auth_service: AuthService, fake_redis: _FakeRedis
):
    assert await auth_service.verify_magic_link("badtoken") is None


@pytest.mark.asyncio
async def test_verify_magic_link_merges_guest(
    auth_service: AuthService,
    fake_redis: _FakeRedis,
    db_engine,
):
    factory = _factory(db_engine)
    guest_repo = GuestProfileRepository(factory)
    user_repo = UserRepository(factory)

    expires_at = datetime.now(timezone.utc) + timedelta(days=10)
    guest = await guest_repo.create(
        token="tok-merge-guest",
        expires_at=expires_at,
        name="Настоящее Имя",
        birth_date="07.07.2007",
        quiz_answers={"m": 1},
    )
    fake_redis.store["guest_profile:tok-merge-guest"] = json.dumps(
        {"name": "Настоящее Имя", "merged": False}, ensure_ascii=False
    )

    user = await user_repo.create_web_user(
        name="Гость",
        birth_date="",
        web_session_id=uuid.uuid4().hex,
    )

    magic_token = uuid.uuid4().hex
    fake_redis.store[f"magic_link:{magic_token}"] = json.dumps(
        {"user_id": str(user.id), "guest_token": "tok-merge-guest"}
    )

    result = await auth_service.verify_magic_link(magic_token)
    assert result is not None
    assert result["success"] is True

    fetched_user = await user_repo.get(user.id)
    assert fetched_user is not None
    assert fetched_user.name == "Настоящее Имя"
    assert fetched_user.birth_date == "07.07.2007"

    fetched_guest = await guest_repo.get_by_token("tok-merge-guest")
    assert fetched_guest is not None
    assert fetched_guest.merged_to_user_id == user.id

    assert "guest_profile:tok-merge-guest" not in fake_redis.store


@pytest.mark.asyncio
async def test_merge_guest_idempotent(
    auth_service: AuthService, db_engine
):
    factory = _factory(db_engine)
    guest_repo = GuestProfileRepository(factory)
    user_repo = UserRepository(factory)

    expires_at = datetime.now(timezone.utc) + timedelta(days=10)
    guest = await guest_repo.create(
        token="tok-idemp",
        expires_at=expires_at,
        name="Идемпотент",
        birth_date="09.09.1999",
    )
    user = await user_repo.create_web_user(
        name="Гость",
        birth_date="",
        web_session_id=uuid.uuid4().hex,
    )

    first = await auth_service.merge_guest("tok-idemp", user)
    assert first is True

    second = await auth_service.merge_guest("tok-idemp", user)
    assert second is False


@pytest.mark.asyncio
async def test_generate_telegram_link(
    auth_service: AuthService, fake_redis: _FakeRedis, db_engine
):
    factory = _factory(db_engine)
    repo = UserRepository(factory)
    user = await repo.create_web_user(
        name="Linker",
        birth_date="12.12.1990",
        web_session_id=uuid.uuid4().hex,
    )

    result = await auth_service.generate_telegram_link(user)
    token = result["token"]
    assert re.fullmatch(r"[0-9a-f]{32}", token)
    assert "?start=link_" in result["tg_url"]
    assert token in result["tg_url"]
    assert result["expires_in"] == 900

    assert fake_redis.store[f"link_token:{token}"] == str(user.id)


@pytest.mark.asyncio
async def test_cleanup_expired_guests(
    auth_service: AuthService, db_engine
):
    factory = _factory(db_engine)
    repo = GuestProfileRepository(factory)
    past = datetime.now(timezone.utc) - timedelta(days=2)
    future = datetime.now(timezone.utc) + timedelta(days=20)
    await repo.create(
        token="tok-cleanup-old", expires_at=past, name="old", birth_date="01.01.1980"
    )
    await repo.create(
        token="tok-cleanup-new", expires_at=future, name="new", birth_date="02.02.2020"
    )

    removed = await auth_service.cleanup_expired_guests()
    assert removed == 1
    assert await repo.get_by_token("tok-cleanup-old") is None
    assert await repo.get_by_token("tok-cleanup-new") is not None