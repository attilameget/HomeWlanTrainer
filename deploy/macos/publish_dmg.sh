#!/usr/bin/env bash
# One-shot: build + commit + push the versioned macOS DMG for the current pyproject version,
# then publish/update the GitHub Release as Latest (repo right-rail).
# Must run on macOS (Darwin) with hdiutil. Example:
#   git checkout main && git pull
#   ./deploy/macos/publish_dmg.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "error: publish_dmg.sh requires macOS (found $(uname -s))" >&2
  exit 1
fi
if ! command -v hdiutil >/dev/null 2>&1; then
  echo "error: hdiutil not found" >&2
  exit 1
fi

VERSION="$(grep -E '^version[[:space:]]*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
DMG="dist/latest/steadyGrind-${VERSION}-macos.dmg"
TAG="v${VERSION}"

"${ROOT}/deploy/macos/build_dmg.sh"

if [[ ! -f "${DMG}" ]]; then
  echo "error: missing ${DMG}" >&2
  exit 1
fi

# Restore download docs; keep README What's new above Screenshots
python3 - <<'PY'
from pathlib import Path
import re

ver = None
for line in Path("pyproject.toml").read_text().splitlines():
    m = re.match(r'version\s*=\s*"([^"]+)"', line)
    if m:
        ver = m.group(1)
        break
assert ver

highlights = """- **Start Riding.** The workout preview button is Start Riding. The Home manual button is Start Manual Ride.
- **Full-screen close.** Closing the window with the red button while it is full screen returns to the previous desktop."""

what = Path("dist/latest/WHAT_IS_NEW.md")
what.write_text(
    f"""# What's new in {ver}

Released **2026-10-10**. Full project history: [CHANGELOG.md](../../CHANGELOG.md).

## Highlights

{highlights}

## Installer

- `steadyGrind-{ver}-macos.dmg` (this folder)
- GitHub Release: https://github.com/attilameget/HomeWlanTrainer/releases/tag/v{ver}
"""
)

readme = Path("README.md").read_text()
whats_new = f"""## What's new (v{ver})

{highlights}

Full notes: [CHANGELOG](CHANGELOG.md) · [What's New](dist/latest/WHAT_IS_NEW.md)

"""
readme2, n = re.subn(
    r"## What's new \(v[^)]+\).*?(?=\n## Screenshots\b)",
    whats_new,
    readme,
    count=1,
    flags=re.S,
)
if n != 1:
    # Insert before Screenshots if the section is missing
    if "\n## Screenshots" not in readme:
        raise SystemExit("README missing ## Screenshots anchor")
    readme2 = readme.replace("\n## Screenshots", "\n" + whats_new + "## Screenshots", 1)

share = f"""## Share with a friend (macOS DMG installer)

**Download the latest DMG** (Apple silicon, v{ver}):

```bash
curl -fL -o steadyGrind-{ver}-macos.dmg \\
  https://github.com/attilameget/HomeWlanTrainer/releases/download/v{ver}/steadyGrind-{ver}-macos.dmg
```

Also in the repo: [`dist/latest/`](dist/latest/) ([DMG](https://github.com/attilameget/HomeWlanTrainer/raw/main/dist/latest/steadyGrind-{ver}-macos.dmg)).

Rebuild locally (output goes to `dist/latest/`; older builds move to `dist/previous-builds/<version>/`; runs unit + e2e tests first):

```bash
./deploy/macos/build_dmg.sh
```
"""
readme3, n = re.subn(
    r"## Share with a friend \(macOS DMG installer\).*?(?=\n## |\n\*\*On your friend's Mac\*\*)",
    share + "\n",
    readme2,
    count=1,
    flags=re.S,
)
if n != 1:
    raise SystemExit(f"README Share section replace failed (n={n})")
Path("README.md").write_text(readme3)

