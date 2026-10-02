"""Settings Autoconnect toggle is present and persists."""

from __future__ import annotations

import json

from playwright.sync_api import Page, expect

from e2e.helpers import wait_for_home


def test_autoconnect_toggle_persists(page: Page, e2e_base_url: str) -> None:
    wait_for_home(page)
    page.locator('[data-nav="settings"]').click()
    expect(page.locator("#view-settings")).to_be_visible(timeout=10_000)
    expect(page.locator("#set-trainer-mode")).to_have_value("simulated", timeout=10_000)

    # Emulator: toggle disabled (applies to Real KICKR)
    auto = page.locator("#set-auto-connect")
    expect(auto).to_be_visible()
    expect(auto).to_be_disabled()

    # Switch to Real so the toggle is editable
    page.locator("#set-trainer-mode").select_option("dircon")
    expect(page.locator("#set-trainer-mode")).to_have_value("dircon")
    page.locator("#btn-apply-mode").click()
    expect(page.locator("#mode-msg")).to_contain_text("Real KICKR", timeout=20_000)

    page.locator('#view-settings [data-nav="home"]').click()
    wait_for_home(page)
    page.locator('[data-nav="settings"]').click()
    expect(page.locator("#set-trainer-mode")).to_have_value("dircon", timeout=10_000)
    expect(auto).to_be_enabled()

    resp = page.request.put(
        f"{e2e_base_url}/api/settings",
        data=json.dumps({"auto_connect": False}),
        headers={"Content-Type": "application/json"},
    )
    assert resp.ok, resp.text()
    assert resp.json().get("auto_connect") is False

    page.reload(wait_until="domcontentloaded")
    page.locator('[data-nav="settings"]').click()
    expect(page.locator("#set-auto-connect")).not_to_be_checked(timeout=10_000)

    resp = page.request.put(
        f"{e2e_base_url}/api/settings",
        data=json.dumps({"auto_connect": True}),
        headers={"Content-Type": "application/json"},
    )
    assert resp.ok
    assert resp.json().get("auto_connect") is True

    # Restore Emulator for other e2e tests
    page.request.post(
        f"{e2e_base_url}/api/trainer/mode",
        data=json.dumps({"mode": "simulated"}),
        headers={"Content-Type": "application/json"},
    )
    page.locator('#view-settings [data-nav="home"]').click()
    wait_for_home(page)
