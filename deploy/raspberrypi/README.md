# steadyGrind on Raspberry Pi / Debian 13 (trixie)

Installs the same Python app as on macOS, as a `systemd` service that starts on boot.
Tested target: **Debian GNU/Linux 13 (trixie)** (and Raspberry Pi OS images based on it).
Also fine on Bookworm (12) with Python 3.11+.

Service / install paths still use the historical `kickr-pi` name (`/opt/kickr-pi`, `kickr-pi.service`, `kickr-pi.local`).

## Requirements

- Raspberry Pi 4 (2 GB+) or Pi 5 recommended (same Wi‑Fi / LAN as the KICKR)
- 64-bit Debian 13 / Raspberry Pi OS Lite
- Network access for `apt` and `pip` on first install

## Install

On the Pi, clone the repo (or copy it over), then:

```bash
cd HomeWlanTrainer
sudo ./deploy/raspberrypi/install.sh
```

Useful flags:

```bash
sudo ./deploy/raspberrypi/install.sh --port 80          # http://kickr-pi.local/
sudo ./deploy/raspberrypi/install.sh --no-hostname      # keep current hostname
sudo ./deploy/raspberrypi/install.sh --hostname my-bike
sudo ./deploy/raspberrypi/install.sh --skip-start
```

What the script does:

1. Installs `python3`, `python3-venv`, `avahi-daemon`, etc.
2. Sets hostname to `kickr-pi` (unless `--no-hostname`)
3. Creates system user `kickr-pi` and copies the app to `/opt/kickr-pi`
4. Creates a venv and `pip install`s the package
5. Installs `/etc/systemd/system/kickr-pi.service` and starts it
6. Writes `/etc/kickr-pi.env` (`KICKR_HOST=0.0.0.0`, port, trainer mode)

## Use

Open on your phone (same LAN):

- `http://kickr-pi.local:8080` (default port)
- or `http://kickr-pi.local/` if you installed with `--port 80`

```bash
systemctl status kickr-pi
journalctl -u kickr-pi -f
```

Edit config, then restart:

```bash
sudo nano /etc/kickr-pi.env
sudo systemctl restart kickr-pi
```

## Update

If `/opt/kickr-pi` is a git checkout (or you re-sync files there):

```bash
sudo /opt/kickr-pi/deploy/raspberrypi/update.sh
```

Or from your development machine: copy/rsync the tree onto the Pi and re-run `install.sh` (safe to re-run).

## Uninstall

```bash
sudo /opt/kickr-pi/deploy/raspberrypi/uninstall.sh
# also remove the service user + home data:
sudo /opt/kickr-pi/deploy/raspberrypi/uninstall.sh --purge-data
```

## Notes

- Port **80** works without root thanks to `CAP_NET_BIND_SERVICE` on the unit.
- Avahi provides `*.local` resolution; Bonjour on iPhone/Mac finds `kickr-pi.local`.
- Garmin tokens and SQLite live under the `kickr-pi` user data dirs (via `platformdirs`).
- This is **not** a cross-compiled binary — install runs **on** the Pi (native ARM64).
