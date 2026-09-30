#!/usr/bin/env bash
# Build KICKR Pi.app and pack it into a versioned drag-and-drop DMG.
# Output: dist/<version>/KICKR-Pi-<version>-macos.dmg
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

VERSION="$(grep -E '^version[[:space:]]*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
if [[ -z "${VERSION}" ]]; then
  echo "error: could not read version from pyproject.toml" >&2
  exit 1
fi
APP_NAME="KICKR Pi"
DIST_DIR="${ROOT}/dist"
VERSION_DIR="${DIST_DIR}/${VERSION}"
APP_DIR="${DIST_DIR}/${APP_NAME}.app"
DMG_NAME="KICKR-Pi-${VERSION}-macos.dmg"
DMG_PATH="${VERSION_DIR}/${DMG_NAME}"
STAGE="${DIST_DIR}/dmg-stage"
VOL_NAME="KICKR Pi ${VERSION}"

"${ROOT}/deploy/macos/build_app.sh"

if [[ ! -d "${APP_DIR}" ]]; then
  echo "error: app missing at ${APP_DIR}" >&2
  exit 1
fi

echo "==> Staging DMG contents (v${VERSION})…"
rm -rf "${STAGE}"
mkdir -p "${STAGE}" "${VERSION_DIR}"
cp -R "${APP_DIR}" "${STAGE}/"
# Stamp version into the on-disk Read Me
sed "s/__VERSION__/${VERSION}/g" "${ROOT}/deploy/macos/ReadMe.txt" > "${STAGE}/Read Me.txt"
ln -s /Applications "${STAGE}/Applications"

# Clear previous DMG for this version
rm -f "${DMG_PATH}" "${DIST_DIR}/rw.${DMG_NAME}" "${VERSION_DIR}/rw.${DMG_NAME}"

echo "==> Creating ${DMG_NAME}…"
hdiutil create \
  -volname "${VOL_NAME}" \
  -srcfolder "${STAGE}" \
  -ov \
  -format UDRW \
  "${DIST_DIR}/rw.${DMG_NAME}"

hdiutil convert \
  "${DIST_DIR}/rw.${DMG_NAME}" \
  -format ULMO \
  -o "${DMG_PATH}"

rm -f "${DIST_DIR}/rw.${DMG_NAME}"
rm -rf "${STAGE}"

# Version stamp for humans / scripts
printf '%s\n' "${VERSION}" > "${VERSION_DIR}/VERSION"
date -u +'%Y-%m-%dT%H:%M:%SZ' > "${VERSION_DIR}/BUILT_AT"
# Drop unversioned leftover from older layouts
rm -f "${DIST_DIR}/${DMG_NAME}"

echo "==> Done: ${DMG_PATH}"
ls -lh "${DMG_PATH}"
echo "==> Version dir: ${VERSION_DIR}"
ls -la "${VERSION_DIR}"
