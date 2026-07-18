"""Real-page Playwright regression tests for Tarot production dialogs."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator

import pytest
from playwright.sync_api import Page, sync_playwright


URL = "http://127.0.0.1:4174/app/tarot.html?e2e=1"
SHEETS = ("#card-sheet", "#topic-sheet", "#pw-sheet", "#spread-sheet")


@pytest.fixture(scope="module")
def server() -> Iterator[None]:
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "tests.e2e_harness:create_e2e_harness",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            "4174",
        ],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=os.environ | {"APP_ENV": "test"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(40):
        try:
            urllib.request.urlopen(URL, timeout=0.25)
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
def page(server: None) -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            service_workers="block",
            extra_http_headers={"X-NURA-E2E-Persona": "telegram_connected"},
        )
        context.route("https://**/*", lambda route: route.abort())
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(URL, wait_until="domcontentloaded")
        yield page
        assert not errors
        context.close()
        browser.close()


def assert_open(page: Page, selector: str) -> None:
    dialog = page.locator(selector)
    dialog.wait_for(state="visible")
    assert dialog.get_attribute("role") == "dialog"
    assert dialog.get_attribute("aria-modal") == "true"
    assert dialog.get_attribute("aria-labelledby")
    assert dialog.get_attribute("aria-hidden") == "false"
    assert not dialog.evaluate("element => element.hidden")
    page.wait_for_function(
        "dialog => dialog.contains(document.activeElement)", arg=dialog.element_handle()
    )
    assert page.evaluate("document.body.style.overflow") == "hidden"


def assert_closed(page: Page, selector: str) -> None:
    dialog = page.locator(selector)
    dialog.wait_for(state="hidden")
    state = dialog.evaluate(
        """element => {
            const style = getComputedStyle(element);
            const box = element.getBoundingClientRect();
            return {
                ariaHidden: element.getAttribute('aria-hidden'),
                hidden: element.hidden,
                className: element.className,
                display: style.display,
                visibility: style.visibility,
                opacity: style.opacity,
                pointerEvents: style.pointerEvents,
                width: box.width,
                height: box.height,
                containsFocus: element.contains(document.activeElement),
            };
        }"""
    )
    assert state == {
        "ariaHidden": "true",
        "hidden": True,
        "className": "sheet tarot-sheet"
        if selector != "#spread-sheet"
        else "sheet tarot-sheet tarot-spread-sheet",
        "display": "none",
        "visibility": "visible",
        "opacity": "1",
        "pointerEvents": "none",
        "width": 0,
        "height": 0,
        "containsFocus": False,
    }
    assert not dialog.is_visible()


def wait_for_tarot_ready(page: Page) -> None:
    page.locator("#daily-open").wait_for(state="attached")
    page.locator("#daily-open").wait_for(state="visible")
    page.wait_for_function("() => !document.querySelector('#daily-open').disabled")
    page.wait_for_function("() => !document.querySelector('#p-mini').disabled")


def test_card_detail_escapes_closes_on_backdrop_and_reopens(page: Page) -> None:
    wait_for_tarot_ready(page)
    trigger = page.locator("#daily-open")
    trigger.click()
    assert_open(page, "#card-sheet")

    page.keyboard.press("Escape")
    assert_closed(page, "#card-sheet")
    assert trigger.evaluate("element => document.activeElement === element")

    trigger.click()
    assert_open(page, "#card-sheet")
    page.mouse.click(10, 10)
    assert_closed(page, "#card-sheet")


def test_topic_question_closes_and_can_reopen(page: Page) -> None:
    wait_for_tarot_ready(page)
    trigger = page.locator("#p-mini")
    trigger.click()
    assert_open(page, "#topic-sheet")
    page.keyboard.press("Escape")
    assert_closed(page, "#topic-sheet")
    assert trigger.evaluate("element => document.activeElement === element")

    trigger.click()
    assert_open(page, "#topic-sheet")
    page.locator("#topic-sheet .tarot-close").click()
    assert_closed(page, "#topic-sheet")


def test_paywall_close_and_checkout_request_is_not_duplicated(page: Page) -> None:
    wait_for_tarot_ready(page)
    page.locator("#p-weekly").click()
    assert_open(page, "#pw-sheet")
    page.locator("#pw-sheet .tarot-close").click()
    assert_closed(page, "#pw-sheet")

    requests = 0

    def checkout(route: object) -> None:
        nonlocal requests
        requests += 1
        route.fulfill(status=200, content_type="application/json", body='{"payment_url":""}')

    page.route("**/api/v1/web/subscribe", checkout)
    page.locator("#p-weekly").click()
    assert_open(page, "#pw-sheet")
    page.locator("#pw-subscribe-btn").dblclick()
    page.wait_for_function("() => !document.querySelector('#pw-subscribe-btn').disabled")
    assert requests == 1
    page.locator("#pw-sheet .tarot-close").click()
    assert_closed(page, "#pw-sheet")


def test_spread_result_and_dialog_stack_keep_scroll_lock(page: Page) -> None:
    wait_for_tarot_ready(page)
    page.locator("#p-mini").click()
    assert_open(page, "#topic-sheet")
    page.locator("#topic-input").fill("Как двигаться дальше?")
    page.locator("#topic-form button[type='submit']").click()
    assert_closed(page, "#topic-sheet")
    assert_open(page, "#spread-sheet")

    page.evaluate("window.openPaywall('Premium')")
    assert_open(page, "#pw-sheet")
    page.keyboard.press("Escape")
    assert_closed(page, "#pw-sheet")
    assert page.evaluate("document.body.style.overflow") == "hidden"

    page.locator("#spread-sheet .tarot-close").click()
    assert_closed(page, "#spread-sheet")
    assert page.evaluate("document.body.style.overflow") == ""

    for selector in SHEETS:
        assert_closed(page, selector)
