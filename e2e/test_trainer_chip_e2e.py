"""Trainer status chip must be ok only when connected."""

from __future__ import annotations

import json
import re

from playwright.sync_api import Page, expect

from e2e.helpers import (
    expect_trainer_chip_connected,
    expect_trainer_chip_disconnected,
    wait_for_home,
)


def test_trainer_chip_green_only_when_connected(page: Page, e2e_base_url: str) -> None:
    page.request.post(
        f"{e2e_base_url}/api/trainer/mode",
        data=json.dumps({"mode": "simulated"}),
        headers={"Content-Type": "application/json"},
    )
    page.reload(wait_until="domcontentloaded")
    wait_for_home(page)

    # Emulator fixture starts connected → pastel green "Emulator connected"
    expect_trainer_chip_connected(page, emulator=True)
    expect(page.locator("#btn-manual-start")).to_be_enabled()
    page.locator("[data-nav=settings]").click()
    expect(page.locator("#view-settings")).to_be_visible()
    expect(page.locator("#discover-out")).to_have_class(re.compile(r"status-connected"))
    expect(page.locator("#garmin-status")).not_to_have_class(re.compile(r"status-connected"))
    page.locator("#btn-settings-back").click()
    wait_for_home(page)

    # Disconnect → must go bad / "off", never keep ok
    resp = page.request.post(f"{e2e_base_url}/api/trainer/disconnect")
    assert resp.ok, resp.text()
    body = resp.json()
    assert body.get("ok") is True

    page.reload(wait_until="domcontentloaded")
    wait_for_home(page)
    expect_trainer_chip_disconnected(page, emulator=True)
    expect(page.locator("#btn-manual-start")).to_be_disabled()
    page.locator("[data-nav=settings]").click()
    expect(page.locator("#discover-out")).not_to_have_class(re.compile(r"status-connected"))
    page.locator("#btn-settings-back").click()
    wait_for_home(page)

    # Re-enable Emulator connection via mode apply
    resp = page.request.post(
        f"{e2e_base_url}/api/trainer/mode",
        data=json.dumps({"mode": "simulated"}),
        headers={"Content-Type": "application/json"},
    )
    assert resp.ok, resp.text()
    assert resp.json().get("connected") is True

    page.reload(wait_until="domcontentloaded")
    wait_for_home(page)
    expect_trainer_chip_connected(page, emulator=True)
    expect(page.locator("#btn-manual-start")).to_be_enabled()
