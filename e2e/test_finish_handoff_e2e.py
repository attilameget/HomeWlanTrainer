"""Skip/natural finish must leave the ride screen (no zombie frozen ride UI)."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from e2e.helpers import (
    expect_trainer_chip_connected,
    wait_for_home,
    wait_for_ride,
)


def test_skip_finish_shows_summary_and_returns_home(
    page: Page, e2e_base_url: str
) -> None:
    page.request.post(
        f"{e2e_base_url}/api/trainer/mode",
        data='{"mode":"simulated"}',
        headers={"Content-Type": "application/json"},
    )
    page.reload(wait_until="domcontentloaded")
    wait_for_home(page)
    expect_trainer_chip_connected(page, emulator=True)

    start = page.locator("#btn-manual-start")
    expect(start).to_be_enabled(timeout=10_000)
    page.locator("#manual-watts").fill("130")
    start.click()
    wait_for_ride(page)
    expect(page.locator("#chip-engine")).to_have_text("Riding", timeout=10_000)

    # Manual ERG is a single open stage — Skip finishes the session on the host.
    resp = page.request.post(
        f"{e2e_base_url}/api/session/command",
        data='{"command":"skip"}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.ok, resp.text()

    dialog = page.locator("#app-dialog")
    expect(dialog).to_be_visible(timeout=10_000)
    expect(dialog).not_to_have_class(re.compile(r"\bhidden\b"))
    expect(page.locator("#app-dialog-title")).to_have_text("Workout summary")
    page.locator("#app-dialog-confirm").click()
    wait_for_home(page)
    expect(page.locator("#view-ride")).to_have_class(re.compile(r"\bhidden\b"))
    expect(page.locator("#btn-manual-start")).to_be_enabled()
