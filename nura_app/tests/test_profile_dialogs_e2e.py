"""Playwright E2E coverage for Profile confirmation dialogs."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator

import pytest
from playwright.sync_api import BrowserContext, Page, Route, sync_playwright


BASE_URL = "http://127.0.0.1:4174"


@pytest.fixture(scope="module")
def e2e_server() -> Iterator[None]:
    environment = os.environ | {"APP_ENV": "test"}
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.e2e_harness:create_e2e_harness", "--factory", "--host", "127.0.0.1", "--port", "4174"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(40):
        try:
            urllib.request.urlopen(f"{BASE_URL}/app/profile.html", timeout=0.25)
            break
        except OSError:
            time.sleep(0.1)
    else:
        process.terminate()
        raise RuntimeError("E2E harness did not start")
    yield
    process.terminate()
    process.wait(timeout=5)


@pytest.fixture
def page(e2e_server: None) -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context: BrowserContext = browser.new_context(
            service_workers="block",
            extra_http_headers={"X-NURA-E2E-Persona": "telegram_connected"},
        )
        context.route("https://**/*", lambda route: route.abort())
        page = context.new_page()
        errors: list[str] = []
        console_errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error" and "status of 500" not in message.text
            else None,
        )
        page.goto(f"{BASE_URL}/app/profile.html?e2e=1", wait_until="domcontentloaded")
        page.locator("#profile-account").wait_for(state="visible")
        yield page
        assert not errors
        assert not console_errors
        context.close()
        browser.close()


def _assert_dialog_open(page: Page, dialog_id: str) -> None:
    dialog = page.locator(dialog_id)
    dialog.wait_for(state="visible")
    card = dialog.locator("section")
    assert card.get_attribute("role") == "dialog"
    assert card.get_attribute("aria-modal") == "true"
    assert card.get_attribute("aria-label") or card.get_attribute("aria-labelledby")
    page.wait_for_function("dialog => dialog.contains(document.activeElement)", arg=dialog.element_handle())
    assert page.evaluate("document.body.style.overflow") == "hidden"


def _delayed_success(route: Route) -> None:
    route.fulfill(status=200, content_type="application/json", body="{}")


def test_logout_dialog_keyboard_cancel_focus_and_scroll_lock(page: Page) -> None:
    trigger = page.locator("#logout-btn")
    trigger.click()
    _assert_dialog_open(page, "#logout-dialog")
    page.keyboard.press("Shift+Tab")
    assert page.locator("#logout-dialog-confirm").evaluate("element => element === document.activeElement")
    page.keyboard.press("Tab")
    assert page.locator("#logout-dialog-cancel").evaluate("element => element === document.activeElement")
    page.keyboard.press("Escape")
    assert page.locator("#logout-dialog").is_hidden()
    assert trigger.evaluate("element => element === document.activeElement")
    assert page.evaluate("document.body.style.overflow") == ""


def test_logout_cancel_and_confirm_are_accounted_once(page: Page) -> None:
    calls: list[str] = []
    page.route("**/api/v1/web/logout", lambda route: (calls.append(route.request.url), _delayed_success(route)))
    page.locator("#logout-btn").click()
    page.locator("#logout-dialog-cancel").click()
    assert calls == []
    page.locator("#logout-btn").click()
    page.locator("#logout-dialog-confirm").dblclick()
    page.locator("#profile-guest").wait_for(state="visible")
    assert len(calls) == 1


def test_logout_error_keeps_dialog_retryable(page: Page) -> None:
    calls: list[str] = []
    page.route("**/api/v1/web/logout", lambda route: (calls.append(route.request.url), route.fulfill(status=500)))
    page.locator("#logout-btn").click()
    page.locator("#logout-dialog-confirm").click()
    page.locator("#logout-dialog-confirm").wait_for(state="visible")
    assert page.locator("#logout-dialog-confirm").is_enabled()
    assert len(calls) == 1


def test_unlink_dialog_cancel_escape_and_success_state(page: Page) -> None:
    calls: list[str] = []
    page.route("**/api/v1/web/unlink-telegram", lambda route: (calls.append(route.request.url), _delayed_success(route)))
    trigger = page.locator("#tg-link-status")
    trigger.click()
    _assert_dialog_open(page, "#unlink-dialog")
    page.keyboard.press("Escape")
    assert trigger.evaluate("element => element === document.activeElement")
    trigger.click()
    page.locator("#unlink-dialog-cancel").click()
    assert calls == []
    trigger.click()
    page.locator("#unlink-dialog-confirm").dblclick()
    page.locator("#tg-link-item").wait_for(state="visible")
    assert len(calls) == 1


def test_unlink_error_keeps_dialog_retryable(page: Page) -> None:
    page.route("**/api/v1/web/unlink-telegram", lambda route: route.fulfill(status=500))
    page.locator("#tg-link-status").click()
    page.locator("#unlink-dialog-confirm").click()
    page.wait_for_function("() => !document.getElementById('unlink-dialog-confirm').disabled")
    assert page.locator("#unlink-dialog").is_visible()


def test_delete_dialog_uses_safe_focus_and_cancels_without_request(page: Page) -> None:
    calls: list[str] = []
    page.route("**/api/v1/web/account", lambda route: (calls.append(route.request.url), _delayed_success(route)))
    page.locator("#delete-btn").click()
    _assert_dialog_open(page, "#delete-dialog")
    assert page.locator("#delete-dialog-cancel").evaluate("element => element === document.activeElement")
    page.locator("#delete-dialog-cancel").click()
    assert calls == []


def test_delete_confirm_is_single_disabled_and_does_not_restore_removed_trigger(page: Page) -> None:
    calls: list[str] = []
    page.route("**/api/v1/web/account", lambda route: (calls.append(route.request.url), _delayed_success(route)))
    page.locator("#delete-btn").click()
    confirm = page.locator("#delete-dialog-confirm")
    confirm.dblclick()
    assert confirm.is_disabled()
    page.locator("#profile-guest").wait_for(state="visible")
    assert len(calls) == 1
    assert page.evaluate("document.activeElement !== document.querySelector('#delete-btn')")


def test_delete_error_keeps_dialog_retryable_and_escape_restores_focus(page: Page) -> None:
    page.route("**/api/v1/web/account", lambda route: route.fulfill(status=500))
    trigger = page.locator("#delete-btn")
    trigger.click()
    page.locator("#delete-dialog-confirm").click()
    page.wait_for_function("() => !document.getElementById('delete-dialog-confirm').disabled")
    page.keyboard.press("Escape")
    assert trigger.evaluate("element => element === document.activeElement")
