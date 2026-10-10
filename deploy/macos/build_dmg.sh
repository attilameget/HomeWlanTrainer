#!/usr/bin/env bash
# Build steadyGrind.app and pack it into a versioned drag-and-drop DMG.
# Output: dist/latest/steadyGrind-<version>-macos.dmg
# The previous dist/latest build is moved to dist/previous-builds/<old version>/.
#
# The mounted window is an icon view: steadyGrind on the left, Applications
# on the right, Read Me below. Positions match dmg-background.png and
# dmg-window.applescript.
set -euo pipefail

MOUNT_DIR=""
DEV_ENTRY=""

detach_layout_mount() {
  local target=""
  if [[ -n "${DEV_ENTRY}" ]]; then
    target="${DEV_ENTRY}"
  elif [[ -n "${MOUNT_DIR}" ]]; then
    target="${MOUNT_DIR}"
  fi
  if [[ -n "${target}" ]]; then
    hdiutil detach "${target}" -quiet || hdiutil detach "${target}" -force || true
  fi
  DEV_ENTRY=""
  MOUNT_DIR=""
}
trap detach_layout_mount EXIT

# Finder resolves `disk "<volume name>"` only when the image is mounted at
# /Volumes/<volume name>. A random directory under /Volumes (mountrandom)
# stays invisible to that lookup.
attach_rw_dmg() {
  local rw="$1"
  local plist
  plist="$(mktemp)"
  hdiutil attach -plist -readwrite -noverify -noautoopen "${rw}" > "${plist}"
  local i=0 mp dev
  while true; do
    mp="$(/usr/libexec/PlistBuddy -c "Print :system-entities:${i}:mount-point" "${plist}" 2>/dev/null || true)"
    dev="$(/usr/libexec/PlistBuddy -c "Print :system-entities:${i}:dev-entry" "${plist}" 2>/dev/null || true)"
    if [[ -z "${mp}" && -z "${dev}" ]]; then
      break
    fi
    if [[ -n "${mp}" ]]; then
      MOUNT_DIR="${mp}"
      DEV_ENTRY="${dev}"
    fi
    i=$((i + 1))
  done
  rm -f "${plist}"
  if [[ -z "${MOUNT_DIR}" || -z "${DEV_ENTRY}" ]]; then
    echo "error: disk image attached without a /Volumes mount" >&2
    exit 1
  fi
}

layout_dmg_window() {
  local rw="$1"
  local fallback_name="$2"

  echo "==> Mounting disk image for Finder layout…"
  attach_rw_dmg "${rw}"

  mkdir -p "${MOUNT_DIR}/.background"
  cp "${ROOT}/deploy/macos/dmg-background.png" "${MOUNT_DIR}/.background/background.png"

  local disk_name
  disk_name="$(diskutil info "${MOUNT_DIR}" | sed -n 's/^.*Volume Name:[[:space:]]*//p' | head -1)"
  if [[ -z "${disk_name}" ]]; then
    disk_name="${fallback_name}"
  fi
  echo "==> Finder layout on volume: ${disk_name} (${MOUNT_DIR})"

  # Finder has to be running before the layout script can set the window.
  open -g -a Finder || true
  sleep 5

  local attempt
  for attempt in 1 2 3 4 5; do
    if /usr/bin/osascript \
      "${ROOT}/deploy/macos/dmg-window.applescript" \
      "${disk_name}" \
      "${MOUNT_DIR}" \
      "steadyGrind.app" \
      "Applications" \
      "Read Me.txt"
    then
      break
    fi
    if [[ "${attempt}" -eq 5 ]]; then
      echo "error: Finder could not lay out the DMG window" >&2
      exit 1
    fi
    echo "==> Finder layout retry ${attempt}…"
    sleep $((attempt * 2))
  done

  chmod -Rf go-w "${MOUNT_DIR}" >/dev/null 2>&1 || true
  sync
  echo "==> Unmounting disk image…"
  local try
  for try in 1 2 3 4 5; do
    if hdiutil detach "${DEV_ENTRY}" -quiet; then
      break
    fi
    if [[ "${try}" -eq 5 ]]; then
      hdiutil detach "${DEV_ENTRY}" -force
    fi
    sleep 2
  done
  DEV_ENTRY=""
  MOUNT_DIR=""
}

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

