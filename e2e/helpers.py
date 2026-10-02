"""Shared helpers for UI e2e selectors and waits."""

from __future__ import annotations

import re
import time

from playwright.sync_api import Page, expect


def wait_for_ride(page: Page, *, timeout_ms: int = 15_000) -> None:
    expect(page.locator("#view-ride")).to_be_visible(timeout=timeout_ms)
    expect(page.locator("#view-ride")).not_to_have_class(re.compile(r"\bhidden\b"))


def wait_for_home(page: Page, *, timeout_ms: int = 15_000) -> None:
    expect(page.locator("#view-home")).to_be_visible(timeout=timeout_ms)
    expect(page.locator("#view-home")).not_to_have_class(re.compile(r"\bhidden\b"))


def expect_trainer_chip_connected(page: Page, *, emulator: bool = True) -> None:
    """Chip must be ok and show connected label only when connected."""
    chip = page.locator("#chip-trainer")
    label = "Emulator connected" if emulator else "Trainer connected"
    expect(chip).to_have_text(label, timeout=10_000)
    expect(chip).to_have_class(re.compile(r"\bok\b"))
    expect(chip).not_to_have_class(re.compile(r"\bbad\b"))


def expect_trainer_chip_disconnected(page: Page, *, emulator: bool = True) -> None:
    """Chip must be bad; never ok when disconnected."""
    chip = page.locator("#chip-trainer")
    label = "Emulator off" if emulator else "Trainer off"
    expect(chip).to_have_text(label, timeout=10_000)
    expect(chip).to_have_class(re.compile(r"\bbad\b"))
    expect(chip).not_to_have_class(re.compile(r"\bok\b"))


def wait_power_at_least(page: Page, min_w: int, *, timeout_s: float = 12.0) -> None:
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        last = (page.locator("#ride-power").inner_text() or "").strip()
        try:
            if last not in ("—", "-", "") and int(float(last)) >= min_w:
                return
        except ValueError:
            pass
        page.wait_for_timeout(250)
    raise AssertionError(f"power did not reach {min_w} W (last={last!r})")


def read_elapsed_label(page: Page) -> str:
    """Manual ride shows total elapsed in #ride-stage-left."""
    return (page.locator("#ride-stage-left").inner_text() or "").strip()
