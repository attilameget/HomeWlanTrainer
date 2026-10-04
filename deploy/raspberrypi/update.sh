#!/usr/bin/env bash
# Pull latest code (if git) and reinstall into the venv, then restart kickr-pi.
# Run on the Pi: sudo /opt/kickr-pi/deploy/raspberrypi/update.sh
set -euo pipefail

PREFIX="${KICKR_PREFIX:-/opt/kickr-pi}"
SERVICE_NAME="kickr-pi"
SERVICE_USER="kickr-pi"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "error: run as root (sudo $0)" >&2
  exit 1
fi

if [[ ! -d "${PREFIX}" ]]; then
  echo "error: ${PREFIX} not found — run install.sh first" >&2
  exit 1
fi

echo "==> Updating ${PREFIX}…"
if [[ -d "${PREFIX}/.git" ]]; then
  sudo -u "${SERVICE_USER}" git -C "${PREFIX}" pull --ff-only
else
  echo "note: ${PREFIX} is not a git checkout; reinstalling from current tree only"
fi

# shellcheck disable=SC1091
source "${PREFIX}/.venv/bin/activate"
pip install --upgrade pip wheel >/dev/null
pip install --upgrade "${PREFIX}"
deactivate

systemctl restart "${SERVICE_NAME}.service"
sleep 1
systemctl --no-pager --full status "${SERVICE_NAME}.service" || true
echo "==> Updated and restarted ${SERVICE_NAME}"
