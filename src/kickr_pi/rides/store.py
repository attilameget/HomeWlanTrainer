"""Persist a ride recording as FIT + SQLite row."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from kickr_pi.rides.fit import write_activity_fit
from kickr_pi.rides.models import RideRecording
from kickr_pi.storage.repository import Repository

logger = logging.getLogger(__name__)


def save_ride(
    recording: RideRecording,
    *,
    repo: Repository,
    rides_dir: Path,
) -> dict[str, Any] | None:
    """Write FIT and insert a rides row. Returns the list payload or None."""
    if recording.duration_s < 1.0:
        return None
    ride_id = uuid.uuid4().hex
    fit_path = rides_dir / f"{ride_id}.fit"
    try:
        write_activity_fit(recording, fit_path)
    except Exception as exc:  # noqa: BLE001
        logger.exception("failed to write FIT for ride: %s", exc)
        raise

    started = recording.started_at.isoformat()
    ended = recording.ended_at.isoformat()
    row = {
        "id": ride_id,
        "started_at": started,
        "ended_at": ended,
        "duration_s": float(recording.duration_s),
        "avg_power_w": recording.avg_power_w,
        "workout_name": recording.workout_name,
        "fit_path": str(fit_path),
    }
    repo.insert_ride(row)
    return {
        "id": ride_id,
        "started_at": started,
        "ended_at": ended,
        "duration_s": float(recording.duration_s),
        "avg_power_w": recording.avg_power_w,
        "workout_name": recording.workout_name,
    }


def delete_ride_files(ride: dict[str, Any]) -> None:
    path = Path(ride.get("fit_path") or "")
    if path.is_file():
        try:
            path.unlink()
        except OSError as exc:
            logger.warning("could not delete FIT %s: %s", path, exc)


def download_filename(ride: dict[str, Any]) -> str:
    """steadyGrind-YYYYMMDD-HHMMSS.fit from started_at."""
    stamp = str(ride.get("started_at") or "")
    # 2026-10-03T18:00:00+00:00 → 20261003-180000
    digits = "".join(ch for ch in stamp if ch.isdigit())
    if len(digits) >= 14:
        return f"steadyGrind-{digits[:8]}-{digits[8:14]}.fit"
    return f"steadyGrind-{ride.get('id', 'ride')}.fit"
