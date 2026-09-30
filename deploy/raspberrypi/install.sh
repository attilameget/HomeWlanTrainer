#!/usr/bin/env bash
# Install KICKR Pi Trainer on Raspberry Pi / Debian 13 (trixie) or later.
#
# Usage (from a clone of this repo on the Pi):
#   sudo ./deploy/raspberrypi/install.sh
#
# Options:
#   --port N          UI port (default 8080; use 80 for http://kickr-pi.local/)
#   --no-hostname     Do not rename the host to kickr-pi
#   --hostname NAME   Hostname to set (default kickr-pi)
#   --prefix DIR      Install prefix (default /opt/kickr-pi)
#   --skip-start      Install but do not enable/start the service yet
#
# Target: Debian GNU/Linux 13 (trixie) / Raspberry Pi OS based on it.
# Requires: root, network access for apt + pip.
set -euo pipefail

PORT=8080
SET_HOSTNAME=1
HOSTNAME_WANT="kickr-pi"
PREFIX="/opt/kickr-pi"
SKIP_START=0
SERVICE_NAME="kickr-pi"
SERVICE_USER="kickr-pi"
ENV_FILE="/etc/kickr-pi.env"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

usage() {
  sed -n '2,18p' "$0" | sed 's/^# \?//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="${2:?}"; shift 2 ;;
    --no-hostname) SET_HOSTNAME=0; shift ;;
    --hostname) HOSTNAME_WANT="${2:?}"; SET_HOSTNAME=1; shift 2 ;;
    --prefix) PREFIX="${2:?}"; shift 2 ;;
    --skip-start) SKIP_START=1; shift ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown option: $1" >&2; usage 1 ;;
  esac
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo "error: run as root (sudo $0 …)" >&2
  exit 1
fi

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "error: this installer is for Linux (Raspberry Pi / Debian)" >&2
  exit 1
fi

if [[ ! -f /etc/debian_version ]]; then
  echo "warning: expected Debian-based OS; continuing anyway…" >&2
fi

if [[ -f /etc/os-release ]]; then
  # shellcheck source=/dev/null
  . /etc/os-release
  echo "==> Detected ${PRETTY_NAME:-$ID $VERSION_ID}"
fi

if [[ ! -f "${REPO_ROOT}/pyproject.toml" ]] || [[ ! -d "${REPO_ROOT}/src/kickr_pi" ]]; then
  echo "error: run from a HomeWlanTrainer checkout (missing pyproject.toml / src)" >&2
  exit 1
fi

echo "==> Installing system packages…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  python3 \
  python3-venv \
  python3-pip \
  python3-dev \
  git \
  curl \
  avahi-daemon \
  libcap2-bin

PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "==> Python ${PY_VER}"
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
  || { echo "error: need Python 3.11+ (got ${PY_VER})" >&2; exit 1; }

echo "==> Ensuring Avahi (mDNS / .local) is running…"
systemctl enable --now avahi-daemon.service >/dev/null 2>&1 || true

if [[ "${SET_HOSTNAME}" -eq 1 ]]; then
  CURRENT="$(hostname 2>/dev/null || true)"
  if [[ "${CURRENT}" != "${HOSTNAME_WANT}" ]]; then
    echo "==> Setting hostname to ${HOSTNAME_WANT} (was ${CURRENT:-unknown})…"
    if command -v hostnamectl >/dev/null 2>&1; then
      hostnamectl set-hostname "${HOSTNAME_WANT}"
    else
      echo "${HOSTNAME_WANT}" >/etc/hostname
      hostname "${HOSTNAME_WANT}"
    fi
    if [[ -f /etc/hosts ]]; then
      if grep -qE '^127\.0\.1\.1[[:space:]]' /etc/hosts; then
        sed -i -E "s/^127\\.0\\.1\\.1[[:space:]].*/127.0.1.1\t${HOSTNAME_WANT}/" /etc/hosts
      else
        printf '127.0.1.1\t%s\n' "${HOSTNAME_WANT}" >>/etc/hosts
      fi
    fi
  else
    echo "==> Hostname already ${HOSTNAME_WANT}"
  fi
