"""Ride chart: power-only on Manual; structure+power overlay on demo workout."""

from __future__ import annotations

import json

from playwright.sync_api import Page, expect

from e2e.helpers import (
    expect_trainer_chip_connected,
    wait_for_home,
    wait_for_ride,
)


def test_structure_overlay_hidden_on_manual(page: Page, e2e_base_url: str) -> None:
    page.request.post(
        f"{e2e_base_url}/api/trainer/mode",
        data='{"mode":"simulated"}',
        headers={"Content-Type": "application/json"},
    )
    page.reload(wait_until="domcontentloaded")
    wait_for_home(page)
    expect_trainer_chip_connected(page, emulator=True)

    page.locator("#manual-watts").fill("100")
    page.locator("#btn-manual-start").click()
    wait_for_ride(page)

    panel = page.locator("#ride-chart-panel")
    expect(panel).to_be_visible()
    expect(panel).to_have_attribute("data-mode", "power")
    expect(page.locator("#ride-chart")).to_be_visible()
    expect(page.locator("#ride-chart-title")).to_contain_text("Power")

    page.request.post(
        f"{e2e_base_url}/api/session/command",
        data=json.dumps({"command": "stop"}),
        headers={"Content-Type": "application/json"},
    )


def test_structure_power_overlay_on_demo_workout(page: Page, e2e_base_url: str) -> None:
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

    res = page.request.post(
        f"{e2e_base_url}/api/session",
        data=json.dumps({"workoutId": "demo"}),
        headers={"Content-Type": "application/json"},
    )
    assert res.ok, res.text()
    wait_for_ride(page)

    panel = page.locator("#ride-chart-panel")
    expect(panel).to_be_visible(timeout=10_000)
    expect(panel).to_have_attribute("data-mode", "overlay", timeout=10_000)
    expect(page.locator("#ride-chart")).to_be_visible()
    expect(page.locator("#ride-chart-title")).to_contain_text("Structure + power")
    expect(page.locator("#ride-chart-axis-mid")).to_have_text("now")

    page.request.post(
        f"{e2e_base_url}/api/session/command",
        data=json.dumps({"command": "stop"}),
        headers={"Content-Type": "application/json"},
    )