def demote_previous_latest(text: str, new_ver: str) -> str:
    found = re.search(r"## macOS — v([\d.]+) \(latest\)", text)
    if not found or found.group(1) == new_ver:
        return text
    old = found.group(1)
    start = found.start()
    nxt = re.search(r"\n## macOS —", text[found.end():])
    end = found.end() + nxt.start() if nxt else len(text)
    section = text[start:end]
    section = section.replace(" (latest)", "", 1)
    section = section.replace("dist/latest/", f"dist/previous-builds/{old}/")
    section = section.replace("](latest/", f"](previous-builds/{old}/")
    section = section.replace(f"dist/{old}/", f"dist/previous-builds/{old}/")
    section = section.replace(f"]({old}/", f"](previous-builds/{old}/")
    return text[:start] + section + text[end:]

dist_readme = demote_previous_latest(Path("dist/README.md").read_text(), ver)
dist_readme = re.sub(
    r"## macOS — v[\d.]+ \(latest\)",
    lambda m: m.group(0).replace(" (latest)", ""),
    dist_readme,
    count=1,
)

latest = f"""## macOS — v{ver} (latest)

`dist/latest/` is this build. Older installers are under `dist/previous-builds/`.

What's new: [`WHAT_IS_NEW.md`](latest/WHAT_IS_NEW.md) · full log: [`CHANGELOG.md`](../CHANGELOG.md)

| File | Path |
| --- | --- |
| Installer | [`dist/latest/steadyGrind-{ver}-macos.dmg`](latest/steadyGrind-{ver}-macos.dmg) |
| Version stamp | [`dist/latest/VERSION`](latest/VERSION) |
| GitHub Release | [v{ver}](https://github.com/attilameget/HomeWlanTrainer/releases/tag/v{ver}) |

```bash
curl -fL -o steadyGrind-{ver}-macos.dmg \\
  https://github.com/attilameget/HomeWlanTrainer/releases/download/v{ver}/steadyGrind-{ver}-macos.dmg

# or from the repo tree:
curl -fL -o steadyGrind-{ver}-macos.dmg \\
  https://github.com/attilameget/HomeWlanTrainer/raw/main/dist/latest/steadyGrind-{ver}-macos.dmg
```

"""
dist2, n = re.subn(
    rf"## macOS — v{re.escape(ver)}(?: \(latest\))?.*?(?=\n## macOS —)",
    latest,
    dist_readme,
    count=1,
    flags=re.S,
)
if n != 1:
    parts = dist_readme.split("\n## macOS —", 1)
    if len(parts) != 2:
        raise SystemExit("dist/README structure unexpected")
    dist2 = parts[0].rstrip() + "\n" + latest + "\n## macOS —" + parts[1]
Path("dist/README.md").write_text(dist2)
print(f"updated docs for {ver}")
PY

git add dist/latest dist/previous-builds README.md dist/README.md
if ! git diff --cached --quiet; then
  git commit -m "Add steadyGrind ${VERSION} macOS DMG installer."
  BRANCH="$(git rev-parse --abbrev-ref HEAD)"
  git push -u origin "${BRANCH}"
else
  echo "docs already up to date; skipping commit"
fi

# Publish / refresh GitHub Release as Latest (right-rail on the repo page)
if command -v gh >/dev/null 2>&1; then
  NOTES="dist/latest/WHAT_IS_NEW.md"
  TITLE="v${VERSION}"
  if gh release view "${TAG}" >/dev/null 2>&1; then
    gh release upload "${TAG}" "${DMG}" --clobber
    gh release edit "${TAG}" --title "${TITLE}" --notes-file "${NOTES}" --latest
    echo "==> Updated GitHub Release ${TAG} as Latest"
  else
    gh release create "${TAG}" "${DMG}" \
      --title "${TITLE}" \
      --notes-file "${NOTES}" \
      --latest
    echo "==> Created GitHub Release ${TAG} as Latest"
  fi
else
  echo "warning: gh not found — create GitHub Release ${TAG} manually and mark Latest" >&2
fi

ls -lh "${DMG}"
echo "==> Published ${DMG} (tag ${TAG})"