fi

if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  echo "==> Creating system user ${SERVICE_USER}…"
  useradd --system --home-dir "${PREFIX}" --create-home \
    --shell /usr/sbin/nologin "${SERVICE_USER}"
else
  echo "==> User ${SERVICE_USER} already exists"
fi

echo "==> Syncing application into ${PREFIX}…"
mkdir -p "${PREFIX}"
# Prefer rsync; fall back to tar if rsync is missing
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude '.venv/' \
    --exclude 'dist/' \
    --exclude 'build/' \
    --exclude '.git/' \
    --exclude '__pycache__/' \
    --exclude '.pytest_cache/' \
    --exclude '*.pyc' \
    --exclude '.DS_Store' \
    "${REPO_ROOT}/" "${PREFIX}/"
else
  apt-get install -y -qq rsync
  rsync -a --delete \
    --exclude '.venv/' \
    --exclude 'dist/' \
    --exclude 'build/' \
    --exclude '.git/' \
    --exclude '__pycache__/' \
    --exclude '.pytest_cache/' \
    --exclude '*.pyc' \
    --exclude '.DS_Store' \
    "${REPO_ROOT}/" "${PREFIX}/"
fi
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${PREFIX}"

echo "==> Creating virtualenv and installing kickr-pi…"
sudo -u "${SERVICE_USER}" python3 -m venv "${PREFIX}/.venv"
# shellcheck disable=SC1091
source "${PREFIX}/.venv/bin/activate"
pip install --upgrade pip wheel >/dev/null
pip install "${PREFIX}"
deactivate

echo "==> Writing ${ENV_FILE}…"
if [[ ! -f "${ENV_FILE}" ]]; then
  cat >"${ENV_FILE}" <<EOF
KICKR_HOST=0.0.0.0
KICKR_PORT=${PORT}
KICKR_TRAINER_MODE=dircon
EOF
else
  # Keep existing file; ensure port is set if missing
  if ! grep -qE '^KICKR_PORT=' "${ENV_FILE}"; then
    echo "KICKR_PORT=${PORT}" >>"${ENV_FILE}"
  fi
fi
chmod 644 "${ENV_FILE}"

echo "==> Installing systemd unit…"
install -m 0644 "${SCRIPT_DIR}/kickr-pi.service" "/etc/systemd/system/${SERVICE_NAME}.service"
# Point WorkingDirectory / ExecStart at chosen prefix
sed -i \
  -e "s|/opt/kickr-pi|${PREFIX}|g" \
  "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload

if [[ "${SKIP_START}" -eq 0 ]]; then
  echo "==> Enabling and starting ${SERVICE_NAME}…"
  systemctl enable --now "${SERVICE_NAME}.service"
  sleep 1
  systemctl --no-pager --full status "${SERVICE_NAME}.service" || true
else
  systemctl enable "${SERVICE_NAME}.service"
  echo "==> Service enabled but not started (--skip-start)"
fi

LAN_HINT="${HOSTNAME_WANT}.local"
if [[ "${PORT}" -eq 80 ]]; then
  URL="http://${LAN_HINT}/"
else
  URL="http://${LAN_HINT}:${PORT}/"
fi

cat <<EOF

==> Install complete

  UI (phone on same Wi‑Fi):  ${URL}
  Status:                    systemctl status ${SERVICE_NAME}
  Logs:                      journalctl -u ${SERVICE_NAME} -f
  Config:                    ${ENV_FILE}
  App dir:                   ${PREFIX}

  Update later:              sudo ${PREFIX}/deploy/raspberrypi/update.sh
  Uninstall:                 sudo ${PREFIX}/deploy/raspberrypi/uninstall.sh

EOF
