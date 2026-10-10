# steadyGrind 1.1.0 — Raspberry Pi

Pure-Python wheel for Debian / Raspberry Pi OS (Python 3.11+). Same app as the macOS DMG; no heart-rate BLE on Pi.

## Recommended: install script on the Pi

Clone or copy the repo onto the Pi, then:

```bash
cd HomeWlanTrainer
sudo ./deploy/raspberrypi/install.sh
```

Details: [deploy/raspberrypi/README.md](../../../deploy/raspberrypi/README.md).

## Update from this wheel

On a Pi that already has `/opt/kickr-pi`:

```bash
sudo /opt/kickr-pi/.venv/bin/pip install --upgrade ./kickr_pi-1.1.0-py3-none-any.whl
sudo systemctl restart kickr-pi
```

Or from the GitHub Release asset:

```bash
curl -fL -O https://github.com/attilameget/HomeWlanTrainer/releases/download/v1.1.0/kickr_pi-1.1.0-py3-none-any.whl
sudo /opt/kickr-pi/.venv/bin/pip install --upgrade ./kickr_pi-1.1.0-py3-none-any.whl
sudo systemctl restart kickr-pi
```

## Files

- `kickr_pi-1.1.0-py3-none-any.whl` — installable package (`py3-none-any`)
- `PI_INSTALL.md` — this note
