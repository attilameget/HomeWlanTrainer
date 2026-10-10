"""Transparent 1-2-3 veil in the last three seconds before the next stage."""

from __future__ import annotations

import json
import time

from playwright.sync_api import Page

from e2e.helpers import wait_for_home, wait_for_ride


def _countdown_digit(page: Page) -> str | None:
    veil = page.locator("#stage-countdown")
    classes = veil.get_attribute("class") or ""
    if "hidden" in classes.split():
        return None
    return (page.locator("#stage-countdown-digit").inner_text() or "").strip() or None


def _stop(page: Page, base: str) -> None:
    page.request.post(
        f"{base}/api/session/command",
        data=json.dumps({"command": "stop"}),
        headers={"Content-Type": "application/json"},
    )
    page.request.post(
        f"{base}/api/emulator/cadence",
        data=json.dumps({"rpm": 85}),
        headers={"Content-Type": "application/json"},
    )


def test_manual_ride_has_no_stage_countdown(page: Page, e2e_base_url: str) -> None:
    page.request.post(
        f"{e2e_base_url}/api/trainer/mode",
        data='{"mode":"simulated"}',
        headers={"Content-Type": "application/json"},
    )
    page.reload(wait_until="domcontentloaded")
    wait_for_home(page)
    try:
        page.locator("#manual-watts").fill("100")
        page.locator("#btn-manual-start").click()
        wait_for_ride(page)
        time.sleep(1.2)
        assert _countdown_digit(page) is None
    finally:
        _stop(page, e2e_base_url)


def test_stage_countdown_counts_up_before_the_next_stage(
    page: Page, e2e_base_url: str
) -> None:
    page.request.post(
        f"{e2e_base_url}/api/trainer/mode",
        data='{"mode":"simulated"}',
        headers={"Content-Type": "application/json"},
    )
    cadence = page.request.post(
        f"{e2e_base_url}/api/emulator/cadence",
        data=json.dumps({"rpm": 90}),
        headers={"Content-Type": "application/json"},
    )
    assert cadence.ok, cadence.text()
    page.reload(wait_until="domcontentloaded")
    wait_for_home(page)
    try:
        started = page.request.post(
            f"{e2e_base_url}/api/session",
            data=json.dumps({"workoutId": "demo"}),
            headers={"Content-Type": "application/json"},
        )
        assert started.ok, started.text()
        wait_for_ride(page)
        assert _countdown_digit(page) is None

        seen: list[str] = []
        deadline = time.monotonic() + 75.0
        while time.monotonic() < deadline:
            digit = _countdown_digit(page)
            if digit and (not seen or seen[-1] != digit):
                seen.append(digit)
            if seen[:3] == ["1", "2", "3"] and digit is None:
                break
            page.wait_for_timeout(100)
        else:
            raise AssertionError(f"countdown did not finish 1, 2, 3 (saw {seen})")

        label = page.locator("#ride-stage-label").inner_text()
        assert "steady" in label.lower(), label
        assert _countdown_digit(page) is None
    finally:
        _stop(page, e2e_base_url)
