"""Settings backup writes a timestamped file and restore puts FTP back."""

from __future__ import annotations

from playwright.sync_api import Page, expect

from e2e.helpers import wait_for_home


def _save_settings(page: Page) -> None:
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#btn-save").click()


def test_settings_backup_and_restore(page: Page) -> None:
    wait_for_home(page)
    page.locator('[data-nav="settings"]').click()
    expect(page.locator("#view-settings")).to_be_visible(timeout=10_000)
    expect(page.locator("#backup-settings-heading")).to_have_text("Backup")
    help_panel = page.locator("#backup-help")
    expect(help_panel).to_be_visible()
    assert help_panel.evaluate("el => el.open") is False
    help_panel.locator("summary").click()
    assert help_panel.evaluate("el => el.open") is True
    expect(help_panel.locator(".backup-help-body")).to_be_visible()
    expect(help_panel).to_contain_text("Tap Backup")
    expect(help_panel).to_contain_text("Choose a file in the list, then tap Restore")
    expect(help_panel).to_contain_text("Claude API key")
    expect(page.locator("#btn-backup-reveal")).to_be_visible()

    ftp = page.locator("#set-ftp")
    ftp.fill("222")
    _save_settings(page)
    expect(ftp).to_have_value("222", timeout=10_000)

    page.locator("#btn-backup").click()
    expect(page.locator("#backup-msg")).to_have_text("Backup saved.", timeout=10_000)
    selected = page.locator("#backup-select")
    expect(selected.locator("option:checked")).not_to_have_text("No backups yet")
    backup_id = selected.input_value()
    assert backup_id.startswith("steadygrind-backup-")

    ftp.fill("180")
    _save_settings(page)
    expect(ftp).to_have_value("180", timeout=10_000)

    page.locator("#btn-backup-restore").click()
    expect(page.locator("#backup-msg")).to_have_text("Backup restored.", timeout=10_000)
    expect(ftp).to_have_value("222")
