# KICKR Pi Trainer

Self-hosted app that runs Garmin Connect workouts on a Wahoo KICKR v6 over Wi-Fi.
Mac-first development; Raspberry Pi deployment comes after Phase A soak tests pass.

See [specification/SPEC.md](specification/SPEC.md) for the full software spec.

## Phase A – run on macOS (dev)

```bash
# Requires Python 3.11+ (uv installs one if needed)
curl -LsSf https://astral.sh/uv/install.sh | sh   # once
source ~/.local/bin/env

cd HomeWlanTrainer
uv sync
./deploy/macos/run.sh
```

Open **http://localhost:8080** on the Mac, or **http://\<mac-name\>.local:8080** from a phone on the same LAN.

Allow **Local Network** access when macOS prompts (needed for KICKR mDNS discovery).

Default trainer is the **simulator** (no hardware). Set trainer mode in Settings, or:

```bash
KICKR_TRAINER=dircon ./deploy/macos/run.sh
```

## Share with a friend (DMG installer)

Build a drag-and-drop disk image that bundles Python and all dependencies — no `uv`, git, or repo checkout on their Mac:

```bash
./deploy/macos/build_dmg.sh
```

Output: `dist/KICKR-Pi-0.1.0-macos.dmg` (version follows `pyproject.toml`).

**On your friend's Mac**

1. Open the DMG and drag **KICKR Pi** to Applications.
2. First launch: right-click → **Open** (unsigned / Gatekeeper).
3. Safari opens `http://127.0.0.1:8080`. Same Wi‑Fi as the KICKR; allow Local Network if asked.
4. Settings → Garmin Connect to fetch today's bike workout.
5. Click **Quit** in the KICKR Pi dialog when done.

Server log: `~/Library/Logs/KICKR-Pi/server.log`.

App-only build (no DMG): `./deploy/macos/build_app.sh` → `dist/KICKR Pi.app`.

## Tests

```bash
uv run pytest
```

## Phase B – Raspberry Pi

Deferred until Mac soak tests pass. Stubs live under `deploy/raspberrypi/`.
