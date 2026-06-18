---
name: pytest
description: Pytest testing patterns for Python — fixtures, mocking, parametrize, markers, async tests, and pytest-asyncio. Use when writing or reviewing Python tests.
---

# Pytest Testing Patterns

## NURA Test Stack
- pytest + pytest-asyncio
- pytest-cov (coverage)
- httpx AsyncClient (for FastAPI)
- freezegun (time mocking)

## Basic Test Structure
```python
import pytest

class TestUserService:
    def test_create_user_success(self):
        user = create_user(name="John", email="john@test.com")
        assert user.name == "John"

    def test_create_user_invalid_email_fails(self):
        with pytest.raises(ValueError, match="Invalid email"):
            create_user(name="John", email="invalid")
```

## Fixtures
```python
import pytest

@pytest.fixture
def user():
    return User(name="Test User", email="test@example.com")

@pytest.fixture
def authenticated_client(client, user):
    client.force_login(user)
    return client

# Fixture with teardown
@pytest.fixture
def temp_file():
    path = Path("/tmp/test_file.txt")
    path.write_text("test content")
    yield path
    path.unlink()

# Fixture scopes
@pytest.fixture(scope="module")   # Once per module
@pytest.fixture(scope="session")  # Once per session
```

## Async Fixtures (pytest-asyncio)
```python
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest_asyncio.fixture
async def client(db_session):
    app.dependency_overrides[get_session] = lambda: db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

@pytest_asyncio.fixture
async def async_session():
    engine = create_async_engine("sqlite+aiosqlite://", echo=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session_maker() as session:
        yield session
```

## Mocking
```python
from unittest.mock import patch, MagicMock, AsyncMock

class TestPaymentService:
    def test_process_payment_success(self):
        with patch("services.payment.stripe_client") as mock_stripe:
            mock_stripe.charge.return_value = {"id": "ch_123", "status": "succeeded"}
            result = process_payment(amount=100)
            assert result["status"] == "succeeded"
            mock_stripe.charge.assert_called_once_with(amount=100)

    def test_process_payment_failure(self):
        with patch("services.payment.stripe_client") as mock_stripe:
            mock_stripe.charge.side_effect = PaymentError("Card declined")
            with pytest.raises(PaymentError):
                process_payment(amount=100)

# AsyncMock for async functions
async def test_async_service():
    mock_repo = AsyncMock()
    mock_repo.get_by_id.return_value = User(id=1, name="Test")
    service = UserService(mock_repo)
    result = await service.get_user(1)
    assert result.name == "Test"
```

## Parametrize
```python
@pytest.mark.parametrize("email,is_valid", [
    ("user@example.com", True),
    ("invalid-email", False),
    ("", False),
])
def test_email_validation(email, is_valid):
    assert validate_email(email) == is_valid
```

## Testing Retry Behavior
```python
def test_retries_on_transient_error():
    client = Mock()
    client.request.side_effect = [
        ConnectionError("Failed"),
        ConnectionError("Failed"),
        {"status": "ok"},
    ]
    service = ServiceWithRetry(client, max_retries=3)
    result = service.fetch()
    assert result == {"status": "ok"}
    assert client.request.call_count == 3
```

## Mocking Time
```python
from freezegun import freeze_time
from datetime import datetime

@freeze_time("2026-01-15 10:00:00")
def test_token_expiry():
    token = create_token(expires_in_seconds=3600)
    assert token.expires_at == datetime(2026, 1, 15, 11, 0, 0)

def test_with_time_travel():
    with freeze_time("2026-01-01") as frozen_time:
        item = create_item()
        frozen_time.move_to("2026-01-15")
        assert item.age_days == 14
```

## Markers
```python
@pytest.mark.slow
def test_large_data(): ...

@pytest.mark.integration
def test_database(): ...

@pytest.mark.skip(reason="Not implemented yet")
def test_future(): ...

@pytest.mark.skipif(sys.platform == "win32", reason="Unix only")
def test_unix(): ...

# Run: pytest -m "not slow"
# Run: pytest -m integration
```

## Commands
```bash
pytest                          # All tests
pytest -v                       # Verbose
pytest -x                       # Stop on first failure
pytest -k "test_user"           # Filter by name
pytest -m "not slow"            # Filter by marker
pytest --cov=src --cov-report=term-missing  # Coverage
pytest -n auto                  # Parallel (pytest-xdist)
pytest --tb=short               # Short traceback
pytest tests/test_bot/ -v       # Only bot tests
```

## NURA Test Layout
```
tests/
├── conftest.py            # Shared fixtures (db, client, redis)
├── test_unit/
│   ├── test_services.py
│   └── test_repositories.py
├── test_api/
│   └── test_routes.py
├── test_bot/
│   ├── test_handlers.py
│   └── conftest.py
└── integration/
    └── test_workflows.py
```
