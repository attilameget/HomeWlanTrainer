# UI end-to-end harness (dev only — not shipped)

Playwright + pytest against a real `steadygrind` process with **Trainer Emulator** enabled.
No physical KICKR and no Garmin login required for the golden path.

## Setup

```bash
uv sync --group dev
uv run playwright install chromium
```

## Run

```bash
uv run pytest e2e -q
```

Unit tests stay in `tests/` (`uv run pytest`). This folder is excluded from Pi install / DMG packaging.

## Golden path

`test_manual_ride_e2e.py` — Manual ERG start → emulator set watts → pause/resume → stop summary → home.
