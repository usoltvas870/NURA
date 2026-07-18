from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.schemas.auth import EmailAuthResponse
from tests.e2e_harness import create_e2e_harness


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "test")
    with TestClient(create_e2e_harness()) as test_client:
        test_client.post("/__e2e__/email/outbox/reset")
        yield test_client


def send(client: TestClient) -> str:
    response = client.post("/api/v1/auth/email/send", json={"email": "e2e@example.test"})
    assert response.status_code == 200
    EmailAuthResponse.model_validate(response.json())
    return client.get("/__e2e__/email/outbox").json()["messages"][-1]["token"]


def test_email_request_has_safe_response_and_outbox(client: TestClient) -> None:
    token = send(client)
    outbox = client.get("/__e2e__/email/outbox").json()
    assert outbox["count"] == 1 and outbox["messages"][0]["recipient"] == "e***@example.test"
    assert token not in client.get("/__e2e__/requests").text


def test_valid_token_creates_cookie_and_is_single_use(client: TestClient) -> None:
    token = send(client)
    response = client.get(f"/api/v1/auth/email/verify?token={token}", follow_redirects=False)
    assert response.status_code == 302 and response.headers["location"] == "/app/" and "web_session=" in response.headers["set-cookie"]
    assert client.get(f"/api/v1/auth/email/verify?token={token}", follow_redirects=False).headers["location"] == "/?error=token_expired"


@pytest.mark.parametrize("token", ("invalid", "e2e-email-999"))
def test_invalid_tokens_are_rejected(client: TestClient, token: str) -> None:
    assert client.get(f"/api/v1/auth/email/verify?token={token}", follow_redirects=False).headers["location"] == "/?error=token_expired"


def test_expire_provider_failure_reset_and_parallel_tokens(client: TestClient) -> None:
    first, second = send(client), send(client)
    assert first != second
    client.post("/__e2e__/email/token/expire")
    assert client.get(f"/api/v1/auth/email/verify?token={first}", follow_redirects=False).headers["location"] == "/?error=token_expired"
    client.post("/__e2e__/email/outbox/reset")
    client.post("/__e2e__/email/provider/fail")
    response = client.post("/api/v1/auth/email/send", json={"email": "e2e@example.test"})
    assert response.status_code == 503 and "e2e@example.test" not in response.text
    client.post("/__e2e__/email/outbox/reset")
    assert client.get("/__e2e__/email/outbox").json()["count"] == 0