VERSION="$(grep -E '^version[[:space:]]*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
if [[ -z "${VERSION}" ]]; then
  echo "error: could not read version from pyproject.toml" >&2
  exit 1
fi
APP_NAME="steadyGrind"
DIST_DIR="${ROOT}/dist"
# Current installer always lands in dist/latest. An older build already there
# moves to dist/previous-builds/<version> before this one is written.
if [[ -f "${DIST_DIR}/latest/VERSION" ]]; then
  old="$(tr -d '[:space:]' < "${DIST_DIR}/latest/VERSION")"
  if [[ -n "${old}" && "${old}" != "${VERSION}" ]]; then
    mkdir -p "${DIST_DIR}/previous-builds"
    rm -rf "${DIST_DIR}/previous-builds/${old}"
    mv "${DIST_DIR}/latest" "${DIST_DIR}/previous-builds/${old}"
    find "${DIST_DIR}/previous-builds/${old}" -name '*.md' -print0 | while IFS= read -r -d '' notes; do
      sed -i '' \
        -e 's|(../../CHANGELOG.md)|(../../../CHANGELOG.md)|g' \
        -e 's|(../../deploy/|(../../../deploy/|g' \
        "${notes}"
    done
    echo "==> Archived v${old} under dist/previous-builds/${old}"
  fi
fi
VERSION_DIR="${DIST_DIR}/latest"
APP_DIR="${DIST_DIR}/${APP_NAME}.app"
DMG_NAME="steadyGrind-${VERSION}-macos.dmg"
DMG_PATH="${VERSION_DIR}/${DMG_NAME}"
STAGE="${DIST_DIR}/dmg-stage"
VOL_NAME="steadyGrind ${VERSION}"

"${ROOT}/deploy/macos/build_app.sh"

if [[ ! -d "${APP_DIR}" ]]; then
  echo "error: app missing at ${APP_DIR}" >&2
  exit 1
fi

echo "==> Staging DMG contents (v${VERSION})…"
rm -rf "${STAGE}"
mkdir -p "${STAGE}/.background" "${VERSION_DIR}"
cp -R "${APP_DIR}" "${STAGE}/"
# Stamp version into the on-disk Read Me
sed "s/__VERSION__/${VERSION}/g" "${ROOT}/deploy/macos/ReadMe.txt" > "${STAGE}/Read Me.txt"
ln -s /Applications "${STAGE}/Applications"
cp "${ROOT}/deploy/macos/dmg-background.png" "${STAGE}/.background/background.png"
rm -f "${STAGE}/.DS_Store"

# Clear previous DMG for this version
RW_DMG="${DIST_DIR}/rw.${DMG_NAME}"
rm -f "${DMG_PATH}" "${RW_DMG}" "${VERSION_DIR}/rw.${DMG_NAME}"

echo "==> Creating ${DMG_NAME}…"
hdiutil create \
  -volname "${VOL_NAME}" \
  -srcfolder "${STAGE}" \
  -ov \
  -format UDRW \
  "${RW_DMG}"

# Room for Finder to write .DS_Store while the icon layout is applied.
CUR_SECTORS="$(hdiutil resize -limits "${RW_DMG}" | awk '/^[0-9]/ {print $2; exit}')"
hdiutil resize -sectors $((CUR_SECTORS + 65536)) "${RW_DMG}"

layout_dmg_window "${RW_DMG}" "${VOL_NAME}"

hdiutil convert \
  "${RW_DMG}" \
  -format ULMO \
  -o "${DMG_PATH}"

rm -f "${RW_DMG}"
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
