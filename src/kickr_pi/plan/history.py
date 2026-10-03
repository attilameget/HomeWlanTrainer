"""Build recent training history from Garmin activities + local rides."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from kickr_pi.plan.models import ActivitySummary, Sport

logger = logging.getLogger(__name__)

RUN_KEYS = frozenset(
    {
        "running",
        "trail_running",
        "treadmill_running",
        "track_running",
        "indoor_running",
        "run",
    }
)
BIKE_KEYS = frozenset(
    {
        "cycling",
        "road_biking",
        "mountain_biking",
        "gravel_cycling",
        "virtual_ride",
        "indoor_cycling",
        "cyclocross",
        "bike",
        "biking",
    }
)


def _sport_from_activity(raw: dict[str, Any]) -> Sport | None:
    type_obj = raw.get("activityType") or {}
    key = str(
        type_obj.get("typeKey")
        or raw.get("activityTypeKey")
        or raw.get("sport")
        or ""
    ).lower()
    parent = str(type_obj.get("parentTypeId") or "")
    if key in RUN_KEYS or "run" in key:
        return "running"
    if key in BIKE_KEYS or "cycl" in key or "bike" in key:
        return "cycling"
    # Garmin sometimes uses numeric type ids; common: 1=running, 2=cycling
    tid = type_obj.get("typeId")
    if tid == 1:
        return "running"
    if tid == 2:
        return "cycling"
    if parent in ("1", "2"):
        return "running" if parent == "1" else "cycling"
    return None


def normalize_garmin_activity(raw: dict[str, Any]) -> ActivitySummary | None:
    sport = _sport_from_activity(raw)
    if sport is None:
        return None
    started = (
        raw.get("startTimeLocal")
        or raw.get("startTimeGMT")
        or raw.get("beginTimestamp")
        or ""
    )
    if isinstance(started, (int, float)):
        started = datetime.fromtimestamp(started / 1000, tz=timezone.utc).isoformat()
    duration = float(raw.get("duration") or raw.get("elapsedDuration") or 0)
    if duration <= 0:
        return None
    avg_power = raw.get("averagePower") or raw.get("avgPower")
    distance = raw.get("distance")
    return ActivitySummary(
        id=str(raw.get("activityId") or raw.get("activityId") or raw.get("id") or ""),
        sport=sport,
        started_at=str(started),
        duration_s=duration,
        avg_power_w=int(avg_power) if avg_power is not None else None,
        distance_m=float(distance) if distance is not None else None,
        name=str(raw.get("activityName") or raw.get("name") or "") or None,
        source="garmin",
    )


def normalize_local_ride(ride: dict[str, Any]) -> ActivitySummary:
    return ActivitySummary(
        id=f"local:{ride['id']}",
        sport="cycling",
        started_at=str(ride.get("started_at") or ""),
        duration_s=float(ride.get("duration_s") or 0),
        avg_power_w=ride.get("avg_power_w"),
        distance_m=None,
        name=ride.get("workout_name"),
        source="local",
    )


def weekly_hours(activities: list[ActivitySummary], *, sport: Sport | None = None) -> float:
    """Hours in the last 7 days for sport (or all bike+run)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    total = 0.0
    for a in activities:
        if sport and a.sport != sport:
            continue
        if a.sport == "rest":
            continue
        try:
            ts = datetime.fromisoformat(a.started_at.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if ts >= cutoff:
            total += a.duration_s
    return total / 3600.0


def describe_history(activities: list[ActivitySummary]) -> str:
    bike_h = weekly_hours(activities, sport="cycling")
    run_h = weekly_hours(activities, sport="running")
    bike_n = sum(1 for a in activities if a.sport == "cycling")
    run_n = sum(1 for a in activities if a.sport == "running")
    if not activities:
        return (
            "No recent Garmin or local history found — plan uses your goals and FTP only."
        )
    return (
        f"Last ~28 days: {bike_n} bike / {run_n} run sessions. "
        f"Recent 7-day load ≈ {bike_h:.1f} h bike + {run_h:.1f} h run."
    )


def merge_history(
    garmin_activities: list[dict[str, Any]],
    local_rides: list[dict[str, Any]],
    *,
    lookback_days: int = 28,
) -> list[ActivitySummary]:
    cutoff = date.today() - timedelta(days=lookback_days)
    out: list[ActivitySummary] = []
    seen: set[str] = set()

    for raw in garmin_activities:
        item = normalize_garmin_activity(raw)
        if item is None or not item.id or item.id in seen:
            continue
        if _date_key(item.started_at) < cutoff.isoformat():
            continue
        seen.add(item.id)
        out.append(item)

    for ride in local_rides:
        item = normalize_local_ride(ride)
        if item.duration_s <= 0:
            continue
        if _date_key(item.started_at) < cutoff.isoformat():
            continue
        # Prefer Garmin when same-day local backup exists; keep local as extra indoor signal
        if item.id in seen:
            continue
        seen.add(item.id)
        out.append(item)

    out.sort(key=lambda a: a.started_at, reverse=True)
    return out


def _date_key(started_at: str) -> str:
    if not started_at:
        return "1970-01-01"
    return started_at[:10]
