"""Browser-level checks for the shared NURA dialog helper."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, sync_playwright


PWA_SCRIPT = Path(__file__).resolve().parents[2] / "frontend" / "pwa" / "app" / "nura-pwa.js"


@pytest.fixture
def page() -> Page:
    """Load the production shared PWA script in bundled Chromium."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content("<!doctype html><html><body></body></html>")
        page.add_script_tag(path=str(PWA_SCRIPT))
        yield page
        browser.close()


def test_activate_dialog_sets_modal_semantics(page: Page) -> None:
    page.evaluate(
        """() => {
            const backdrop = document.body.appendChild(document.createElement('div'));
            const card = backdrop.appendChild(document.createElement('section'));
            card.appendChild(document.createElement('button')).textContent = 'Continue';
            window.NURA.activateDialog(backdrop, card);
        }"""
    )

    assert page.locator("section").get_attribute("role") == "dialog"
    assert page.locator("section").get_attribute("aria-modal") == "true"


def test_activate_dialog_moves_initial_focus_inside_dialog(page: Page) -> None:
    page.evaluate(
        """() => {
            const trigger = document.body.appendChild(document.createElement('button'));
            trigger.textContent = 'Open';
            trigger.focus();
            const backdrop = document.body.appendChild(document.createElement('div'));
            const card = backdrop.appendChild(document.createElement('section'));
            const primary = card.appendChild(document.createElement('button'));
            primary.id = 'dialog-primary';
            primary.textContent = 'Continue';
            window.NURA.activateDialog(backdrop, card, primary);
        }"""
    )

    page.wait_for_timeout(10)
    assert page.evaluate("document.querySelector('section').contains(document.activeElement)")
    assert page.locator("#dialog-primary").evaluate("element => element === document.activeElement")


def test_escape_closes_a_dismissible_dialog(page: Page) -> None:
    page.evaluate(
        """() => {
            const backdrop = document.body.appendChild(document.createElement('div'));
            backdrop.id = 'dismissible-backdrop';
            const card = backdrop.appendChild(document.createElement('section'));
            card.appendChild(document.createElement('button')).textContent = 'Close';
            window.NURA.activateDialog(backdrop, card);
        }"""
    )

    page.keyboard.press("Escape")

    assert page.locator("#dismissible-backdrop").count() == 0


def test_tab_and_shift_tab_stay_within_dialog(page: Page) -> None:
    page.evaluate(
        """() => {
            const outside = document.body.appendChild(document.createElement('button'));
            outside.id = 'outside';
            outside.textContent = 'Outside';
            const backdrop = document.body.appendChild(document.createElement('div'));
            const card = backdrop.appendChild(document.createElement('section'));
            const first = card.appendChild(document.createElement('button'));
            first.id = 'first';
            first.textContent = 'First';
            const last = card.appendChild(document.createElement('button'));
            last.id = 'last';
            last.textContent = 'Last';
            window.NURA.activateDialog(backdrop, card, first);
        }"""
    )
    page.wait_for_timeout(10)

    page.keyboard.press("Shift+Tab")
    assert page.locator("#last").evaluate("element => element === document.activeElement")
    page.keyboard.press("Tab")
    assert page.locator("#first").evaluate("element => element === document.activeElement")
    assert not page.locator("#outside").evaluate("element => element === document.activeElement")


def test_escape_closes_only_top_dialog_and_restores_lower_focus(page: Page) -> None:
    page.evaluate(
        """() => {
            const lowerBackdrop = document.body.appendChild(document.createElement('div'));
            lowerBackdrop.id = 'lower-backdrop';
            const lowerCard = lowerBackdrop.appendChild(document.createElement('section'));
            const lowerButton = lowerCard.appendChild(document.createElement('button'));
            lowerButton.id = 'lower-button';
            lowerButton.textContent = 'Lower';
            window.NURA.activateDialog(lowerBackdrop, lowerCard, lowerButton);

            const topBackdrop = document.body.appendChild(document.createElement('div'));
            topBackdrop.id = 'top-backdrop';
            const topCard = topBackdrop.appendChild(document.createElement('section'));
            const topButton = topCard.appendChild(document.createElement('button'));
            topButton.textContent = 'Top';
            window.NURA.activateDialog(topBackdrop, topCard, topButton);
        }"""
    )
    page.wait_for_timeout(10)

    page.keyboard.press("Escape")

    assert page.locator("#top-backdrop").count() == 0
    assert page.locator("#lower-backdrop").count() == 1
    assert page.locator("#lower-button").evaluate("element => element === document.activeElement")


def test_escape_does_not_close_a_non_dismissible_dialog(page: Page) -> None:
    page.evaluate(
        """() => {
            const backdrop = document.body.appendChild(document.createElement('div'));
            backdrop.id = 'persistent-backdrop';
            const card = backdrop.appendChild(document.createElement('section'));
            card.appendChild(document.createElement('button')).textContent = 'Stay open';
            window.NURA.activateDialog(backdrop, card, null, null, {dismissible: false});
        }"""
    )

    page.keyboard.press("Escape")

    assert page.locator("#persistent-backdrop").count() == 1


