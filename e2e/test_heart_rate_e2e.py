"""macOS heart-rate settings and ride number. No Bluetooth scan."""

from __future__ import annotations

import json

from playwright.sync_api import Page, expect

from e2e.helpers import wait_for_home, wait_for_ride


def test_heart_rate_settings_and_ride_number(page: Page, e2e_base_url: str) -> None:
    scanned: list[str] = []

    def _track(request) -> None:  # type: ignore[no-untyped-def]
        if "/api/hr/discover" in request.url or "/api/hr/connect" in request.url:
            scanned.append(request.url)

    page.on("request", _track)

    try:
        page.request.post(
            f"{e2e_base_url}/api/trainer/mode",
            data=json.dumps({"mode": "simulated"}),
            headers={"Content-Type": "application/json"},
        )
        status = page.request.get(f"{e2e_base_url}/api/status").json()
        supported = bool(status.get("hr_supported"))

        page.reload(wait_until="domcontentloaded")
        wait_for_home(page)
        page.locator('[data-nav="settings"]').click()
        expect(page.locator("#view-settings")).to_be_visible(timeout=10_000)

        section = page.locator("#hr-settings")
        if not supported:
            expect(section).to_be_hidden()
        else:
            expect(section).to_be_visible(timeout=10_000)
            expect(page.locator("#btn-hr-discover")).to_be_enabled()
            expect(page.locator("#btn-hr-connect")).to_be_enabled()
            expect(page.locator("#btn-hr-disconnect")).to_be_disabled()

        page.locator("#btn-settings-back").click()
        wait_for_home(page)
        start = page.locator("#btn-manual-start")
        expect(start).to_be_enabled(timeout=10_000)
        start.click()
        wait_for_ride(page)
        ride_hr = page.locator("#ride-hr-wrap")
        if supported:
            expect(ride_hr).to_be_visible()
            expect(page.locator("#ride-hr")).to_have_text("—")
        else:
            expect(ride_hr).to_be_hidden()
        assert scanned == []
    finally:
        # The e2e server is shared. Leave it idle so the next test still sees Home.
        page.request.post(
            f"{e2e_base_url}/api/session/command",
            data=json.dumps({"command": "stop"}),
            headers={"Content-Type": "application/json"},
        )
