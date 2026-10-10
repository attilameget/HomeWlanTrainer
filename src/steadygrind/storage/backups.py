"""Local timestamped backups of settings and the active training plan.

Files live under the app data directory. The Claude API key and Garmin
login tokens are never written. Saved rides stay in their own folder.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKUP_VERSION = 1
_EXCLUDED_SETTINGS = frozenset({"anthropic_api_key"})
_NAME = re.compile(
    r"^steadygrind-backup-(\d{4}-\d{2}-\d{2}T\d{6}Z)(?:-(\d+))?\.json$"
)


def backups_dir(data_dir: Path) -> Path:
    path = Path(data_dir) / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def backup_payload(settings: dict[str, Any], plan: dict[str, Any] | None) -> dict[str, Any]:
    """Settings and plan safe to write to disk. Secrets are dropped."""
    clean = {
        key: value
        for key, value in settings.items()
        if key not in _EXCLUDED_SETTINGS
    }
    return {
        "version": BACKUP_VERSION,
        "settings": clean,
        "plan": plan,
    }


def create_backup(
    data_dir: Path,
    settings: dict[str, Any],
    plan: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Write a new backup file under ``data_dir/backups``. Existing files stay."""
    folder = backups_dir(data_dir)
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    stamp = moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    name = f"steadygrind-backup-{stamp}.json"
    path = folder / name
    suffix = 2
    while path.exists():
        name = f"steadygrind-backup-{stamp}-{suffix}.json"
        path = folder / name
        suffix += 1
    payload = backup_payload(settings, plan)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return describe_backup(path)


def list_backups(data_dir: Path) -> list[dict[str, Any]]:
    folder = backups_dir(data_dir)
    found = [describe_backup(path) for path in folder.glob("steadygrind-backup-*.json")]
    found = [item for item in found if item is not None]
    found.sort(key=_backup_sort_key, reverse=True)
    return found


def _backup_sort_key(item: dict[str, Any]) -> tuple[str, int]:
    match = _NAME.match(item["id"])
    if not match:
        return ("", 0)
    return (match.group(1), int(match.group(2) or 0))


def describe_backup(path: Path) -> dict[str, Any] | None:
    match = _NAME.match(path.name)
    if not match:
        return None
    created = datetime.strptime(match.group(1), "%Y-%m-%dT%H%M%SZ").replace(
        tzinfo=timezone.utc
    )
    local = created.astimezone()
    label = f"{local.day} {local.strftime('%b %Y, %H:%M')}"
    return {
        "id": path.name,
        "created_at": created.isoformat(),
        "label": label,
    }


def resolve_backup(data_dir: Path, backup_id: str) -> Path:
    """Return the backup path, or raise ValueError if the id is not a backup file."""
    if not backup_id or Path(backup_id).name != backup_id or not _NAME.match(backup_id):
        raise ValueError("unknown backup")
    path = backups_dir(data_dir) / backup_id
    if not path.is_file():
        raise ValueError("unknown backup")
    return path


def read_backup(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("backup is not a document")
    settings = data.get("settings")
    if not isinstance(settings, dict):
        raise ValueError("backup has no settings")
    settings.pop("anthropic_api_key", None)
    plan = data.get("plan")
    if plan is not None and not isinstance(plan, dict):
        raise ValueError("backup plan is invalid")
    return {"settings": settings, "plan": plan}


def reveal_supported() -> bool:
    return sys.platform == "darwin"


def reveal_backup_folder(data_dir: Path) -> bool:
    """Open the backup folder in Finder. Returns False when this is not macOS."""
    folder = backups_dir(data_dir)
    if not reveal_supported():
        return False
    import subprocess

    subprocess.run(["open", str(folder)], check=False)
    return True
