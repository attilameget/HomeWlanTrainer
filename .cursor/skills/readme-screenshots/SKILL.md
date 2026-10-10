---
name: readme-screenshots
description: >-
  Capture steadyGrind UI screenshots for README and docs using Playwright and
  the Trainer Emulator. Use when the user asks for app screenshots, README
  images, marketing stills, or to refresh docs/screenshots.
---

# README screenshots (steadyGrind)

Capture polished UI stills of the running app for [`README.md`](../../../README.md) without a physical KICKR or Garmin login.

## Output

Default directory (git-friendly):

```
docs/screenshots/
  home.png
  preview.png
  ride.png
  settings.png
  plan.png          # Plan form + Claude panel
  plan-active.png   # Generated plan + coach reasoning
```

Phone variants (optional): `*-phone.png`.

Stills are **1280×800** (half the former 2560×1600 retina captures) via `device_scale_factor=1`.

## Quick run

From the repo root:

```bash
uv sync --group dev
uv run playwright install chromium
uv run python .cursor/skills/readme-screenshots/scripts/capture_readme_screenshots.py
```

Flags:

```bash
# Custom output dir
uv run python .cursor/skills/readme-screenshots/scripts/capture_readme_screenshots.py --out docs/screenshots

# Phone + desktop viewports
uv run python .cursor/skills/readme-screenshots/scripts/capture_readme_screenshots.py --phone

# Skip starting a server; attach to an already-running app
uv run python .cursor/skills/readme-screenshots/scripts/capture_readme_screenshots.py --base-url http://127.0.0.1:8080
```

## Agent workflow

Copy this checklist and complete it:

```
Screenshot progress:
- [ ] Ensure Playwright Chromium is installed
- [ ] Run capture_readme_screenshots.py
- [ ] Open PNGs and confirm they look good (not empty / not error states)
- [ ] Offer README markdown snippets linking the new images
- [ ] Do not commit unless the user asks
```

1. Run the capture script from the **repo root** (not from the skill folder).
2. Prefer Emulator mode (script default). Never require a real KICKR or Garmin for the default set.
3. After capture, suggest README usage like:

```markdown
## Screenshots

![Home](docs/screenshots/home.png)

![Ride](docs/screenshots/ride.png)
```

4. Only edit `README.md` when the user asks to wire the images in.
5. Keep screenshots under `docs/screenshots/` (tracked). Do not put them under `dist/`.

## What each shot shows

| File | Screen | Setup |
| --- | --- | --- |
| `home.png` | Home library | Emulator connected; plan bike rows with pale structure sketches |
| `preview.png` | Workout preview | Built-in `demo` workout power profile chart |
| `ride.png` | Ride | Demo workout running with structure+power overlay; cadence set |
| `settings.png` | Settings | Trainer / Autoconnect section in view |
| `plan.png` | Plan | Goals form, rest chips, Claude panel expanded (no real key) |
| `plan-active.png` | Plan (active) | After Generate (rules fallback): coach reasoning + calendar |

## Notes

- Script starts an isolated `steadygrind` on an ephemeral port (same idea as `e2e/conftest.py`), then stops it.
- Viewport default: **1280×800** at scale 1 (half prior retina file size). `--phone` also shoots **390×844**.
- If capture fails on “app not ready”, run `uv run playwright install chromium` and retry.
- For a live Mac app already on `:8080`, pass `--base-url http://127.0.0.1:8080` (Emulator should already be connected).
