from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Browser, sync_playwright

from api.routes.tarot_pwa import DailyCardResponse, SpreadResponse
from api.routes.web import NotificationPrefsResponse, UserProfileResponse
from core.schemas.chat import ChatQuotaState, ChatResponse
from tests.e2e_harness import PERSONAS, PERSONA_HEADER, create_e2e_harness


E2E_BASE_URL = "http://127.0.0.1:4174"


@pytest.fixture(scope="module")
def e2e_server() -> Iterator[None]:
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.e2e_harness:create_e2e_harness", "--factory", "--host", "127.0.0.1", "--port", "4174"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=os.environ | {"APP_ENV": "test"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(40):
        try:
            urllib.request.urlopen(f"{E2E_BASE_URL}/app/index.html?e2e=1", timeout=0.25)
            break
        except OSError:
            time.sleep(0.1)
    else:
        process.terminate()
        raise RuntimeError("E2E harness did not start")
    yield
    process.terminate()
    process.wait(timeout=5)


@pytest.fixture(scope="module")
def chromium(e2e_server: None) -> Iterator[Browser]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "test")
    with TestClient(create_e2e_harness()) as test_client:
        yield test_client


def headers(persona: str) -> dict[str, str]:
    return {PERSONA_HEADER: persona}


def test_harness_refuses_non_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for environment in (None, "production", "staging"):
        if environment is None:
            monkeypatch.delenv("APP_ENV", raising=False)
        else:
            monkeypatch.setenv("APP_ENV", environment)
        with pytest.raises(RuntimeError, match="APP_ENV=test"):
            create_e2e_harness()


def test_harness_serves_real_pwa_with_no_store_and_no_service_worker(client: TestClient) -> None:
    page = client.get("/app/index.html")
    assert page.status_code == 200
    assert "nura-pwa.js" in page.text
    assert page.headers["cache-control"] == "no-store"
    assert client.get("/service-worker.js").status_code == 404
    assert client.get("/pwa-install.js").headers["content-type"].startswith("application/javascript")
    vendor_asset = client.get("/assets/vendor/vkid-sdk.js")
    expected_asset = (Path(__file__).parents[2] / "frontend/assets/vendor/vkid-sdk.js").read_bytes()
    assert vendor_asset.status_code == 200
    assert vendor_asset.headers["content-type"].startswith("application/javascript")
    assert vendor_asset.content == expected_asset
    assert b"window.VKIDSDK=window.VKIDSDK||{};" not in vendor_asset.content


def test_chromium_loads_same_origin_vkid_sdk_without_external_bundle_requests(chromium: Browser) -> None:
    context = chromium.new_context(service_workers="block")
    requests: list[str] = []
    errors: list[str] = []
    context.route("https://**/*", lambda route: route.abort())
    page = context.new_page()
    page.on("request", lambda request: requests.append(request.url))
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        home = page.goto(f"{E2E_BASE_URL}/app/index.html?e2e=1", wait_until="domcontentloaded", timeout=15_000)
        assert home and home.status == 200
        assert page.evaluate("""() => Boolean(
            window.VKIDSDK &&
            typeof window.VKIDSDK.Config.init === 'function' &&
            typeof window.VKIDSDK.Auth.login === 'function' &&
            typeof window.VKIDSDK.Auth.exchangeCode === 'function'
        )""")
        assert f"{E2E_BASE_URL}/assets/vendor/vkid-sdk.js" in requests
        assert not any("npmjs.org" in url or "unpkg.com" in url or "cdn." in url for url in requests)
        assert not errors

        callback = page.goto(f"{E2E_BASE_URL}/vk-callback.html", wait_until="domcontentloaded", timeout=15_000)
        assert callback and callback.status == 200
        assert not errors
    finally:
        context.close()


@pytest.mark.parametrize("persona", sorted(PERSONAS))
def test_each_persona_is_selectable(client: TestClient, persona: str) -> None:
    response = client.get("/__e2e__/state", headers=headers(persona))
    assert response.status_code == 200
    assert response.json()["persona"] == persona
    assert response.headers["cache-control"] == "no-store"


def test_unknown_persona_is_rejected_safely(client: TestClient) -> None:
    response = client.get("/api/v1/web/me", headers=headers("not_a_persona"))
    assert response.status_code == 400
    assert response.json() == {"detail": "unknown_e2e_persona"}
    assert response.headers["x-request-id"].startswith("e2e-")


