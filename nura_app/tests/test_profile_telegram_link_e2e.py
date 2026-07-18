from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from tests.e2e_harness import PERSONA_HEADER


BASE_URL = "http://127.0.0.1:4199"


@pytest.fixture(scope="module")
def e2e_server() -> Iterator[None]:
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.e2e_harness:create_e2e_harness", "--factory", "--host", "127.0.0.1", "--port", "4199"],
        cwd=os.path.dirname(os.path.dirname(__file__)), env=os.environ | {"APP_ENV": "test"}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(40):
        try:
            urllib.request.urlopen(f"{BASE_URL}/app/profile.html?e2e=1", timeout=0.25)
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
def browser(e2e_server: None) -> Iterator[Browser]:
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()


def new_page(browser: Browser, persona: str) -> tuple[BrowserContext, Page, list[str]]:
    context = browser.new_context(service_workers="block", viewport={"width": 390, "height": 844}, extra_http_headers={PERSONA_HEADER: persona})
    context.route("https://**/*", lambda route: route.abort())
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: errors.append(message.text)
        if message.type == "error" and not any(f"status of {status}" in message.text for status in (400, 404, 409, 500))
        else None,
    )
    page.goto(f"{BASE_URL}/app/profile.html?e2e=1", wait_until="domcontentloaded")
    page.locator("#profile-account").wait_for(state="visible")
    return context, page, errors


def test_connect_opens_once_and_shows_accessible_confirmation(browser: Browser) -> None:
    context, page, errors = new_page(browser, "telegram_disconnected")
    opened: list[str] = []
    page.evaluate("() => { window.open = (url) => { window.__e2eOpened = (window.__e2eOpened || 0) + 1; window.__e2eUrl = url; }; }")
    try:
        page.locator("#tg-link-status").dblclick()
        page.locator("#telegram-confirmation").wait_for(state="visible")
        assert page.evaluate("() => window.__e2eOpened") == 1
        assert page.locator("#telegram-confirmation-code").evaluate("el => el === document.activeElement")
        code = page.locator("#telegram-confirmation-code")
        code.evaluate("el => { el.value = '１２３４５６'; el.dispatchEvent(new Event('input', {bubbles: true})); }")
        assert code.input_value() == "" and page.locator("#telegram-confirmation-submit").is_disabled()
        code.fill("123456")
        assert page.locator("#telegram-confirmation-submit").is_enabled()
        assert page.locator("#telegram-confirmation-open").is_visible()
        assert page.locator("#telegram-confirmation-cancel").is_visible()
        assert page.locator("#telegram-confirmation").evaluate("el => el.scrollWidth <= el.clientWidth")
        assert not errors
    finally:
        context.close()


@pytest.mark.parametrize(
    ("persona", "expected"),
    (("telegram_pending", "Осталось попыток: 3."), ("telegram_expired", "Код истёк"), ("telegram_linked", "Отключить")),
)
def test_status_is_restored_safely_after_load(browser: Browser, persona: str, expected: str) -> None:
    context, page, errors = new_page(browser, persona)
    try:
        if persona == "telegram_pending":
            confirmation = page.locator("#telegram-confirmation")
            confirmation.wait_for(state="visible")
            assert expected in page.locator("#telegram-confirmation-meta").inner_text()
        else:
            assert expected in page.locator("#tg-link-container").inner_text() or expected in page.locator("#account-action-status").inner_text()
        assert not errors
    finally:
        context.close()


@pytest.mark.parametrize(
    ("persona", "message"),
    (("telegram_confirm_invalid", "Проверь код"), ("telegram_confirm_missing", "Код истёк"), ("telegram_confirm_conflict", "Этот Telegram уже связан"), ("telegram_confirm_failure", "Не удалось подтвердить")),
)
def test_confirmation_outcomes_are_safe_and_retryable(browser: Browser, persona: str, message: str) -> None:
    context, page, errors = new_page(browser, persona)
    try:
        page.locator("#tg-link-status").click()
        code = page.locator("#telegram-confirmation-code")
        code.fill("123456")
        page.locator("#telegram-confirmation-submit").dblclick()
        page.get_by_text(message, exact=False).wait_for(state="visible")
        if persona in {"telegram_confirm_invalid", "telegram_confirm_failure"}:
            assert code.input_value() == "123456" and page.locator("#telegram-confirmation-submit").is_enabled()
        else:
            assert page.locator("#telegram-confirmation").count() == 0
        assert not errors
    finally:
        context.close()


def test_enter_cancel_and_request_accounting(browser: Browser) -> None:
    context, page, errors = new_page(browser, "telegram_pending")
    try:
        page.request.post(f"{BASE_URL}/__e2e__/reset")
        code = page.locator("#telegram-confirmation-code")
        code.fill("123456")
        code.press("Enter")
        page.locator("#tg-linked-item").wait_for(state="visible")
        records = page.request.get(f"{BASE_URL}/__e2e__/requests").json()
        assert records["count"] == 1 and "123456" not in str(records)
    finally:
        context.close()

    context, page, errors = new_page(browser, "telegram_pending")
    try:
        page.request.post(f"{BASE_URL}/__e2e__/reset")
        code = page.locator("#telegram-confirmation-code")
        code.fill("123456")
        page.locator("#telegram-confirmation-cancel").dblclick()
        page.locator("#tg-link-item").wait_for(state="visible")
        records = page.request.get(f"{BASE_URL}/__e2e__/requests").json()
        assert records["count"] == 1 and records["requests"][0]["path"] == "/api/v1/web/cancel-telegram-link"
        assert code.count() == 0 and not errors
    finally:
        context.close()
