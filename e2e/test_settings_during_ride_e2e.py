"""Settings stays open during an active ride; Back to ride returns to ride."""

from __future__ import annotations

import json
import re
import time

from playwright.sync_api import Page, expect

from e2e.helpers import (
    expect_trainer_chip_connected,
    wait_for_home,
    wait_for_ride,
)


def test_settings_stays_open_during_ride(page: Page, e2e_base_url: str) -> None:
    page.request.post(
        f"{e2e_base_url}/api/trainer/mode",
        data='{"mode":"simulated"}',
        headers={"Content-Type": "application/json"},
    )
    page.request.post(
        f"{e2e_base_url}/api/emulator/cadence",
        data=json.dumps({"rpm": 85}),
        headers={"Content-Type": "application/json"},
    )
    page.reload(wait_until="domcontentloaded")
    wait_for_home(page)
    expect_trainer_chip_connected(page, emulator=True)

    page.locator("#manual-watts").fill("110")
    page.locator("#btn-manual-start").click()
    wait_for_ride(page)

    page.locator('[data-nav="settings"]').first.click()
    expect(page.locator("#view-settings")).to_be_visible(timeout=10_000)
    expect(page.locator("#view-settings")).not_to_have_class(re.compile(r"\bhidden\b"))
    expect(page.locator("#btn-settings-back")).to_have_text("← Back to ride")

    # Live ticks must not yank the user back to the ride view
    time.sleep(1.5)
    expect(page.locator("#view-settings")).to_be_visible()
    expect(page.locator("#view-ride")).to_have_class(re.compile(r"\bhidden\b"))

    page.locator("#btn-settings-back").click()
    wait_for_ride(page)

    page.request.post(
        f"{e2e_base_url}/api/session/command",
        data=json.dumps({"command": "stop"}),
        headers={"Content-Type": "application/json"},
    )
