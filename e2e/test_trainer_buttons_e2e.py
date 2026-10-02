"""Real KICKR Discover/Connect/Disconnect buttons follow connection state."""

from __future__ import annotations

import json
import re

from playwright.sync_api import Page, expect

from e2e.helpers import (
    expect_trainer_chip_connected,
    wait_for_home,
)


def _open_settings(page: Page) -> None:
    page.locator('[data-nav="settings"]').click()
    expect(page.locator("#view-settings")).to_be_visible(timeout=10_000)
    expect(page.locator("#set-trainer-mode")).to_have_value("simulated", timeout=10_000)
    expect(page.locator("#btn-discover")).to_be_visible()


def test_real_trainer_buttons_follow_connection(page: Page, e2e_base_url: str) -> None:
    # Ensure Emulator baseline (other tests may leave Real mode)
    page.request.post(
        f"{e2e_base_url}/api/trainer/mode",
        data=json.dumps({"mode": "simulated"}),
        headers={"Content-Type": "application/json"},
    )
    page.reload(wait_until="domcontentloaded")
    wait_for_home(page)
    expect_trainer_chip_connected(page, emulator=True)

    _open_settings(page)

    # Emulator mode: Discover/Connect are DirCon-only → disabled; Disconnect on while connected
    expect(page.locator("#btn-discover")).to_be_disabled()
    expect(page.locator("#btn-connect")).to_be_disabled()
    expect(page.locator("#btn-disconnect")).to_be_enabled()

    # Switch to Real KICKR
    page.locator("#set-trainer-mode").select_option("dircon")
    expect(page.locator("#set-trainer-mode")).to_have_value("dircon")
    page.locator("#btn-apply-mode").click()
    expect(page.locator("#mode-msg")).to_contain_text("Real KICKR", timeout=20_000)

    chip = page.locator("#chip-trainer")
    expect(chip).to_have_text(re.compile(r"Trainer (connected|off)"), timeout=10_000)
    connected = "ok" in (chip.get_attribute("class") or "")

    expect(page.locator("#btn-discover")).to_be_enabled()
    if connected:
        expect(page.locator("#btn-connect")).to_be_disabled()
        expect(page.locator("#btn-disconnect")).to_be_enabled()
    else:
        expect(page.locator("#btn-connect")).to_be_enabled()
        expect(page.locator("#btn-disconnect")).to_be_disabled()

    # Restore Emulator for other e2e tests
    page.locator("#set-trainer-mode").select_option("simulated")
    expect(page.locator("#set-trainer-mode")).to_have_value("simulated")
    page.locator("#btn-apply-mode").click()
    expect(page.locator("#mode-msg")).to_contain_text("Emulator", timeout=20_000)

    st = page.request.get(f"{e2e_base_url}/api/status").json()
    assert st.get("emulator") is True
    assert st.get("engine", {}).get("trainer_connected") is True

    page.locator('#view-settings [data-nav="home"]').click()
    wait_for_home(page)
    expect_trainer_chip_connected(page, emulator=True)
