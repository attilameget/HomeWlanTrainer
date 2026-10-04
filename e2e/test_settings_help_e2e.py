"""Settings: Garmin login MFA field and Record-with-Garmin help dialog."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from e2e.helpers import wait_for_home


def test_garmin_login_mfa_field_starts_hidden(page: Page) -> None:
    wait_for_home(page)
    page.locator('[data-nav="settings"]').click()
    expect(page.locator("#view-settings")).to_be_visible(timeout=10_000)
    expect(page.locator("#btn-garmin-login")).to_be_visible()
    expect(page.locator("#garmin-mfa-wrap")).to_have_class(re.compile(r"\bhidden\b"))


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
