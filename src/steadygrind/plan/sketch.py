"""Shared LLM week-sketch → TrainingPlan day materialization (ERG on-host)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from steadygrind.plan.models import PlanDay, SessionKind
from steadygrind.plan.templates import build_bike_stages, run_distance_m

VALID_SPORTS = frozenset({"cycling", "running", "strength", "rest"})
VALID_KINDS = frozenset(
    {
        "endurance",
        "tempo",
        "intervals",
        "long",
        "recovery",
        "easy",
        "rest",
        "full_body",
        "upper",
        "lower",
        "core",
        "mobility",
    }
)

STRENGTH_DURATION_S = 45 * 60


def materialize_days(
    raw_days: list[Any],
    *,
    start: date,
    end: date,
    ftp_w: int,
    sketch_source: str = "LLM",
) -> list[PlanDay]:
    """
    Build PlanDay rows from a sketch.

    Multiple non-rest sessions may share a calendar date (same-day doubles:
    e.g. easy run + bike). At most one entry per (date, sport). Missing dates
    get a rest row.
    """
    # date → sport → session dict (last write wins for a sport)
    by_date: dict[str, dict[str, dict[str, Any]]] = {}
    for item in raw_days:
        if not isinstance(item, dict):
            continue
        d = str(item.get("date") or "")[:10]
        try:
            day_date = date.fromisoformat(d)
        except ValueError:
            continue
        if day_date < start or day_date > end:
            continue
        sport = str(item.get("sport") or "rest").lower()
        kind = str(item.get("kind") or "rest").lower()
        if sport not in VALID_SPORTS:
            sport = "rest"
        if kind not in VALID_KINDS:
            kind = _default_kind(sport)
        if sport == "rest":
            kind = "rest"
        distance_km = item.get("distance_km")
        try:
            distance_km_f = float(distance_km) if distance_km is not None else None
        except (TypeError, ValueError):
            distance_km_f = None
        if distance_km_f is not None and distance_km_f <= 0:
            distance_km_f = None
        by_date.setdefault(d, {})[sport] = {
            "sport": sport,
            "kind": kind,
            "title": str(item.get("title") or _default_title(sport, kind)),
            "duration_min": max(0, int(float(item.get("duration_min") or 0))),
            "distance_km": distance_km_f,
            "rationale": str(item.get("rationale") or ""),
        }

    out: list[PlanDay] = []
    cursor = start
    while cursor <= end:
        key = cursor.isoformat()
        sports = by_date.get(key) or {}
        # Drop rest if any real session exists that day
        active = {s: v for s, v in sports.items() if s != "rest"}
        if not active:
            active = {
                "rest": {
                    "sport": "rest",
                    "kind": "rest",
                    "title": "Rest / mobility",
                    "duration_min": 0,
                    "rationale": "Recovery day filled in locally.",
                }
            }
        # Morning-first: run, strength, bike, then rest
        order = [s for s in ("running", "strength", "cycling", "rest") if s in active]
        for sport in order:
            item = active[sport]
            out.append(
                _to_plan_day(
                    item,
                    key=key,
                    ftp_w=ftp_w,
                    sketch_source=sketch_source,
                )
            )
        cursor += timedelta(days=1)
    return out


def _default_kind(sport: str) -> str:
    if sport == "rest":
        return "rest"
    if sport == "cycling":
        return "endurance"
    if sport == "strength":
        return "full_body"
    return "easy"


def _to_plan_day(
    item: dict[str, Any],
    *,
    key: str,
    ftp_w: int,
    sketch_source: str,
) -> PlanDay:
    sport = item["sport"]
    kind: SessionKind = item["kind"]  # type: ignore[assignment]
    if sport == "cycling":
        dur_s = max(20 * 60, int(item["duration_min"]) * 60)
        stages = build_bike_stages(kind, ftp_w=ftp_w, duration_s=dur_s)
        total = sum(int(s.get("duration_s") or 0) for s in stages)
        return PlanDay(
            id=f"plan-day-{key}-bike",
            date=key,
            sport="cycling",
            kind=kind,
            title=item["title"],
            duration_s=total,
            rationale=item["rationale"]
            or f"Bike session from {sketch_source} sketch.",
            playable=True,
            stages=stages,
            intensity_note=kind,
        )
    if sport == "running":
        run_kind: SessionKind = kind if kind != "rest" else "easy"
        dist_km = item.get("distance_km")
        if dist_km is not None:
            distance_m = int(max(1500, float(dist_km) * 1000))
            # Prefer coach distance; duration from easy/tempo pace if missing/short
            pace_mps = 2.9 if run_kind in ("tempo", "intervals") else 2.7
            if run_kind == "long":
                pace_mps = 2.6
            dur_from_dist = int(distance_m / pace_mps)
            dur_s = max(20 * 60, int(item["duration_min"]) * 60)
            # If duration implies a much longer distance than stated, trust distance
            if run_distance_m(run_kind, dur_s) > distance_m * 1.25:
                dur_s = max(20 * 60, dur_from_dist)
        else:
            dur_s = max(20 * 60, int(item["duration_min"]) * 60)
            distance_m = run_distance_m(run_kind, dur_s)
        return PlanDay(
            id=f"plan-day-{key}-run",
            date=key,
            sport="running",
            kind=run_kind,
            title=item["title"],
            duration_s=dur_s,
            distance_m=distance_m,
            rationale=item["rationale"]
            or f"Run guidance from {sketch_source} sketch.",
            playable=False,
            intensity_note=run_kind,
        )
    if sport == "strength":
        dur_min = int(item["duration_min"]) or 45
        dur_s = max(20 * 60, dur_min * 60)
        strength_kind: SessionKind = (
            kind if kind in ("full_body", "upper", "lower", "core", "mobility") else "full_body"
        )
        return PlanDay(
            id=f"plan-day-{key}-strength",
            date=key,
            sport="strength",
            kind=strength_kind,
            title=item["title"],
            duration_s=dur_s,
            rationale=item["rationale"]
            or f"Strength / gym guidance from {sketch_source} sketch.",
            playable=False,
            intensity_note=strength_kind,
        )
    return PlanDay(
        id=f"plan-day-{key}-rest",
        date=key,
        sport="rest",
        kind="rest",
        title=item["title"],
        duration_s=0,
        rationale=item["rationale"] or "Rest day.",
        playable=False,
    )


def _default_title(sport: str, kind: str) -> str:
    if sport == "rest":
        return "Rest / mobility"
    if sport == "running":
        return f"{kind.capitalize()} run"
    if sport == "strength":
        label = kind.replace("_", " ")
        return f"Strength · {label}"
    return f"{kind.capitalize()} ride"


def parse_start(value: str | None) -> date:
    """Snap to Monday of the start week (Mon–Sun plan blocks)."""
    raw = date.today()
    if value:
        try:
            raw = date.fromisoformat(value[:10])
        except ValueError:
            pass
    return raw - timedelta(days=raw.weekday())


def clamp_run_volumes(
    days: list[PlanDay],
    *,
    start: date,
    weeks: int,
    volume_caps: dict[str, Any],
) -> list[PlanDay]:
    """
    Enforce per-session and week-1 weekly run km caps from recent history.

    Later weeks may grow ~7%/week above week-1 max.
    """
    easy_max = float(volume_caps.get("easy_run_km_max") or 7)
    tempo_max = float(volume_caps.get("tempo_run_km_max") or easy_max * 1.2)
    long_max = float(volume_caps.get("long_run_km_max") or 10)
    week1_max = float(volume_caps.get("week1_run_km_max") or easy_max * 3)

    for day in days:
        if day.sport != "running" or not day.distance_m:
            continue
        km = day.distance_m / 1000.0
        if day.kind == "long":
            cap = long_max
        elif day.kind in ("tempo", "intervals"):
            cap = tempo_max
        else:
            cap = easy_max
        if km > cap:
            day.distance_m = int(cap * 1000)
            pace_mps = 2.9 if day.kind in ("tempo", "intervals") else 2.7
            if day.kind == "long":
                pace_mps = 2.6
            day.duration_s = max(20 * 60, int(day.distance_m / pace_mps))

    for week in range(max(1, weeks)):
        week_start = start + timedelta(days=7 * week)
        week_end = week_start + timedelta(days=6)
        week_cap = week1_max * (1.0 + 0.07 * week)
        runs = [
            d
            for d in days
            if d.sport == "running"
            and d.distance_m
            and week_start.isoformat() <= d.date <= week_end.isoformat()
        ]
        total = sum((d.distance_m or 0) for d in runs) / 1000.0
        if total <= week_cap or total <= 0:
            continue
        scale = week_cap / total
        for d in runs:
            d.distance_m = max(1500, int((d.distance_m or 0) * scale))
            pace_mps = 2.9 if d.kind in ("tempo", "intervals") else 2.7
            if d.kind == "long":
                pace_mps = 2.6
            d.duration_s = max(20 * 60, int(d.distance_m / pace_mps))
    return days