def test_backdrop_click_closes_when_enabled(page: Page) -> None:
    page.evaluate(
        """() => {
            const backdrop = document.body.appendChild(document.createElement('div'));
            backdrop.id = 'clickable-backdrop';
            const card = backdrop.appendChild(document.createElement('section'));
            card.appendChild(document.createElement('button')).textContent = 'Close';
            window.NURA.activateDialog(backdrop, card, null, null, {backdropClose: true});
        }"""
    )

    page.locator("#clickable-backdrop").dispatch_event("click")

    assert page.locator("#clickable-backdrop").count() == 0


def test_backdrop_click_does_not_close_when_disabled(page: Page) -> None:
    page.evaluate(
        """() => {
            const backdrop = document.body.appendChild(document.createElement('div'));
            backdrop.id = 'static-backdrop';
            const card = backdrop.appendChild(document.createElement('section'));
            card.appendChild(document.createElement('button')).textContent = 'Stay open';
            window.NURA.activateDialog(backdrop, card, null, null, {backdropClose: false});
        }"""
    )

    page.locator("#static-backdrop").dispatch_event("click")

    assert page.locator("#static-backdrop").count() == 1


def test_dialog_without_focusable_elements_receives_focus(page: Page) -> None:
    page.evaluate(
        """() => {
            const backdrop = document.body.appendChild(document.createElement('div'));
            const card = backdrop.appendChild(document.createElement('section'));
            card.id = 'empty-dialog';
            card.textContent = 'A dialog without controls';
            window.NURA.activateDialog(backdrop, card);
        }"""
    )
    page.wait_for_timeout(10)

    assert page.locator("#empty-dialog").evaluate("element => element === document.activeElement")
    assert page.locator("#empty-dialog").get_attribute("tabindex") == "-1"


def test_closing_one_of_two_dialogs_keeps_body_scroll_locked(page: Page) -> None:
    page.evaluate(
        """() => {
            document.body.style.overflow = 'auto';
            const lowerBackdrop = document.body.appendChild(document.createElement('div'));
            const lowerCard = lowerBackdrop.appendChild(document.createElement('section'));
            lowerCard.appendChild(document.createElement('button')).textContent = 'Lower';
            window.NURA.activateDialog(lowerBackdrop, lowerCard);
            const topBackdrop = document.body.appendChild(document.createElement('div'));
            const topCard = topBackdrop.appendChild(document.createElement('section'));
            topCard.appendChild(document.createElement('button')).textContent = 'Top';
            window.closeTopDialog = window.NURA.activateDialog(topBackdrop, topCard);
        }"""
    )

    page.evaluate("window.closeTopDialog()")

    assert page.evaluate("document.body.style.overflow") == "hidden"


def test_closing_last_dialog_restores_original_body_overflow(page: Page) -> None:
    page.evaluate(
        """() => {
            document.body.style.overflow = 'scroll';
            const backdrop = document.body.appendChild(document.createElement('div'));
            const card = backdrop.appendChild(document.createElement('section'));
            card.appendChild(document.createElement('button')).textContent = 'Close';
            window.closeOnlyDialog = window.NURA.activateDialog(backdrop, card);
        }"""
    )

    page.evaluate("window.closeOnlyDialog()")

    assert page.evaluate("document.body.style.overflow") == "scroll"


def test_close_destroy_removes_dialog_from_stack_and_restores_scroll_lock(page: Page) -> None:
    page.evaluate(
        """() => {
            document.body.style.overflow = 'auto';
            const backdrop = document.body.appendChild(document.createElement('div'));
            backdrop.id = 'destroyed-backdrop';
            const card = backdrop.appendChild(document.createElement('section'));
            card.appendChild(document.createElement('button')).textContent = 'Destroy';
            window.destroyDialog = window.NURA.activateDialog(backdrop, card);
        }"""
    )

    page.evaluate("window.destroyDialog.destroy()")

    assert page.locator("#destroyed-backdrop").count() == 0
    assert page.evaluate("document.body.style.overflow") == "auto"


def test_close_does_not_restore_focus_to_removed_or_disabled_trigger(page: Page) -> None:
    page.evaluate(
        """() => {
            const removedTrigger = document.body.appendChild(document.createElement('button'));
            removedTrigger.id = 'removed-trigger';
            removedTrigger.focus();
            const removedBackdrop = document.body.appendChild(document.createElement('div'));
            const removedCard = removedBackdrop.appendChild(document.createElement('section'));
            removedCard.appendChild(document.createElement('button')).textContent = 'Close removed';
            const closeRemoved = window.NURA.activateDialog(removedBackdrop, removedCard);
            removedTrigger.remove();
            closeRemoved();

            const disabledTrigger = document.body.appendChild(document.createElement('button'));
            disabledTrigger.id = 'disabled-trigger';
            disabledTrigger.focus();
            const disabledBackdrop = document.body.appendChild(document.createElement('div'));
            const disabledCard = disabledBackdrop.appendChild(document.createElement('section'));
            disabledCard.appendChild(document.createElement('button')).textContent = 'Close disabled';
            const closeDisabled = window.NURA.activateDialog(disabledBackdrop, disabledCard);
            disabledTrigger.disabled = true;
            closeDisabled();
        }"""
    )

    assert not page.locator("#disabled-trigger").evaluate("element => element === document.activeElement")
    assert page.evaluate("document.activeElement === document.body")
