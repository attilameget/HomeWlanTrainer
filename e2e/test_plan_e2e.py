"""E2E: generate plan on Plan page; bike sessions appear in Home Library."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from e2e.helpers import expect_trainer_chip_connected, wait_for_home


def test_plan_generate_and_open_bike_day(page: Page, e2e_base_url: str) -> None:
    page.request.post(
        f"{e2e_base_url}/api/trainer/mode",
        data='{"mode":"simulated"}',
        headers={"Content-Type": "application/json"},
    )
    page.reload(wait_until="domcontentloaded")
    wait_for_home(page)
    expect_trainer_chip_connected(page, emulator=True)

    # No Home proposal strip
    expect(page.locator("#plan-today-section")).to_have_count(0)

    page.locator('[data-nav="plan"]').first.click()
    expect(page.locator("#view-plan")).to_be_visible()
    expect(page.locator("#view-plan")).not_to_have_class(re.compile(r"\bhidden\b"))
    expect(page.locator("#plan-ollama-enabled")).to_be_visible()

    page.locator("#plan-weeks").select_option("4")
    page.locator("#plan-hours").fill("5")
    page.locator("#plan-bike-days").fill("3")
    page.locator("#plan-run-days").fill("2")
    page.locator("#btn-plan-generate").click()

    active = page.locator("#plan-active")
    expect(active).to_be_visible(timeout=15_000)
    expect(active).not_to_have_class(re.compile(r"\bhidden\b"))
    expect(page.locator("#plan-summary")).not_to_have_text("")
    expect(page.locator("#plan-days tr")).to_have_count(28, timeout=5_000)
    expect(page.locator("#plan-days .sport-pill.bike").first).to_be_visible()
    expect(page.locator("#plan-days .sport-pill.run").first).to_be_visible()

    # Home Library shows Plan-sourced bike rows
    page.locator('[data-nav="home"]').first.click()
    wait_for_home(page)
    lib = page.locator("#library")
    expect(lib).to_contain_text("Plan", timeout=5_000)
    plan_row = lib.locator("tr").filter(has_text="Plan").first
    expect(plan_row).to_be_visible()
    plan_row.locator("button.ghost").click()

    expect(page.locator("#view-preview")).to_be_visible(timeout=10_000)
    expect(page.locator("#view-preview")).not_to_have_class(re.compile(r"\bhidden\b"))
    expect(page.locator("#btn-start")).to_be_visible()