def test_guest_contract(client: TestClient) -> None:
    for path in ("/api/v1/web/session-check", "/api/v1/web/me", "/api/v1/web/chat/state", "/api/v1/web/notifications", "/api/v1/tarot/daily-card"):
        assert client.get(path, headers=headers("guest")).status_code == 401


@pytest.mark.parametrize("persona", ("free", "premium", "expired"))
def test_subscription_persona_contracts_use_production_models(client: TestClient, persona: str) -> None:
    request_headers = headers(persona)
    assert client.get("/api/v1/web/session-check", headers=request_headers).json() == {"authenticated": True}
    profile = UserProfileResponse.model_validate(client.get("/api/v1/web/me", headers=request_headers).json())
    quota = ChatQuotaState.model_validate(client.get("/api/v1/web/chat/state", headers=request_headers).json())
    NotificationPrefsResponse.model_validate(client.get("/api/v1/web/notifications", headers=request_headers).json())
    DailyCardResponse.model_validate(client.get("/api/v1/tarot/daily-card", headers=request_headers).json())
    if persona == "free":
        assert profile.subscription_status == "free" and not profile.has_tarot and quota.messages_left == 10
    elif persona == "premium":
        assert profile.subscription_status == "premium" and profile.has_tarot and quota.messages_left is None
    else:
        assert profile.subscription_status == "expired" and not profile.has_tarot and profile.subscription_until == "31.12.2029"


def test_profile_report_and_telegram_personas(client: TestClient) -> None:
    matrix = UserProfileResponse.model_validate(client.get("/api/v1/web/me", headers=headers("matrix_owner")).json())
    report = UserProfileResponse.model_validate(client.get("/api/v1/web/me", headers=headers("report_owner")).json())
    connected = client.get("/api/v1/web/me", headers=headers("telegram_connected")).json()
    disconnected = client.get("/api/v1/web/me", headers=headers("telegram_disconnected")).json()
    assert matrix.has_matrix and matrix.reports[0].report_type == "full"
    assert report.reports[0].url == "/report/e2e-finished-report"
    assert connected["telegram_linked"] is True and disconnected["telegram_linked"] is False
    assert client.post("/api/v1/web/generate-link-token", headers=headers("telegram_disconnected")).status_code == 200
    assert client.delete("/api/v1/web/unlink-telegram", headers=headers("telegram_connected")).status_code == 200


@pytest.mark.parametrize(
    ("persona", "expected"),
    (("telegram_disconnected", "idle"), ("telegram_pending", "pending_confirmation"), ("telegram_linked", "linked"), ("telegram_expired", "expired")),
)
def test_telegram_link_status_harness_contract(client: TestClient, persona: str, expected: str) -> None:
    response = client.get("/api/v1/web/telegram-link-status", headers=headers(persona))
    assert response.status_code == 200
    assert response.json()["status"] == expected
    if expected == "pending_confirmation":
        assert response.json()["expires_in"] == 540 and response.json()["attempts_remaining"] == 3


@pytest.mark.parametrize(
    ("persona", "status"),
    (("telegram_pending", 200), ("telegram_confirm_invalid", 400), ("telegram_confirm_missing", 404), ("telegram_confirm_conflict", 409), ("telegram_confirm_failure", 500)),
)
def test_telegram_confirm_harness_is_safe_and_does_not_record_code(client: TestClient, persona: str, status: int) -> None:
    client.post("/__e2e__/reset")
    response = client.post("/api/v1/web/confirm-telegram-link", headers=headers(persona), json={"code": "123456"})
    assert response.status_code == status
    records = client.get("/__e2e__/requests").json()
    assert records["count"] == 1 and "123456" not in str(records)


def test_telegram_cancel_harness_accounting_and_failure(client: TestClient) -> None:
    client.post("/__e2e__/reset")
    assert client.delete("/api/v1/web/cancel-telegram-link", headers=headers("telegram_pending")).status_code == 200
    assert client.delete("/api/v1/web/cancel-telegram-link", headers=headers("telegram_cancel_failure")).status_code == 500
    records = client.get("/__e2e__/requests").json()
    assert records["count"] == 2 and all(record["path"] == "/api/v1/web/cancel-telegram-link" for record in records["requests"])


