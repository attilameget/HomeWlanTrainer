"""E2E: Plan params persist; Open bike day Back returns to Plan; Library still works."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from e2e.helpers import expect_trainer_chip_connected, wait_for_home


def test_plan_params_persist_and_preview_back_to_plan(
    page: Page, e2e_base_url: str
) -> None:
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
    expect(page.locator("#plan-claude-details")).to_be_visible()
    expect(page.locator("#plan-claude-summary-status")).to_be_visible()
    # Claude settings stay collapsed by default — expand to test
    page.locator("#plan-claude-details > summary").click()
    expect(page.locator("#plan-anthropic-key")).to_be_visible()
    expect(page.locator("#btn-plan-test-claude")).to_be_visible()
    expect(page.locator(".plan-claude-steps")).to_contain_text("console.anthropic.com")
    page.locator("#btn-plan-test-claude").click()
    expect(page.locator("#plan-claude-msg")).not_to_have_text("", timeout=10_000)

    page.locator("#plan-weeks").select_option("8")
    page.locator("#plan-hours").fill("5")
    page.locator("#plan-bike-days").fill("4")
    page.locator("#plan-run-days").fill("1")
    page.locator("#plan-strength-days").fill("1")
    # Rest: Fri+Sun default; also toggle Thursday on
    page.locator('#plan-rest-days .plan-rest-chip[data-dow="3"]').click()
    page.locator("#plan-goal").select_option("event")
    page.locator("#plan-notes").fill("prefer mornings")
    # Debounced settings save
    page.wait_for_timeout(600)

    page.locator("#btn-plan-generate").click()

    active = page.locator("#plan-active")
    expect(active).to_be_visible(timeout=15_000)
    expect(active).not_to_have_class(re.compile(r"\bhidden\b"))
    expect(page.locator("#plan-summary")).not_to_have_text("")
    expect(page.locator("#plan-coaching")).to_be_visible()
    expect(page.locator("#plan-coaching")).not_to_have_class(re.compile(r"\bhidden\b"))
    expect(page.locator("#plan-coaching-goal")).not_to_have_text("")
    expect(page.locator("#plan-coaching-why")).not_to_have_text("")
    expect(page.locator("#plan-coaching-expect")).not_to_have_text("")
    expect(page.locator("#plan-days tr").first).to_be_visible(timeout=5_000)
    # 8 weeks with strength + extra rest day → doubles → more than 7 rows/week
    row_count = page.locator("#plan-days tr").count()
    assert row_count >= 56
    expect(page.locator(".plan-table thead")).to_contain_text("Weekday")
    expect(page.locator("#plan-days tr").first.locator("td").nth(1)).not_to_have_text("")
    expect(page.locator("#plan-days .sport-pill.bike").first).to_be_visible()
    expect(page.locator("#plan-days .sport-pill.run").first).to_be_visible()
    expect(page.locator("#plan-days .sport-pill.strength").first).to_be_visible()
    expect(page.locator("#plan-days .sport-pill.rest").first).to_be_visible()
    expect(page.locator("#view-plan .plan-intro")).to_contain_text("Generate plan")
    expect(page.locator("#view-plan .plan-intro")).not_to_contain_text("30")

    # Open a bike day from Plan → Preview Back returns to Plan
    page.locator("#plan-days button[data-plan-preview]").first.click()
    expect(page.locator("#view-preview")).to_be_visible(timeout=10_000)
    expect(page.locator("#view-preview")).not_to_have_class(re.compile(r"\bhidden\b"))
    expect(page.locator("#btn-preview-back")).to_have_attribute("data-nav", "plan")
    page.locator("#btn-preview-back").click()
    expect(page.locator("#view-plan")).to_be_visible(timeout=10_000)
    expect(page.locator("#view-plan")).not_to_have_class(re.compile(r"\bhidden\b"))

    # Leave Plan and return — form values must still be there
    page.locator('[data-nav="home"]').first.click()
    wait_for_home(page)
    page.locator('[data-nav="plan"]').first.click()
    expect(page.locator("#view-plan")).to_be_visible()
    expect(page.locator("#plan-weeks")).to_have_value("8")
    expect(page.locator("#plan-hours")).to_have_value("5")
    expect(page.locator("#plan-bike-days")).to_have_value("4")
    expect(page.locator("#plan-run-days")).to_have_value("1")
    expect(page.locator("#plan-strength-days")).to_have_value("1")
    expect(page.locator('#plan-rest-days .plan-rest-chip[data-dow="3"]')).to_have_class(
        re.compile(r"\bselected\b")
    )
    expect(page.locator("#plan-goal")).to_have_value("event")
    expect(page.locator("#plan-notes")).to_have_value("prefer mornings")

    # Home Library still shows Plan-sourced bike rows
    page.locator('[data-nav="home"]').first.click()
    wait_for_home(page)
    lib = page.locator("#library")
    expect(lib).to_contain_text("Plan", timeout=5_000)
    plan_row = lib.locator("tr").filter(has_text="Plan").first
    expect(plan_row).to_be_visible()
    plan_row.locator("button.ghost").click()

    expect(page.locator("#view-preview")).to_be_visible(timeout=10_000)
    expect(page.locator("#btn-preview-back")).to_have_attribute("data-nav", "home")
    expect(page.locator("#btn-start")).to_be_visible()
