"""Playwright E2E coverage for the production iOS install dialogs."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator

import pytest
from playwright.sync_api import Page, sync_playwright


BASE_URL = "http://127.0.0.1:4174"


@pytest.fixture(scope="module")
def e2e_server() -> Iterator[None]:
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.e2e_harness:create_e2e_harness", "--factory", "--host", "127.0.0.1", "--port", "4174"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=os.environ | {"APP_ENV": "test"}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(40):
        try:
            urllib.request.urlopen(f"{BASE_URL}/app/index.html", timeout=0.25)
            break
        except OSError:
            time.sleep(0.1)
    else:
        process.terminate()
        raise RuntimeError("E2E harness did not start")
    yield
    process.terminate()
    process.wait(timeout=5)


@pytest.fixture(params=["index.html", "tarot.html"])
def page(e2e_server: None, request: pytest.FixtureRequest) -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(service_workers="block", extra_http_headers={"X-NURA-E2E-Persona": "telegram_connected"})
        context.route("https://**/*", lambda route: route.abort())
        page = context.new_page()
        errors: list[str] = []
        console_errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.goto(f"{BASE_URL}/app/{request.param}?e2e=1", wait_until="domcontentloaded")
        page.locator("#pwa-ios-modal").wait_for(state="hidden")
        yield page
        assert not errors
        assert not console_errors
        context.close()
        browser.close()


def _open(page: Page, legacy: bool = False) -> None:
    page.evaluate("window.showIOSInstallModal()" if legacy else "window.NURA_PWA.showIOSInstallModal()")
    page.locator("#pwa-ios-modal").wait_for(state="visible")
    page.wait_for_function("() => document.querySelector('#pwa-ios-modal').contains(document.activeElement)")


def _assert_open(page: Page) -> None:
    backdrop = page.locator("#pwa-ios-modal")
    card = backdrop.locator(":scope > div")
    assert card.get_attribute("role") == "dialog"
    assert card.get_attribute("aria-modal") == "true"
    assert page.evaluate("() => !!document.getElementById(document.querySelector('#pwa-ios-modal > div').getAttribute('aria-labelledby'))")
    assert page.evaluate("() => !!document.getElementById(document.querySelector('#pwa-ios-modal > div').getAttribute('aria-describedby'))")
    assert page.evaluate("document.body.style.overflow") == "hidden"


def _focus_trigger(page: Page) -> None:
    page.locator("#themeToggle").focus()
    assert page.locator("#themeToggle").evaluate("element => element === document.activeElement")


def _assert_closed(page: Page, trigger: str | None = None, fallback: bool = False) -> None:
    modal = page.locator("#pwa-ios-modal")
    modal.wait_for(state="hidden")
    assert not modal.evaluate("element => element.contains(document.activeElement)")
    assert page.evaluate("document.body.style.overflow") == ""
    assert page.evaluate("!document.body.hasAttribute('tabindex')")
    if trigger:
        assert page.locator(trigger).evaluate("element => element === document.activeElement")
    if fallback:
        assert page.evaluate("document.activeElement === document.body")


def test_ios_install_dialog_keyboard_focus_scroll_and_reopen(page: Page) -> None:
    _focus_trigger(page)
    _open(page)
    _assert_open(page)
    page.keyboard.press("Shift+Tab")
    assert page.locator("#pwa-ios-modal-cancel").evaluate("element => element === document.activeElement")
    page.keyboard.press("Tab")
    assert page.locator("#pwa-ios-modal-close").evaluate("element => element === document.activeElement")
    page.keyboard.press("Escape")
    _assert_closed(page, "#themeToggle")
    _focus_trigger(page)
    _open(page, legacy=True)
    page.locator("#pwa-ios-modal-close").click()
    _assert_closed(page, "#themeToggle")


def test_ios_install_dialog_backdrop_and_controls(page: Page) -> None:
    _focus_trigger(page)
    _open(page)
    page.locator("#pwa-ios-modal > div").click()
    assert page.locator("#pwa-ios-modal").is_visible()
    page.locator("#pwa-ios-modal").dispatch_event("click")
    _assert_closed(page, "#themeToggle")
    _focus_trigger(page)
    _open(page)
    page.locator("#pwa-ios-modal-cancel").click()
    _assert_closed(page, "#themeToggle")


@pytest.mark.parametrize("invalidation", ("body", "disabled", "hidden", "detached"))
def test_ios_install_dialog_invalid_trigger_uses_safe_fallback(page: Page, invalidation: str) -> None:
    if invalidation == "body":
        page.evaluate("document.activeElement.blur()")
        assert page.evaluate("document.activeElement === document.body")
    else:
        _focus_trigger(page)
    _open(page)
    if invalidation == "disabled":
        page.evaluate("document.getElementById('themeToggle').disabled = true")
    elif invalidation == "hidden":
        page.evaluate("document.getElementById('themeToggle').hidden = true")
    elif invalidation == "detached":
        page.evaluate("document.getElementById('themeToggle').remove()")
    page.keyboard.press("Escape")
    _assert_closed(page, fallback=True)


def test_tarot_ios_dialog_stacks_with_existing_dialog(e2e_server: None) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(service_workers="block", extra_http_headers={"X-NURA-E2E-Persona": "telegram_connected"})
        context.route("https://**/*", lambda route: route.abort())
        page = context.new_page()
        page.goto(f"{BASE_URL}/app/tarot.html?e2e=1", wait_until="domcontentloaded")
        page.evaluate("window.openPaywall('Тест')")
        page.locator("#pw-sheet").wait_for(state="visible")
        page.evaluate("window.NURA_PWA.showIOSInstallModal()")
        page.locator("#pwa-ios-modal").wait_for(state="visible")
        page.keyboard.press("Escape")
        page.locator("#pwa-ios-modal").wait_for(state="hidden")
        assert page.locator("#pw-sheet").is_visible()
        assert page.evaluate("document.body.style.overflow") == "hidden"
        assert page.locator("#pw-sheet").evaluate("element => element.contains(document.activeElement)")
        page.evaluate("window.closePaywall()")
        assert page.evaluate("document.body.style.overflow") == ""
        context.close()
        browser.close()
