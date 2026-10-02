"""Ride timer must not advance until cadence is present."""

from __future__ import annotations

import json
import time

from playwright.sync_api import Page

from e2e.helpers import read_elapsed_label, wait_for_home, wait_for_ride


def test_timer_starts_only_with_cadence(page: Page, e2e_base_url: str) -> None:
    page.request.post(
        f"{e2e_base_url}/api/trainer/mode",
        data='{"mode":"simulated"}',
        headers={"Content-Type": "application/json"},
    )
    # Simulate standing still before Start (Start must not begin the clock)
    cad = page.request.post(
        f"{e2e_base_url}/api/emulator/cadence",
        data=json.dumps({"rpm": 0}),
        headers={"Content-Type": "application/json"},
    )
    assert cad.ok, cad.text()

    page.reload(wait_until="domcontentloaded")
    wait_for_home(page)

    try:
        page.locator("#manual-watts").fill("100")
        page.locator("#btn-manual-start").click()
        wait_for_ride(page)

        time.sleep(1.5)
        assert read_elapsed_label(page) == "0:00", (
            f"timer must stay at zero without cadence, got {read_elapsed_label(page)!r}"
        )

        cad = page.request.post(
            f"{e2e_base_url}/api/emulator/cadence",
            data=json.dumps({"rpm": 85}),
            headers={"Content-Type": "application/json"},
        )
        assert cad.ok, cad.text()

        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            if read_elapsed_label(page) not in ("0:00", ""):
                break
            time.sleep(0.25)
        else:
            raise AssertionError("timer did not advance after cadence returned")
    finally:
        page.request.post(
            f"{e2e_base_url}/api/emulator/cadence",
            data=json.dumps({"rpm": 85}),
            headers={"Content-Type": "application/json"},
        )
        page.request.post(
            f"{e2e_base_url}/api/session/command",
            data=json.dumps({"command": "stop"}),
            headers={"Content-Type": "application/json"},
        )
        page.goto(e2e_base_url, wait_until="domcontentloaded")
        wait_for_home(page)
