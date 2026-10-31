"""On-host adaptive multi-sport plan generator (no cloud LLM)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from steadygrind.plan.history import build_load_profile, describe_history, weekly_hours
from steadygrind.plan.models import (
    ActivitySummary,
    PlanCoaching,
    PlanDay,
    PlanGoals,
    SessionKind,
    TrainingPlan,
)
from steadygrind.plan.sketch import clamp_run_volumes
from steadygrind.plan.templates import build_bike_stages, run_distance_m

STRENGTH_DURATION_S = 45 * 60


def generate_plan(
    goals: PlanGoals,
    *,
    ftp_w: int,
    activities: list[ActivitySummary] | None = None,
) -> TrainingPlan:
    """
    Build a multi-week bike + run + strength plan in Mon–Sun weekly blocks.

    Uses recent load to scale volume (cap ~+10%/week vs recent bike+run hours),
    honors user-selected rest weekdays, avoids stacking hard bike + hard run
    when possible, and produces playable ERG stages for bike days.
    """
    g = goals.clamp()
    activities = activities or []
    ftp = max(80, int(ftp_w))
    start = _parse_start(g.start_date)
    load = build_load_profile(activities, ftp_w=ftp)
    caps = load["volume_caps"]

    recent_h = weekly_hours(activities)
    target_h = g.hours_per_week
    if recent_h > 0:
        # Do not jump more than ~10% above recent load in week 1
        target_h = min(target_h, max(recent_h * 1.1, recent_h + 0.5))
        target_h = max(2.0, target_h)
    run_share = 0.0
    if g.run_days_per_week > 0:
        run_share = min(
            0.45,
            g.run_days_per_week
            / max(1, g.bike_days_per_week + g.run_days_per_week),
        )
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
            strength_days=g.strength_days_per_week,
            rest_weekdays=g.rest_weekdays,
            phase=phase,
            week_index=week,
            long_bike_weekday=g.long_bike_weekday,
            long_run_weekday=g.long_run_weekday,
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
            elif sport == "running":
                dur = run_durations[ri] if ri < len(run_durations) else 35 * 60
                ri += 1
                # Soften run if previous calendar day was hard bike — but keep a
                # pinned long run day as long.
                pinned_long_run = (
                    g.long_run_weekday is not None
                    and day_date.weekday() == g.long_run_weekday
                    and kind == "long"
                )
                if _prev_day_hard_bike(days) and not pinned_long_run:
                    kind = "easy"
                    dur = int(dur * 0.85)
                dist = _sized_run_distance_m(kind, dur, caps)
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
            else:
                days.append(
                    PlanDay(
                        id=f"plan-day-{day_date.isoformat()}-strength",
                        date=day_date.isoformat(),
                        sport="strength",
                        kind=kind,
                        title=_strength_title(kind),
                        duration_s=STRENGTH_DURATION_S,
                        rationale=_strength_rationale(kind, phase),
                        playable=False,
                        intensity_note=_intensity_note(kind),
                    )
                )

    days = clamp_run_volumes(
        days, start=start, weeks=g.weeks, volume_caps=caps
    )
    history_note = describe_history(activities, ftp_w=ftp)
    rest_names = _rest_day_names(g.rest_weekdays)
    strength_bit = (
        f" / {g.strength_days_per_week} strength"
        if g.strength_days_per_week
        else ""
    )
    summary = (
        f"{g.weeks}-week multi-sport plan · ~{target_h:.1f} h/week target "
        f"({g.bike_days_per_week} bike / {g.run_days_per_week} run"
        f"{strength_bit} days) · rest {rest_names} · FTP {ftp} W. "
        f"Bike sessions are ERG-ready in steadyGrind; run and strength days "
        f"are guidance (gym / outdoors)."
    )
    if g.notes:
        summary += f" Notes: {g.notes}"

    typical = load.get("typical_run_km")
    coaching = PlanCoaching(
        goal=(
            f"{g.weeks}-week “{g.goal}” block at ~{target_h:.1f} h/week "
            f"with FTP {ftp} W."
        ),
        why=(
            f"Rules planner used your recent Garmin/local load: {history_note} "
            f"Week-1 run volume is capped near ~{caps['week1_run_km_max']} km "
            f"(easy ≤ {caps['easy_run_km_max']} km"
            + (f", typical recent run ≈ {typical} km" if typical else "")
            + ") so sessions stay close to what you already run."
        ),
        expect=(
            f"After {g.weeks} weeks expect steadier indoor bike power around your "
            f"FTP zones and run durability near your current weekly kilometres — "
            f"not a sudden jump to much longer runs."
        ),
    )

    return TrainingPlan(
        id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc).isoformat(),
        ftp_w=ftp,
        goals=g,
        summary=summary,
        history_note=history_note,
        days=days,
        generator="rules",
        model=None,
        coaching=coaching,
    )


def _parse_start(value: str | None) -> date:
    """Plan weeks are Mon–Sun blocks; snap to the Monday of the start week."""
    raw = date.today()
    if value:
        try:
            raw = date.fromisoformat(value[:10])
        except ValueError:
            pass
    # Monday = 0
    return raw - timedelta(days=raw.weekday())


def _rest_day_names(rest_weekdays: list[int]) -> str:
    labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    parts = [labels[d] for d in rest_weekdays if 0 <= d <= 6]
    return ", ".join(parts) if parts else "none"


def _move_kind_to_front(kinds: list[SessionKind], kind: SessionKind) -> list[SessionKind]:
    if kind not in kinds:
        return kinds
    return [kind] + [k for k in kinds if k != kind]


def _week_pattern(
    week_start: date,
    *,
    bike_days: int,
    run_days: int,
    strength_days: int,
    rest_weekdays: list[int],
    phase: str,
    week_index: int,
    long_bike_weekday: int | None = None,
    long_run_weekday: int | None = None,
) -> list[tuple[date, str, SessionKind]]:
    """
    Assign sports across Mon–Sun weekly blocks.

    Selected rest weekdays are always rest. Bike / run / strength fill the
    remaining days; overflow becomes same-day doubles on non-rest days.
    Preferred long weekdays are placed first so the long kind lands there.
    """
    rest_set = set(rest_weekdays)
    slots: list[tuple[int, str, SessionKind] | None] = [None] * 7
    # Extra sessions that share a day with a primary (same-day doubles)
    extras: list[tuple[int, str, SessionKind]] = []

    bike_kinds = _bike_kinds_for_week(bike_days, phase=phase, week_index=week_index)
    run_kinds = _run_kinds_for_week(run_days, phase=phase)
    strength_kinds = _strength_kinds_for_week(strength_days, phase=phase)

    if long_bike_weekday is not None and long_bike_weekday not in rest_set:
        bike_kinds = _move_kind_to_front(bike_kinds, "long")
    if long_run_weekday is not None and long_run_weekday not in rest_set:
        run_kinds = _move_kind_to_front(run_kinds, "long")

    def _prefs(preferred: int | None, order: tuple[int, ...]) -> list[int]:
        out: list[int] = []
        if preferred is not None and preferred not in rest_set:
            out.append(preferred)
        for d in order:
            if d not in rest_set and d not in out:
                out.append(d)
        return out

    bike_prefs = _prefs(long_bike_weekday, (0, 2, 5, 3, 1, 6))
    run_prefs = _prefs(long_run_weekday, (1, 3, 6, 4, 0, 2))
    strength_prefs = _prefs(None, (4, 1, 3, 6, 0, 2, 5))

    bi = 0
    for dow in bike_prefs:
        if bi >= len(bike_kinds):
            break
        if slots[dow] is None:
            slots[dow] = (dow, "cycling", bike_kinds[bi])
            bi += 1

    ri = 0
    # Same-day double: preferred long-run day already has bike/strength
    if (
        long_run_weekday is not None
        and long_run_weekday not in rest_set
        and ri < len(run_kinds)
        and slots[long_run_weekday] is not None
        and slots[long_run_weekday][1] != "running"
    ):
        run_kinds = _move_kind_to_front(run_kinds, "long")
        extras.append((long_run_weekday, "running", run_kinds[ri]))
        ri += 1

    for dow in run_prefs:
        if ri >= len(run_kinds):
            break
        if slots[dow] is None:
            slots[dow] = (dow, "running", run_kinds[ri])
            ri += 1

    si = 0
    for dow in strength_prefs:
        if si >= len(strength_kinds):
            break
        if slots[dow] is None:
            slots[dow] = (dow, "strength", strength_kinds[si])
            si += 1

    # Remaining sessions → same-day doubles on non-rest hosts
    def _append_extras(
        kinds: list[SessionKind],
        sport: str,
        start_i: int,
    ) -> int:
        i = start_i
        hosts = [
            d
            for d in range(7)
            if d not in rest_set and slots[d] is not None
        ]

        def _host_key(d: int) -> tuple[int, int]:
            kind = slots[d][2] if slots[d] else "endurance"  # type: ignore[index]
            hard = 1 if kind in ("intervals", "tempo", "long") else 0
            return (hard, d)

        hosts.sort(key=_host_key)
        # Prefer empty non-rest days first if any remain
        empty = [d for d in range(7) if d not in rest_set and slots[d] is None]
        for dow in empty:
            if i >= len(kinds):
                break
            slots[dow] = (dow, sport, kinds[i])
            i += 1
        # Then double onto existing sessions (one extra per host pass, then again)
        while i < len(kinds):
            placed = False
            for dow in hosts:
                if i >= len(kinds):
                    break
                extras.append((dow, sport, kinds[i]))
                i += 1
                placed = True
            if not placed:
                # No host days at all (all rest?) — force onto first non-rest or Mon
                fallback = next((d for d in range(7) if d not in rest_set), 0)
                while i < len(kinds):
                    extras.append((fallback, sport, kinds[i]))
                    i += 1
                break
        return i

    bi = _append_extras(bike_kinds, "cycling", bi)
    ri = _append_extras(run_kinds, "running", ri)
    si = _append_extras(strength_kinds, "strength", si)

    out: list[tuple[date, str, SessionKind]] = []
    for dow in range(7):
        day = week_start + timedelta(days=dow)
        # Hard constraint: selected rest weekdays are always rest only
        if dow in rest_set:
            out.append((day, "rest", "rest"))
            continue
        day_extras = [(s, k) for d, s, k in extras if d == dow]
        # Morning-first: run, strength, then primary bike/run/strength
        for sport, kind in sorted(
            day_extras,
            key=lambda sk: 0 if sk[0] == "running" else 1 if sk[0] == "strength" else 2,
        ):
            out.append((day, sport, kind))
        if slots[dow] is None and not day_extras:
            out.append((day, "rest", "rest"))
        elif slots[dow] is not None:
            _, sport, kind = slots[dow]
            out.append((day, sport, kind))
    out = _pin_long_sessions(
        out,
        long_bike_weekday=long_bike_weekday,
        long_run_weekday=long_run_weekday,
        rest_set=rest_set,
    )
    return out


def _pin_long_sessions(
    pattern: list[tuple[date, str, SessionKind]],
    *,
    long_bike_weekday: int | None,
    long_run_weekday: int | None,
    rest_set: set[int],
) -> list[tuple[date, str, SessionKind]]:
    """Swap kinds so cycling/running long lands on the preferred weekday."""
    rows = list(pattern)

    def _pin(sport: str, preferred: int | None, soft_kind: SessionKind) -> None:
        if preferred is None or preferred in rest_set:
            return
        sport_idxs = [i for i, (_d, s, _k) in enumerate(rows) if s == sport]
        if not sport_idxs:
            return
        preferred_idxs = [
            i
            for i in sport_idxs
            if rows[i][0].weekday() == preferred
        ]
        long_idxs = [i for i in sport_idxs if rows[i][2] == "long"]
        if not preferred_idxs:
            return
        target = preferred_idxs[0]
        if rows[target][2] == "long":
            # Demote any other long of this sport
            for i in long_idxs:
                if i != target:
                    d, s, _ = rows[i]
                    rows[i] = (d, s, soft_kind)
            return
        if long_idxs:
            src = long_idxs[0]
            d_t, s_t, k_t = rows[target]
            d_s, s_s, _k_s = rows[src]
            rows[target] = (d_t, s_t, "long")
            rows[src] = (d_s, s_s, k_t if k_t != "long" else soft_kind)
        else:
            d_t, s_t, _ = rows[target]
            rows[target] = (d_t, s_t, "long")

    _pin("cycling", long_bike_weekday, "endurance")
    _pin("running", long_run_weekday, "easy")
    return rows


def bike_week_mix_ok(
    kinds: list[str],
    n: int,
    *,
    week_index: int = 0,
    phase: str = "build",
) -> bool:
    """True when bike kinds match the Z2 / intervals / threshold recipe."""
    if n <= 0:
        return True
    if len(kinds) != n:
        return False
    tempos = sum(1 for k in kinds if k == "tempo")
    if tempos > 1:
        return False
    z2 = sum(1 for k in kinds if k in ("endurance", "long", "recovery"))
    intervals = sum(1 for k in kinds if k == "intervals")
    longs = sum(1 for k in kinds if k == "long")
    if phase in ("deload", "taper"):
        return tempos <= 1 and z2 >= max(1, n - 1)
    if n == 1:
        return z2 >= 1
    if n == 2:
        hard = intervals + tempos
        return z2 >= 1 and hard >= 1
    if n == 3:
        return intervals >= 1 and tempos >= 1 and longs >= 1
    return (
        sum(1 for k in kinds if k == "endurance") >= 1
        and intervals >= 1
        and tempos <= 1
        and longs == 1
    )


def _bike_kinds_for_week(
    n: int, *, phase: str, week_index: int
) -> list[SessionKind]:
    """Weekly bike mix: Z2 (endurance/long), intervals, and at most one tempo."""
    if n <= 0:
        return []
    if phase in ("deload", "taper"):
        if n == 1:
            return ["recovery"]
        if n == 2:
            return ["recovery", "endurance"]
        kinds: list[SessionKind] = ["recovery", "endurance", "tempo"]
        while len(kinds) < n:
            kinds.append("endurance")
        kinds[-1] = "long"
        # Keep a single tempo
        seen_tempo = False
        cleaned: list[SessionKind] = []
        for k in kinds[:n]:
            if k == "tempo":
                if seen_tempo:
                    cleaned.append("endurance")
                else:
                    cleaned.append("tempo")
                    seen_tempo = True
            else:
                cleaned.append(k)
        if n >= 3:
            cleaned[-1] = "long"
        return cleaned[:n]

    if n == 1:
        return ["endurance"]
    if n == 2:
        hard: SessionKind = "intervals" if week_index % 2 == 0 else "tempo"
        return ["long", hard]
    if n == 3:
        return ["intervals", "tempo", "long"]
    # 4+: endurance + intervals + tempo + long, fill with endurance
    kinds = ["endurance", "intervals", "tempo", "long"]
    while len(kinds) < n:
        kinds.insert(-1, "endurance")
    return kinds[:n]


def _run_kinds_for_week(n: int, *, phase: str) -> list[SessionKind]:
    if n <= 0:
        return []
    if phase in ("deload", "taper"):
        base: list[SessionKind] = ["easy", "easy", "long", "easy", "easy"]
    else:
        base = ["easy", "tempo", "long", "easy", "easy"]
    kinds = base[:n]
    if n >= 2 and phase not in ("deload", "taper"):
        kinds[0] = "easy"
        if n >= 3:
            kinds[1] = "tempo"
            kinds[2] = "long"
        else:
            kinds[1] = "long"
    return kinds


def _strength_kinds_for_week(n: int, *, phase: str) -> list[SessionKind]:
    if n <= 0:
        return []
    if phase in ("deload", "taper"):
        base: list[SessionKind] = ["mobility", "full_body", "core", "upper"]
    else:
        base = ["full_body", "lower", "upper", "core"]
    return base[:n]


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


def _sized_run_distance_m(
    kind: SessionKind, duration_s: int, caps: dict
) -> int:
    """Estimate distance then clamp to history-based per-session caps."""
    raw = run_distance_m(kind, duration_s)
    km = raw / 1000.0
    if kind == "long":
        cap = float(caps.get("long_run_km_max") or 10)
    elif kind in ("tempo", "intervals"):
        cap = float(caps.get("tempo_run_km_max") or 8)
    else:
        cap = float(caps.get("easy_run_km_max") or 7)
    return int(min(km, cap) * 1000)


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


def _strength_title(kind: SessionKind) -> str:
    return {
        "full_body": "Strength · full body",
        "upper": "Strength · upper",
        "lower": "Strength · lower",
        "core": "Strength · core",
        "mobility": "Strength · mobility",
    }.get(kind, "Strength · gym")


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


def _strength_rationale(kind: SessionKind, phase: str) -> str:
    base = {
        "full_body": "Gym full-body strength — compound lifts, leave legs fresh for hard bikes.",
        "upper": "Upper-body focus; keep legs light before key rides.",
        "lower": "Lower-body strength; avoid the day before VO2 / long rides.",
        "core": "Core stability for posture on the bike.",
        "mobility": "Mobility and light strength — recovery-friendly.",
    }.get(kind, "Gym / strength session (guidance — not on the trainer).")
    if phase in ("deload", "taper"):
        return base + f" ({phase} week — keep loads moderate)."
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
        "full_body": "Moderate gym",
        "upper": "Moderate gym",
        "lower": "Moderate gym",
        "core": "Easy–moderate",
        "mobility": "Easy",
    }.get(kind, "Moderate")
