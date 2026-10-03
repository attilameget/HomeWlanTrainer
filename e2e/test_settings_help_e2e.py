"""Settings help: Record session with Garmin opens in a dialog."""

from __future__ import annotations

from playwright.sync_api import Page, expect

from e2e.helpers import wait_for_home


def test_garmin_record_help_dialog(page: Page) -> None:
    wait_for_home(page)
    page.locator('[data-nav="settings"]').click()
    expect(page.locator("#view-settings")).to_be_visible(timeout=10_000)

    expect(page.locator("#help-garmin-heading")).to_have_text(
        "Record session with Garmin"
    )
    expect(page.locator("#help-dialog")).to_be_hidden()

    page.locator("#btn-help-garmin-record").click()
    dialog = page.locator("#help-dialog")
    expect(dialog).to_be_visible()
    expect(page.locator("#help-dialog-title")).to_have_text(
        "Record session with Garmin"
    )
    expect(dialog).to_contain_text("ANT+")
    expect(dialog).to_contain_text("Indoor Trainer")
    expect(dialog).to_contain_text("Every second")

    page.locator("#btn-help-dialog-close").click()
    expect(dialog).to_be_hidden()
