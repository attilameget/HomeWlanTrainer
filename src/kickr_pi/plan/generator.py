"""On-host adaptive multi-sport plan generator (no cloud LLM)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from kickr_pi.plan.history import describe_history, weekly_hours
from kickr_pi.plan.models import (
    ActivitySummary,
    PlanDay,
    PlanGoals,
    SessionKind,
    TrainingPlan,
)
from kickr_pi.plan.templates import build_bike_stages, run_distance_m


def generate_plan(
    goals: PlanGoals,
    *,
    ftp_w: int,
    activities: list[ActivitySummary] | None = None,
) -> TrainingPlan:
    """
    Build a multi-week bike+run plan.

    Uses recent load to scale volume (cap ~+10%/week vs recent bike+run hours),
    avoids stacking hard bike + hard run on the same day, and produces playable
    ERG stages for bike days.
    """
    g = goals.clamp()
    activities = activities or []
    ftp = max(80, int(ftp_w))
    start = _parse_start(g.start_date)

    recent_h = weekly_hours(activities)
    target_h = g.hours_per_week
    if recent_h > 0:
        # Do not jump more than ~10% above recent load in week 1
        target_h = min(target_h, max(recent_h * 1.1, recent_h + 0.5))
        target_h = max(2.0, target_h)

    run_share = 0.0
    if g.run_days_per_week > 0:
        run_share = min(0.45, g.run_days_per_week / max(1, g.bike_days_per_week + g.run_days_per_week))
    bike_share = 1.0 - run_share

    days: list[PlanDay] = []
    for week in range(g.weeks):
        # Progression: build then light deload every 4th week
        if g.weeks >= 4 and (week + 1) % 4 == 0:
            week_factor = 0.85
            phase = "deload"
        else:
            week_factor = 1.0 + 0.06 * week
            if g.goal == "event" and week >= max(0, g.weeks - 2):
                week_factor = 0.75 if week == g.weeks - 1 else 0.95
                phase = "taper" if week == g.weeks - 1 else "build"
            else:
                phase = "build" if week > 0 else "base"

        week_hours = target_h * week_factor
        bike_hours = week_hours * bike_share
        run_hours = week_hours * run_share

        week_start = start + timedelta(days=7 * week)
        pattern = _week_pattern(
            week_start,
            bike_days=g.bike_days_per_week,
            run_days=g.run_days_per_week,
            phase=phase,
            week_index=week,
        )
        bike_slots = [p for p in pattern if p[1] == "cycling"]
        run_slots = [p for p in pattern if p[1] == "running"]

        bike_durations = _split_hours(bike_hours, len(bike_slots), long_bias=True)
        run_durations = _split_hours(run_hours, len(run_slots), long_bias=True)

        bi = ri = 0
        for day_date, sport, kind in pattern:
            if sport == "rest":
                days.append(
                    PlanDay(
                        id=f"plan-day-{day_date.isoformat()}-rest",
                        date=day_date.isoformat(),
                        sport="rest",
                        kind="rest",
                        title="Rest / mobility",
                        duration_s=0,
                        rationale="Recovery day — optional easy mobility, no structured load.",
                        playable=False,
                    )
                )
                continue

            if sport == "cycling":
                dur = bike_durations[bi] if bi < len(bike_durations) else 45 * 60
                bi += 1
                stages = build_bike_stages(kind, ftp_w=ftp, duration_s=dur)
                total = sum(int(s.get("duration_s") or 0) for s in stages)
                days.append(
                    PlanDay(
                        id=f"plan-day-{day_date.isoformat()}-bike",
                        date=day_date.isoformat(),
                        sport="cycling",
                        kind=kind,
                        title=_bike_title(kind),
                        duration_s=total,
                        rationale=_bike_rationale(kind, phase),
                        playable=True,
                        stages=stages,
                        intensity_note=_intensity_note(kind),
                    )
                )
            else:
                dur = run_durations[ri] if ri < len(run_durations) else 35 * 60
                ri += 1
                # Soften run if previous calendar day was hard bike
                if _prev_day_hard_bike(days):
                    kind = "easy"
                    dur = int(dur * 0.85)
                dist = run_distance_m(kind, dur)
                days.append(
                    PlanDay(
                        id=f"plan-day-{day_date.isoformat()}-run",
                        date=day_date.isoformat(),
                        sport="running",
                        kind=kind,
                        title=_run_title(kind),
                        duration_s=dur,
                        distance_m=dist,
                        rationale=_run_rationale(kind, phase),
                        playable=False,
                        intensity_note=_intensity_note(kind),
                    )
                )

    history_note = describe_history(activities)
    summary = (
        f"{g.weeks}-week multi-sport plan · ~{target_h:.1f} h/week target "
        f"({g.bike_days_per_week} bike / {g.run_days_per_week} run days) · FTP {ftp} W. "
        f"Bike sessions are ERG-ready in steadyGrind; run days are guidance for outdoors or treadmill."
    )
    if g.notes:
        summary += f" Notes: {g.notes}"

    return TrainingPlan(
        id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc).isoformat(),
        ftp_w=ftp,
        goals=g,
        summary=summary,
        history_note=history_note,
        days=days,
    )


def _parse_start(value: str | None) -> date:
    if value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            pass
    return date.today()


def _week_pattern(
    week_start: date,
    *,
    bike_days: int,
    run_days: int,
    phase: str,
    week_index: int,
) -> list[tuple[date, str, SessionKind]]:
    """
    Assign sports across Mon–Sun.

    Prefer hard sessions mid-week / weekend long; keep at least one rest day when possible.
    """
    # Default anchors: Mon bike, Tue run, Wed bike hard, Thu run, Fri rest/recover, Sat long bike, Sun long run/rest
    slots: list[tuple[int, str, SessionKind] | None] = [None] * 7

    bike_kinds = _bike_kinds_for_week(bike_days, phase=phase, week_index=week_index)
    run_kinds = _run_kinds_for_week(run_days, phase=phase)

    bike_prefs = [0, 2, 5, 3, 1, 6]  # Mon Wed Sat Thu Tue Sun
    run_prefs = [1, 3, 6, 4, 0, 2]  # Tue Thu Sun Fri Mon Wed

    bi = 0
    for dow in bike_prefs:
        if bi >= len(bike_kinds):
            break
        if slots[dow] is None:
            slots[dow] = (dow, "cycling", bike_kinds[bi])
            bi += 1

    ri = 0
    for dow in run_prefs:
        if ri >= len(run_kinds):
            break
        if slots[dow] is None:
            slots[dow] = (dow, "running", run_kinds[ri])
            ri += 1

    # Ensure rest if empty mid-week Friday preferred
    if all(s is not None for s in slots) and bike_days + run_days < 7:
        # Should not happen; leave as-is
        pass

    out: list[tuple[date, str, SessionKind]] = []
    for dow in range(7):
        day = week_start + timedelta(days=dow)
        if slots[dow] is None:
            out.append((day, "rest", "rest"))
        else:
            _, sport, kind = slots[dow]
            out.append((day, sport, kind))
    return out


def _bike_kinds_for_week(
    n: int, *, phase: str, week_index: int
) -> list[SessionKind]:
    if n <= 0:
        return []
    if phase in ("deload", "taper"):
        base: list[SessionKind] = ["recovery", "endurance", "endurance", "tempo", "endurance", "long"]
    elif week_index == 0:
        base = ["endurance", "tempo", "endurance", "intervals", "endurance", "long"]
    else:
        base = ["endurance", "intervals", "tempo", "endurance", "tempo", "long"]
    return base[:n]


def _run_kinds_for_week(n: int, *, phase: str) -> list[SessionKind]:
    if n <= 0:
        return []
    if phase in ("deload", "taper"):
        base: list[SessionKind] = ["easy", "easy", "long", "easy", "easy"]
    else:
        base = ["easy", "tempo", "long", "easy", "easy"]
    # Prefer not more than one quality run
    kinds = base[:n]
    if n >= 2 and phase not in ("deload", "taper"):
        kinds[0] = "easy"
        if n >= 3:
            kinds[1] = "tempo"
            kinds[2] = "long"
        else:
            kinds[1] = "long"
    return kinds


def _split_hours(hours: float, n: int, *, long_bias: bool) -> list[int]:
    if n <= 0:
        return []
    if hours <= 0:
        return [30 * 60] * n
    weights = [1.0] * n
    if long_bias and n >= 2:
        weights[-1] = 1.6
        if n >= 3:
            weights[1] = 1.15  # quality-ish mid slot
    total_w = sum(weights)
    secs = []
    remaining = hours * 3600
    for i, w in enumerate(weights):
        if i == n - 1:
            s = int(remaining)
        else:
            s = int((hours * 3600) * (w / total_w))
            remaining -= s
        secs.append(max(20 * 60, s))
    return secs


def _prev_day_hard_bike(days: list[PlanDay]) -> bool:
    if not days:
        return False
    prev = days[-1]
    return prev.sport == "cycling" and prev.kind in ("intervals", "tempo")


def _bike_title(kind: SessionKind) -> str:
    return {
        "endurance": "Endurance ride",
        "tempo": "Tempo ride",
        "intervals": "VO2 intervals",
        "long": "Long endurance",
        "recovery": "Recovery spin",
        "easy": "Easy spin",
        "rest": "Rest",
    }.get(kind, "Bike session")


def _run_title(kind: SessionKind) -> str:
    return {
        "easy": "Easy run",
        "tempo": "Tempo run",
        "intervals": "Run intervals",
        "long": "Long run",
        "recovery": "Recovery jog",
        "endurance": "Steady run",
        "rest": "Rest",
    }.get(kind, "Run")


def _bike_rationale(kind: SessionKind, phase: str) -> str:
    base = {
        "endurance": "Aerobic base on the trainer — hold Z2 and stay smooth.",
        "tempo": "Sweet-spot / tempo stimulus without overcooking recovery.",
        "intervals": "High-intensity VO2 work; keep recoveries honest.",
        "long": "Longer endurance to raise durability; fuel as you would outdoors.",
        "recovery": "Very easy spin to promote blood flow after harder days.",
        "easy": "Keep it easy — technique over watts.",
        "rest": "Rest.",
    }.get(kind, "Structured bike session.")
    if phase == "deload":
        return base + " Deload week — volume is intentionally lighter."
    if phase == "taper":
        return base + " Taper — freshness over fatigue."
    return base


def _run_rationale(kind: SessionKind, phase: str) -> str:
    base = {
        "easy": "Conversational pace. Completes run volume without stealing bike quality.",
        "tempo": "Controlled tempo; stop if form breaks down.",
        "intervals": "Short hard efforts with full recoveries.",
        "long": "Long easy run — build durability; not a race.",
        "recovery": "Shuffle / very easy jog or walk-jog.",
        "endurance": "Steady aerobic run.",
        "rest": "Rest.",
    }.get(kind, "Run session (outdoors or treadmill — not on the KICKR).")
    if phase in ("deload", "taper"):
        return base + f" ({phase} week)."
    return base


def _intensity_note(kind: SessionKind) -> str:
    return {
        "recovery": "Very easy",
        "easy": "Easy",
        "endurance": "Steady Z2",
        "tempo": "Tempo / sweet spot",
        "intervals": "Hard",
        "long": "Steady long",
        "rest": "Off",
    }.get(kind, "Moderate")
