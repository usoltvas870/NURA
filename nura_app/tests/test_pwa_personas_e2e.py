"""Chromium E2E smoke coverage for real PWA persona states."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, Route, sync_playwright


BASE = "http://127.0.0.1:4174/app"
PAGES = ("index.html", "tarot.html", "chat.html", "profile.html")
VIEWPORTS = ((360, 800), (390, 844), (430, 932), (1440, 900))


@pytest.fixture(scope="module")
def server() -> Iterator[None]:
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.e2e_harness:create_e2e_harness", "--factory", "--host", "127.0.0.1", "--port", "4174"],
        cwd=os.path.dirname(os.path.dirname(__file__)), env=os.environ | {"APP_ENV": "test"},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(40):
        try:
            urllib.request.urlopen(f"{BASE}/index.html?e2e=1", timeout=0.25)
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
def browser(server: None) -> Iterator[Browser]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


def new_page(browser: Browser, persona: str, viewport: tuple[int, int] = (390, 844)) -> tuple[BrowserContext, Page, list[str]]:
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, service_workers="block", extra_http_headers={"X-NURA-E2E-Persona": persona})
    context.route("https://**/*", lambda route: route.abort())
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    return context, page, errors


def open_page(page: Page, name: str) -> None:
    response = page.goto(f"{BASE}/{name}?e2e=1", wait_until="domcontentloaded")
    assert response and response.status == 200
    page.wait_for_function("document.readyState === 'interactive' || document.readyState === 'complete'")
    page.locator("header").wait_for(state="visible")
    page.locator("nav.tabbar").wait_for(state="visible")


def assert_no_unexpected_errors(errors: list[str]) -> None:
    assert not [error for error in errors if "Failed to load resource" not in error]


@pytest.mark.parametrize("viewport", VIEWPORTS)
@pytest.mark.parametrize("theme", ("light", "dark"))
def test_shell_matrix_real_pages(browser: Browser, viewport: tuple[int, int], theme: str) -> None:
    for name in PAGES:
        context, page, errors = new_page(browser, "free", viewport)
        try:
            open_page(page, name)
            if page.locator("html").get_attribute("data-theme") != theme:
                page.locator("#themeToggle").click()
            assert page.locator("html").get_attribute("data-theme") == theme
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert page.locator("nav.tabbar").evaluate("element => getComputedStyle(element).position") == "fixed"
            before = page.locator("nav.tabbar").bounding_box()
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            after = page.locator("nav.tabbar").bounding_box()
            assert before and after and abs(before["y"] - after["y"]) < 1
            page.reload(wait_until="domcontentloaded")
            assert page.locator("html").get_attribute("data-theme") == theme
            assert_no_unexpected_errors(errors)
        finally:
            context.close()


def test_tarot_guest_free_premium_expired_and_spread(browser: Browser) -> None:
    for persona, expected in (("guest", "guest"), ("free", "free"), ("premium", "subscriber"), ("expired", "free")):
        context, page, errors = new_page(browser, persona)
        try:
            open_page(page, "tarot.html")
            page.wait_for_function("() => document.body.dataset.access !== 'loading'")
            assert page.locator("body").get_attribute("data-access") == expected
            if persona == "premium":
                page.locator("#p-weekly").click()
                page.locator("#spread-sheet").wait_for(state="visible")
            if persona == "free":
                page.locator("#p-weekly").click()
                page.locator("#pw-sheet").wait_for(state="visible")
            assert_no_unexpected_errors(errors)
        finally:
            context.close()


def test_daily_card_deep_link_is_consumed_after_loading(browser: Browser) -> None:
    context, page, errors = new_page(browser, "free")
    try:
        response = page.goto(f"{BASE}/tarot.html?open=daily&e2e=1", wait_until="domcontentloaded")
        assert response and response.status == 200
        page.locator("#card-sheet").wait_for(state="visible")
        assert "open=" not in page.url
        page.reload(wait_until="domcontentloaded")
        page.locator("#card-sheet").wait_for(state="hidden")
        assert_no_unexpected_errors(errors)
    finally:
        context.close()


def test_daily_card_deep_link_preserves_other_url_parts_and_home_cta(browser: Browser) -> None:
    context, page, errors = new_page(browser, "free")
    try:
        open_page(page, "index.html")
        page.wait_for_function("() => !document.querySelector('#day-cta').disabled")
        page.locator("#day-cta").click()
        page.locator("#card-sheet").wait_for(state="visible")
        assert "open=" not in page.url

        response = page.goto(f"{BASE}/tarot.html?foo=bar&open=daily&e2e=1#test", wait_until="domcontentloaded")
        assert response and response.status == 200
        page.locator("#card-sheet").wait_for(state="visible")
        assert "foo=bar" in page.url and "open=" not in page.url and page.url.endswith("#test")
        assert_no_unexpected_errors(errors)
    finally:
        context.close()


def test_daily_card_invalid_or_failed_deep_link_does_not_open_sheet(browser: Browser) -> None:
    for persona, query in (("free", "open=other"), ("http_500", "open=daily")):
        context, page, errors = new_page(browser, persona)
        try:
            response = page.goto(f"{BASE}/tarot.html?{query}&e2e=1", wait_until="domcontentloaded")
            assert response and response.status == 200
            page.wait_for_function("() => document.body.dataset.access !== 'loading'")
            assert page.locator("#card-sheet").is_hidden()
            assert_no_unexpected_errors(errors)
        finally:
            context.close()


def test_chat_personas_keyboard_and_single_request(browser: Browser) -> None:
    context, page, errors = new_page(browser, "free")
    try:
        open_page(page, "chat.html")
        page.locator("#chat-input").wait_for(state="visible")
        page.wait_for_function("() => !document.querySelector('#chat-input').disabled")
        page.request.post("http://127.0.0.1:4174/__e2e__/reset")
        page.locator("#chat-input").fill("E2E message")
        page.locator("#chat-input").press("Shift+Enter")
        assert "\n" in page.locator("#chat-input").input_value()
        page.locator("#chat-input").press("Enter")
        page.locator("#conversation").wait_for(state="visible")
        records = page.request.get("http://127.0.0.1:4174/__e2e__/requests").json()
        assert records["count"] == 1 and records["requests"][0]["path"] == "/api/v1/web/chat"
        assert_no_unexpected_errors(errors)
    finally:
        context.close()

    for persona, selector in (("guest", "#guest-state"), ("chat_limit", "#limit-state"), ("premium", "#chat-input")):
        context, page, errors = new_page(browser, persona)
        try:
            open_page(page, "chat.html")
            page.locator(selector).wait_for(state="visible")
            assert_no_unexpected_errors(errors)
        finally:
            context.close()


def test_chat_exhausted_quota_preserves_history_and_banner(browser: Browser) -> None:
    context, page, errors = new_page(browser, "chat_limit")
    try:
        context.add_init_script("""
            localStorage.setItem('nura_chat_user_id', 'e2e-chat_limit');
            localStorage.setItem('nura_chat_log', JSON.stringify([
                {role: 'user', text: 'Первый вопрос', time: '10:00'},
                {role: 'nura', text: 'Ответ NURA', time: '10:01'}
            ]));
        """)
        open_page(page, "chat.html")
        page.locator("#conversation").wait_for(state="visible")
        assert page.locator("#conversation").inner_text().find("Ответ NURA") >= 0
        assert page.locator("#quota-banner").is_visible()
        assert page.locator("#limit-state").is_hidden()
        assert page.locator("#chat-input").is_disabled()
        assert page.locator("#send-btn").is_disabled()
        assert_no_unexpected_errors(errors)
    finally:
        context.close()


def test_chat_exhausted_empty_state_hides_banner(browser: Browser) -> None:
    context, page, errors = new_page(browser, "chat_limit")
    try:
        open_page(page, "chat.html")
        page.locator("#limit-state").wait_for(state="visible")
        assert page.locator("#quota-banner").is_hidden()
        assert page.locator("#chat-input").is_disabled()
        assert page.locator("#send-btn").is_disabled()
        assert_no_unexpected_errors(errors)
    finally:
        context.close()


def test_chat_final_send_shows_banner_after_response(browser: Browser) -> None:
    context, page, errors = new_page(browser, "free")
    try:
        request_count = 0

        def last_quota(route: Route) -> None:
            nonlocal request_count
            request_count += 1
            route.fulfill(
                json={
                    "reply": "Последний ответ NURA",
                    "quota": {
                        "access": "free",
                        "can_send": False,
                        "daily_limit": 10,
                        "used": 10,
                        "messages_left": 0,
                        "reset_at": "2026-07-19T00:00:00Z",
                        "timezone": "UTC",
                        "code": "limit_reached",
                    },
                }
            )

        page.route("**/api/v1/web/chat", last_quota)
        open_page(page, "chat.html")
        page.request.post("http://127.0.0.1:4174/__e2e__/reset")
        page.locator("#chat-input").fill("Последний вопрос")
        page.locator("#send-btn").click()
        page.locator("text=Последний ответ NURA").wait_for(state="visible")
        assert page.locator("#quota-banner").is_visible()
        assert page.locator("#limit-state").is_hidden()
        assert page.locator("#chat-input").is_disabled()
        assert page.locator("#send-btn").is_disabled()
        assert page.locator("text=Последний ответ NURA").count() == 1
        assert request_count == 1
        assert_no_unexpected_errors(errors)
    finally:
        context.close()


def test_chat_available_and_subscriber_hide_quota_banner(browser: Browser) -> None:
    for persona in ("free", "premium"):
        context, page, errors = new_page(browser, persona)
        try:
            open_page(page, "chat.html")
            page.locator("#chat-input").wait_for(state="visible")
            assert page.locator("#quota-banner").is_hidden()
            assert page.locator("#chat-input").is_enabled()
            assert_no_unexpected_errors(errors)
        finally:
            context.close()


def test_profile_personas_and_accounting(browser: Browser) -> None:
    for persona, selector in (("guest", "#profile-guest"), ("free", "#profile-account"), ("premium", "#profile-account"), ("expired", "#profile-account"), ("matrix_owner", "#matrix-open-btn"), ("report_owner", "#reports-list"), ("telegram_connected", "#tg-link-container"), ("telegram_disconnected", "#tg-link-container")):
        context, page, errors = new_page(browser, persona)
        try:
            open_page(page, "profile.html")
            page.locator(selector).wait_for(state="visible")
            if persona == "premium":
                assert page.locator("#subscription-date").is_visible()
            assert_no_unexpected_errors(errors)
        finally:
            context.close()


@pytest.mark.parametrize("persona", ("http_400", "http_401", "http_402", "http_403", "http_404", "http_409", "http_422", "http_429", "http_500", "http_502", "http_503"))
def test_http_personas_leave_real_profile_interactive(browser: Browser, persona: str) -> None:
    context, page, errors = new_page(browser, persona)
    try:
        open_page(page, "profile.html")
        page.locator("#profile-guest" if persona == "http_401" else "#profile-error").wait_for(state="visible")
        if persona != "http_401":
            assert page.locator("#profile-retry").is_enabled()
        assert "traceback" not in page.locator("body").inner_text().lower()
        assert_no_unexpected_errors(errors)
    finally:
        context.close()
