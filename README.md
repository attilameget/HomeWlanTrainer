# KICKR Pi Trainer

Self-hosted app that runs Garmin Connect workouts on a Wahoo KICKR v6 over Wi-Fi.
Same codebase on macOS and Raspberry Pi (Debian 13 / trixie).

See [specification/SPEC.md](specification/SPEC.md) for the full software spec.

**What's new:** [CHANGELOG.md](CHANGELOG.md) · [v0.1.0 release notes](https://github.com/attilameget/HomeWlanTrainer/releases/tag/v0.1.0)

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

## Share with a friend (macOS DMG installer)

**Download the latest DMG** (Apple silicon, v0.1.0):

```bash
curl -fL -o KICKR-Pi-0.1.0-macos.dmg \
  https://github.com/attilameget/HomeWlanTrainer/releases/download/v0.1.0/KICKR-Pi-0.1.0-macos.dmg
```

Also in the repo: [`dist/0.1.0/`](dist/0.1.0/) ([DMG](https://github.com/attilameget/HomeWlanTrainer/raw/cursor/add-kickr-spec/dist/0.1.0/KICKR-Pi-0.1.0-macos.dmg)).

Rebuild locally (output goes to `dist/<version>/`):

```bash
./deploy/macos/build_dmg.sh
```

**On your friend's Mac**

1. Open the DMG and drag **KICKR Pi** to Applications.
2. First launch: right-click → **Open** (unsigned / Gatekeeper).
3. Safari opens `http://127.0.0.1:8080`. Same Wi‑Fi as the KICKR; allow Local Network if asked.
4. From a phone: use the LAN URL shown in the KICKR Pi dialog (or `http://<mac-name>.local:8080`).
5. Settings → Garmin Connect to fetch today's bike workout.
6. Click **Quit** in the KICKR Pi dialog when done.

Server log: `~/Library/Logs/KICKR-Pi/server.log`.

App-only build (no DMG): `./deploy/macos/build_app.sh` → `dist/KICKR Pi.app`.

## Tests

```bash
uv run pytest
```

## Phase B – Raspberry Pi (Debian 13 / trixie)

Native install on the Pi (not a cross-build from the Mac). Creates a venv under `/opt/kickr-pi` and a `systemd` unit that starts on boot.

```bash
# On the Pi (Debian 13 / Raspberry Pi OS), over SSH:
curl -fsSL https://github.com/attilameget/HomeWlanTrainer/archive/refs/heads/cursor/add-kickr-spec.tar.gz \
  | tar -xz
cd HomeWlanTrainer-cursor-add-kickr-spec
sudo ./deploy/raspberrypi/install.sh
```

Or with git:

```bash
git clone -b cursor/add-kickr-spec https://github.com/attilameget/HomeWlanTrainer.git
cd HomeWlanTrainer
sudo ./deploy/raspberrypi/install.sh
```

Then open **http://kickr-pi.local:8080** on your phone (same LAN).

Details, `--port 80`, update/uninstall: [deploy/raspberrypi/README.md](deploy/raspberrypi/README.md).
