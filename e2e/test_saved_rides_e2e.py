"""Saved rides list: Stop saves FIT, Download works, Delete removes."""

from __future__ import annotations

import json
import time

from playwright.sync_api import Page, expect

from e2e.helpers import (
    expect_trainer_chip_connected,
    read_elapsed_label,
    wait_for_home,
    wait_for_ride,
)


def test_saved_ride_download_and_delete(page: Page, e2e_base_url: str) -> None:
    page.request.post(
        f"{e2e_base_url}/api/trainer/mode",
        data=json.dumps({"mode": "simulated"}),
        headers={"Content-Type": "application/json"},
    )
    # Clear any leftover rides from prior tests in this session
    for ride in page.request.get(f"{e2e_base_url}/api/rides").json():
        page.request.delete(f"{e2e_base_url}/api/rides/{ride['id']}")

    page.reload(wait_until="domcontentloaded")
    wait_for_home(page)
    expect_trainer_chip_connected(page, emulator=True)

    expect(page.locator("#saved-rides-section")).to_be_visible()
    expect(page.locator("#saved-rides .empty-row")).to_be_visible()

    page.locator("#manual-watts").fill("110")
    page.locator("#btn-manual-start").click()
    wait_for_ride(page)

    # Wait until workout clock advances (needs cadence from emulator)
    deadline = time.monotonic() + 12.0
    while time.monotonic() < deadline:
        label = read_elapsed_label(page)
        if label not in ("—", "0:00", ""):
            break
        page.wait_for_timeout(250)
    else:
        raise AssertionError("elapsed did not advance before Stop")

    page.locator("#btn-stop-m").click()
    dialog = page.locator("#app-dialog")
    expect(dialog).to_be_visible()
    page.locator("#app-dialog-confirm").click()
    wait_for_home(page)

    rows = page.locator("#saved-rides tr:not(.empty-row)")
    expect(rows).to_have_count(1, timeout=10_000)
    row = rows.first
    expect(row.locator("td").nth(0)).not_to_have_text("—")
    expect(row.locator("td").nth(1)).not_to_have_text("—")
    expect(row.locator("td").nth(2)).not_to_have_text("—")
    expect(row.locator("td").nth(3)).not_to_have_text("—")

    rides = page.request.get(f"{e2e_base_url}/api/rides").json()
    assert len(rides) == 1
    ride_id = rides[0]["id"]
    fit = page.request.get(f"{e2e_base_url}/api/rides/{ride_id}/fit")
    assert fit.status == 200
    body = fit.body()
    assert len(body) > 50
    assert b".FIT" in body[:16]
    ctype = (fit.headers.get("content-type") or "").lower()
    assert "octet-stream" in ctype or "fit" in ctype or ctype == ""

    page.locator("#saved-rides button", has_text="Delete").click()
    expect(page.locator("#app-dialog")).to_be_visible()
    page.locator("#app-dialog-confirm").click()
    expect(page.locator("#saved-rides .empty-row")).to_be_visible(timeout=10_000)
    assert page.request.get(f"{e2e_base_url}/api/rides").json() == []
