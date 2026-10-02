"""Workout preview shows a zone-colored power profile chart."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from e2e.helpers import wait_for_home


def test_workout_preview_chart(page: Page) -> None:
    wait_for_home(page)

    # Local demo workout (no Garmin required)
    page.evaluate(
        """async () => {
          state.workoutId = 'demo';
          await openPreview();
        }"""
    )

    expect(page.locator("#view-preview")).to_be_visible(timeout=10_000)
    expect(page.locator("#view-preview")).not_to_have_class(re.compile(r"\bhidden\b"))
    expect(page.locator("#preview-name")).to_have_text("Demo Intervals", timeout=10_000)
    expect(page.locator("#preview-chart")).to_be_visible()
    expect(page.locator("#preview-zone-legend")).to_contain_text("Z1")
    expect(page.locator("#preview-stage-detail")).to_contain_text("Warm-up", timeout=5_000)
    expect(page.locator("#preview-stage-detail")).to_contain_text("% FTP")

    # Tap toward the right side of the chart (later stages)
    box = page.locator("#preview-chart").bounding_box()
    assert box is not None
    page.locator("#preview-chart").click(
        position={"x": box["width"] * 0.75, "y": box["height"] * 0.5}
    )
    detail = page.locator("#preview-stage-detail").inner_text()
    detail_l = detail.lower()
    assert "duration" in detail_l
    assert "target" in detail_l
    assert any(name in detail for name in ("Hard", "Cool-down", "Steady", "Recovery", "Warm-up"))

    page.locator('#view-preview [data-nav="home"]').click()
    wait_for_home(page)
