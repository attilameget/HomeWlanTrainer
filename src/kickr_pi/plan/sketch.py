"""Shared LLM week-sketch → TrainingPlan day materialization (ERG on-host)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from kickr_pi.plan.models import PlanDay, SessionKind
from kickr_pi.plan.templates import build_bike_stages, run_distance_m

VALID_SPORTS = frozenset({"cycling", "running", "rest"})
VALID_KINDS = frozenset(
    {
        "endurance",
        "tempo",
        "intervals",
        "long",
        "recovery",
        "easy",
        "rest",
    }
)


def materialize_days(
    raw_days: list[Any],
    *,
    start: date,
    end: date,
    ftp_w: int,
    sketch_source: str = "LLM",
) -> list[PlanDay]:
    by_date: dict[str, dict[str, Any]] = {}
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
            kind = (
                "rest"
                if sport == "rest"
                else "endurance"
                if sport == "cycling"
                else "easy"
            )
        if sport == "rest":
            kind = "rest"
        by_date[d] = {
            "sport": sport,
            "kind": kind,
            "title": str(item.get("title") or _default_title(sport, kind)),
            "duration_min": max(0, int(float(item.get("duration_min") or 0))),
            "rationale": str(item.get("rationale") or ""),
        }

    out: list[PlanDay] = []
    cursor = start
    while cursor <= end:
        key = cursor.isoformat()
        item = by_date.get(key) or {
            "sport": "rest",
            "kind": "rest",
            "title": "Rest / mobility",
            "duration_min": 0,
            "rationale": "Recovery day filled in locally.",
        }
        sport = item["sport"]
        kind: SessionKind = item["kind"]  # type: ignore[assignment]
        if sport == "cycling":
            dur_s = max(20 * 60, int(item["duration_min"]) * 60)
            stages = build_bike_stages(kind, ftp_w=ftp_w, duration_s=dur_s)
            total = sum(int(s.get("duration_s") or 0) for s in stages)
            out.append(
                PlanDay(
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
            )
        elif sport == "running":
            dur_s = max(20 * 60, int(item["duration_min"]) * 60)
            out.append(
                PlanDay(
                    id=f"plan-day-{key}-run",
                    date=key,
                    sport="running",
                    kind=kind if kind != "rest" else "easy",
                    title=item["title"],
                    duration_s=dur_s,
                    distance_m=run_distance_m(
                        kind if kind != "rest" else "easy", dur_s
                    ),
                    rationale=item["rationale"]
                    or f"Run guidance from {sketch_source} sketch.",
                    playable=False,
                    intensity_note=kind,
                )
            )
        else:
            out.append(
                PlanDay(
                    id=f"plan-day-{key}-rest",
                    date=key,
                    sport="rest",
                    kind="rest",
                    title=item["title"],
                    duration_s=0,
                    rationale=item["rationale"] or "Rest day.",
                    playable=False,
                )
            )
        cursor += timedelta(days=1)
    return out


def _default_title(sport: str, kind: str) -> str:
    if sport == "rest":
        return "Rest / mobility"
    if sport == "running":
        return f"{kind.capitalize()} run"
    return f"{kind.capitalize()} ride"


def parse_start(value: str | None) -> date:
    if value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            pass
    return date.today()
