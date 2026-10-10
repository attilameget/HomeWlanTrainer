"""Golden path: Manual ERG + Emulator pause/resume + stop summary."""

from __future__ import annotations

import re
import time

from playwright.sync_api import Page, expect

from e2e.helpers import (
    expect_trainer_chip_connected,
    read_elapsed_label,
    wait_for_home,
    wait_for_ride,
    wait_power_at_least,
)


def test_manual_ride_end_to_end(page: Page, e2e_base_url: str) -> None:
    # Ensure Emulator is connected (other e2e may have disconnected)
    page.request.post(
        f"{e2e_base_url}/api/trainer/mode",
        data='{"mode":"simulated"}',
        headers={"Content-Type": "application/json"},
    )
    page.reload(wait_until="domcontentloaded")
    wait_for_home(page)
    mark = page.locator(".brand-mark")
    expect(mark).to_be_visible()
    box = mark.bounding_box()
    assert box is not None
    assert abs(box["width"] - 28) < 2 and abs(box["height"] - 28) < 2
    expect_trainer_chip_connected(page, emulator=True)

    start = page.locator("#btn-manual-start")
    expect(start).to_have_text("Start Manual Ride")
    expect(start).to_be_enabled(timeout=10_000)

    page.locator("#manual-watts").fill("120")
    start.click()
    wait_for_ride(page)
    expect(page.locator("#chip-engine")).to_have_text("Running", timeout=10_000)
    expect(page.locator("#chip-engine")).to_have_class(re.compile(r"\bok\b"))

    # Emulator side panel only on ride when Emulator mode is on
    emu = page.locator("#emulator-panel")
    expect(emu).to_be_visible()
    expect(emu).not_to_have_class(re.compile(r"\bhidden\b"))

    page.locator("#emu-watts").fill("180")
    page.locator("#btn-emu-target").click()
    wait_power_at_least(page, 150, timeout_s=15.0)

    page.locator("#btn-emu-pause").click()
    expect(page.locator("#chip-engine")).to_have_text("Paused", timeout=10_000)
    expect(page.locator("#chip-engine")).not_to_have_class(re.compile(r"\bok\b"))
    frozen = read_elapsed_label(page)
    time.sleep(1.2)
    assert read_elapsed_label(page) == frozen, "elapsed should freeze while paused"

    page.locator("#btn-emu-resume").click()
    expect(page.locator("#chip-engine")).to_have_text("Running", timeout=10_000)
    expect(page.locator("#chip-engine")).to_have_class(re.compile(r"\bok\b"))

    page.locator("#btn-stop-m").click()
    dialog = page.locator("#app-dialog")
    expect(dialog).to_be_visible()
    expect(dialog).not_to_have_class(re.compile(r"\bhidden\b"))
    expect(page.locator("#app-dialog-title")).to_have_text("Workout summary")
    elapsed = page.locator("#summary-elapsed").inner_text().strip()
    avg = page.locator("#summary-avg-watts").inner_text().strip()
    assert elapsed not in ("", "—")
    assert avg not in ("", "—")
    assert "W" in avg

    page.locator("#app-dialog-confirm").click()  # Back to main screen
    wait_for_home(page)
    expect(page.locator("#btn-manual-start")).to_be_enabled()
