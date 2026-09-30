#!/usr/bin/env bash
# Remove the KICKR Pi systemd service and optional install tree.
# Does not delete Garmin tokens / app data under the service user's home
# unless you pass --purge-data.
set -euo pipefail

PREFIX="${KICKR_PREFIX:-/opt/kickr-pi}"
SERVICE_NAME="kickr-pi"
SERVICE_USER="kickr-pi"
ENV_FILE="/etc/kickr-pi.env"
PURGE_DATA=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --purge-data) PURGE_DATA=1; shift ;;
    --prefix) PREFIX="${2:?}"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo "error: run as root (sudo $0)" >&2
  exit 1
fi

echo "==> Stopping ${SERVICE_NAME}…"
systemctl disable --now "${SERVICE_NAME}.service" 2>/dev/null || true
rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload

rm -f "${ENV_FILE}"

if [[ -d "${PREFIX}" ]]; then
  echo "==> Removing ${PREFIX}…"
  rm -rf "${PREFIX}"
fi

if [[ "${PURGE_DATA}" -eq 1 ]] && id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  HOME_DIR="$(getent passwd "${SERVICE_USER}" | cut -d: -f6)"
  echo "==> Purging user data under ${HOME_DIR}…"
  userdel --remove "${SERVICE_USER}" 2>/dev/null || userdel "${SERVICE_USER}" 2>/dev/null || true
elif id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  echo "==> Leaving system user ${SERVICE_USER} (pass --purge-data to remove)"
fi

echo "==> Uninstall complete"
