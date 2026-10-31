"""Incline control defaults to 0% and can be adjusted on the ride screen."""

from __future__ import annotations

import json

from playwright.sync_api import Page, expect

from e2e.helpers import (
    expect_trainer_chip_connected,
    wait_for_home,
    wait_for_ride,
)


def test_settings_incline_defaults_to_zero(page: Page) -> None:
    wait_for_home(page)
    page.locator('[data-nav="settings"]').click()
    expect(page.locator("#view-settings")).to_be_visible(timeout=10_000)
    incline = page.locator("#set-incline")
    expect(incline).to_be_visible()
    expect(incline).to_have_value("0")


def test_ride_incline_buttons_adjust_grade(page: Page, e2e_base_url: str) -> None:
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

    page.locator("#manual-watts").fill("100")
    page.locator("#btn-manual-start").click()
    wait_for_ride(page)

    expect(page.locator("#incline-controls .adjuster-label")).to_have_text("Incline")
    expect(page.locator("#ride-incline")).to_have_text("0%")
    page.locator("#btn-incline-plus").click()
    expect(page.locator("#ride-incline")).to_have_text("0.5%", timeout=5_000)
    page.locator("#btn-incline-minus").click()
    expect(page.locator("#ride-incline")).to_have_text("0%", timeout=5_000)

    page.request.post(
        f"{e2e_base_url}/api/session/command",
        data=json.dumps({"command": "stop"}),
        headers={"Content-Type": "application/json"},
    )