def test_chat_limit_contract_uses_production_response_model(client: TestClient) -> None:
    request_headers = headers("chat_limit")
    quota = ChatQuotaState.model_validate(client.get("/api/v1/web/chat/state", headers=request_headers).json())
    response = client.post("/api/v1/web/chat", headers=request_headers, json={"message": "Hello", "history": []})
    assert quota.messages_left == 0 and quota.can_send is False
    assert response.status_code == 402
    assert ChatQuotaState.model_validate(response.json()).code == "limit_reached"


@pytest.mark.parametrize("persona,status", [(f"http_{status}", status) for status in (400, 401, 402, 403, 404, 409, 422, 429, 500, 502, 503)])
def test_error_personas_have_safe_envelope_and_request_id(client: TestClient, persona: str, status: int) -> None:
    response = client.get("/api/v1/web/me", headers=headers(persona))
    body = response.json()
    assert response.status_code == status
    assert body == {"detail": "e2e_forced_error", "code": persona}
    assert response.headers["x-request-id"].startswith("e2e-")
    assert "traceback" not in response.text.lower() and "secret" not in response.text.lower()


def test_loading_slow_timeout_and_offline_are_controlled(client: TestClient) -> None:
    with ThreadPoolExecutor(max_workers=1) as executor:
        loading = executor.submit(client.get, "/api/v1/web/me", headers=headers("loading"))
        assert client.post("/__e2e__/release").json() == {"ok": True}
        assert loading.result(timeout=2).status_code == 200
        timeout = executor.submit(client.get, "/api/v1/web/me", headers=headers("timeout"))
        assert client.post("/__e2e__/release").json() == {"ok": True}
        assert timeout.result(timeout=2).status_code == 504
    assert client.get("/api/v1/web/me", headers=headers("slow")).status_code == 200
    assert client.get("/__e2e__/state", headers=headers("offline")).json()["offline"] is True


def test_action_accounting_is_sanitized_and_resettable(client: TestClient) -> None:
    request_headers = headers("free")
    assert client.post("/__e2e__/reset").status_code == 200
    actions = [
        ("post", "/api/v1/web/logout", None),
        ("delete", "/api/v1/web/account", None),
        ("delete", "/api/v1/web/unlink-telegram", None),
        ("patch", "/api/v1/web/notifications", {"key": "news", "enabled": True}),
        ("post", "/api/v1/web/generate-link-token", None),
        ("post", "/api/v1/web/subscribe", {"promo_code": "SECRET-DO-NOT-LOG"}),
        ("post", "/api/v1/web/create-payment", {"email": "private@example.test"}),
        ("post", "/api/v1/web/chat", {"message": "private chat text", "history": []}),
        ("post", "/api/v1/tarot/spread", {"spread_type": "mini", "question": "private question"}),
    ]
    for method, path, payload in actions:
        response = client.request(method, path, headers=request_headers, json=payload)
        assert response.status_code == 200
    records = client.get("/__e2e__/requests").json()
    assert records["count"] == len(actions)
    assert [record["order"] for record in records["requests"]] == list(range(1, len(actions) + 1))
    assert all(record["payload"].get("keys") is not None for record in records["requests"])
    assert "private" not in str(records).lower() and "secret" not in str(records).lower()
    assert client.post("/__e2e__/reset").status_code == 200
    assert client.get("/__e2e__/requests").json()["count"] == 0


def test_destructive_actions_do_not_change_other_personas(client: TestClient) -> None:
    assert client.delete("/api/v1/web/account", headers=headers("free")).status_code == 200
    premium = UserProfileResponse.model_validate(client.get("/api/v1/web/me", headers=headers("premium")).json())
    free = UserProfileResponse.model_validate(client.get("/api/v1/web/me", headers=headers("free")).json())
    assert premium.has_tarot is True and free.subscription_status == "free"


def test_fake_chat_payment_and_tarot_responses_validate_without_external_providers(client: TestClient) -> None:
    request_headers = headers("free")
    chat = client.post("/api/v1/web/chat", headers=request_headers, json={"message": "Hello", "history": []})
    payment = client.post("/api/v1/web/subscribe", headers=request_headers, json={})
    spread = client.post("/api/v1/tarot/spread", headers=request_headers, json={"spread_type": "mini"})
    assert ChatResponse.model_validate(chat.json()).reply == "Deterministic E2E reply."
    assert payment.json()["payment_url"].startswith("https://payments.invalid/")
    assert SpreadResponse.model_validate(spread.json()).spread_type == "mini"
