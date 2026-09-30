# KICKR Pi Trainer

Self-hosted app that runs Garmin Connect workouts on a Wahoo KICKR v6 over Wi-Fi.
Mac-first development; Raspberry Pi deployment comes after Phase A soak tests pass.

See [specification/SPEC.md](specification/SPEC.md) for the full software spec.

## Phase A – run on macOS

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

## Tests

```bash
uv run pytest
```

## Phase B – Raspberry Pi

Deferred until Mac soak tests pass. Stubs live under `deploy/raspberrypi/`.
