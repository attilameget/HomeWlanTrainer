"""Garmin WorkoutSource interface and parser."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from steadygrind.engine.models import Stage, Workout


@dataclass(frozen=True)
class WorkoutSummary:
    id: str
    name: str
    sport: str
    duration_s: int | None = None
    scheduled_date: str | None = None
    source: str = "garmin"


@runtime_checkable
class WorkoutSource(Protocol):
    async def login(
        self, email: str, password: str, mfa: str | None = None
    ) -> None: ...

    async def todays_workouts(self) -> list[WorkoutSummary]: ...

    async def library(self) -> list[WorkoutSummary]: ...

    async def get_workout(self, source_id: str) -> dict[str, Any]: ...

    @property
    def authenticated(self) -> bool: ...


class LocalDemoSource:
    """Offline source that only exposes the demo workout (Phase A without Garmin)."""

    def __init__(self, ftp_w: int = 200) -> None:
        self._ftp_w = ftp_w
        self._authenticated = True

    @property
    def authenticated(self) -> bool:
        return self._authenticated

    async def login(
        self, email: str, password: str, mfa: str | None = None
    ) -> None:
        self._authenticated = True

    async def todays_workouts(self) -> list[WorkoutSummary]:
        return [
            WorkoutSummary(
                id="demo-1",
                name="Demo Intervals",
                sport="cycling",
                duration_s=315,
                scheduled_date=None,
                source="local",
            )
        ]

    async def library(self) -> list[WorkoutSummary]:
        return await self.todays_workouts()

    async def get_workout(self, source_id: str) -> dict[str, Any]:
        from steadygrind.engine.models import demo_workout

        w = demo_workout(self._ftp_w)
        return {
            "id": w.id,
            "name": w.name,
            "sport": w.sport,
            "stages": [s.__dict__ for s in w.stages],
        }


def parse_garmin_workout(
    raw: dict[str, Any],
    *,
    ftp_w: int,
    power_zones: list[float] | None = None,
) -> Workout:
    """
    Parse a Garmin workout JSON into a flat Stage list.

    Accepts either already-normalized stages (local demo) or a Garmin-like
    tree with workoutSegments / workoutSteps / repeat steps.
    """
    if "stages" in raw and isinstance(raw["stages"], list):
        stages = [_stage_from_dict(s, i) for i, s in enumerate(raw["stages"])]
        return Workout(
            id=str(raw.get("id") or raw.get("workoutId") or "unknown"),
            name=str(raw.get("name") or raw.get("workoutName") or "Workout"),
            sport=str(raw.get("sport") or "cycling"),
            stages=stages,
            source=str(raw.get("source") or "garmin"),
            source_id=str(raw.get("source_id") or raw.get("workoutId") or ""),
        )

    zones = power_zones or [0.45, 0.55, 0.65, 0.75, 0.87, 1.05, 1.25]
    stages: list[Stage] = []
    segments = raw.get("workoutSegments") or raw.get("segments") or []
    for segment in segments:
        steps = segment.get("workoutSteps") or segment.get("steps") or []
        _expand_steps(steps, stages, ftp_w=ftp_w, zones=zones)

    return Workout(
        id=str(raw.get("workoutId") or raw.get("id") or "unknown"),
        name=str(raw.get("workoutName") or raw.get("name") or "Workout"),
        sport=_sport_name(raw.get("sportType") or raw.get("sport")),
        stages=stages,
        source="garmin",
        source_id=str(raw.get("workoutId") or ""),
    )


def _expand_steps(
    steps: list[dict[str, Any]],
    out: list[Stage],
    *,
    ftp_w: int,
    zones: list[float],
    repeat: int = 1,
) -> None:
    for _ in range(repeat):
        for step in steps:
            stype = str(step.get("type") or step.get("stepType") or "").lower()
            if "repeat" in stype or step.get("numberOfIterations"):
                iterations = int(step.get("numberOfIterations") or step.get("repeatValue") or 1)
                child = step.get("steps") or step.get("workoutSteps") or []
                _expand_steps(child, out, ftp_w=ftp_w, zones=zones, repeat=iterations)
                continue
            out.append(_parse_step(step, len(out), ftp_w=ftp_w, zones=zones))


def _parse_step(
    step: dict[str, Any], index: int, *, ftp_w: int, zones: list[float]
) -> Stage:
    step_key = _step_type_key(step)
    name = str(
        step.get("description")
        or step.get("intensity")
        or step_key
        or f"Step {index + 1}"
    )
    kind = _map_kind(step)
    duration_s, open_ended = _map_duration(step)
    target_mode, target_w, start_w, end_w, resistance = _map_target(
        step, ftp_w=ftp_w, zones=zones
    )
    return Stage(
        index=index,
        name=name.title() if name == step_key else name,
        kind=kind,
        duration_s=None if open_ended else duration_s,
        target_mode=target_mode,
        target_w=target_w,
        start_w=start_w,
        end_w=end_w,
        resistance_pct=resistance,
        note=step.get("description"),
    )


def _step_type_key(step: dict[str, Any]) -> str:
    raw = step.get("stepType") or step.get("type")
    if isinstance(raw, dict):
        return str(raw.get("stepTypeKey") or raw.get("typeKey") or "").lower()
    return str(raw or "").lower()


def _map_kind(step: dict[str, Any]) -> str:
    intensity = str(
        step.get("intensity") or step.get("intensityType") or _step_type_key(step)
    ).lower()
    mapping = {
        "warmup": "warmup",
        "warm_up": "warmup",
        "cooldown": "cooldown",
        "cool_down": "cooldown",
        "recovery": "recovery",
        "rest": "rest",
        "interval": "interval",
        "active": "interval",
    }
    for key, value in mapping.items():
        if key in intensity:
            return value
    return "interval"


def _map_duration(step: dict[str, Any]) -> tuple[int, bool]:
    end_cond = step.get("endCondition")
    if isinstance(end_cond, dict):
        dtype = str(end_cond.get("conditionTypeKey") or end_cond.get("typeKey") or "").lower()
    else:
        dtype = str(step.get("durationType") or end_cond or "time").lower()
    if "lap" in dtype or "button" in dtype:
        return 0, True
    value = (
        step.get("durationValue")
        or step.get("endConditionValue")
        or step.get("duration")
    )
    if value is None:
        return 60, False
    return int(float(value)), False


def _target_type_key(step: dict[str, Any]) -> str:
    raw = step.get("targetType") or step.get("targetTypeKey")
    if isinstance(raw, dict):
        return str(
            raw.get("workoutTargetTypeKey") or raw.get("typeKey") or raw.get("key") or ""
        ).lower()
    return str(raw or "").lower()


def _map_target(
    step: dict[str, Any], *, ftp_w: int, zones: list[float]
) -> tuple[str, int | None, int | None, int | None, int | None]:
    ttype = _target_type_key(step)
    low = (
        step.get("targetValue")
        or step.get("targetValueLow")
        or step.get("targetValueOne")
    )
    high = (
        step.get("targetValueHigh")
        or step.get("secondaryTargetValue")
        or step.get("targetValueTwo")
    )

    # Garmin Coach often labels watt ranges as power.zone with absolute watts
    if "power" in ttype and "zone" in ttype:
        if low is not None and float(low) > 10:
            lo = int(float(low))
            if high is not None and abs(float(high) - lo) > 5:
                mid = int((lo + int(float(high))) / 2)
                return "erg", mid, None, None, None
            return "erg", lo, None, None, None
        zone = int(low or step.get("zoneNumber") or 3)
        pct = zones[min(max(zone - 1, 0), len(zones) - 1)]
        return "erg", int(ftp_w * pct), None, None, None

    if "percent" in ttype or "%ftp" in ttype or "ftp" in ttype:
        lo = float(low or 50) / 100.0
        if high is not None:
            hi = float(high) / 100.0
            return "erg", int(ftp_w * ((lo + hi) / 2)), None, None, None
        return "erg", int(ftp_w * lo), None, None, None

    if "watt" in ttype or ttype in ("power", "power.custom"):
        lo = int(float(low or 100))
        if high is not None and abs(float(high) - lo) > 5:
            return "erg", int((lo + int(float(high))) / 2), None, None, None
        return "erg", lo, None, None, None

    if "cadence" in ttype or "heart" in ttype or "hr" in ttype:
        return "resistance", None, None, None, 20

    if not ttype or "open" in ttype or "no.target" in ttype:
        return "resistance", None, None, None, 20

    return "erg", int(ftp_w * 0.6), None, None, None


def _sport_name(raw: Any) -> str:
    if raw is None:
        return "cycling"
    if isinstance(raw, dict):
        return str(raw.get("sportTypeKey") or raw.get("typeKey") or "cycling")
    return str(raw)


def _stage_from_dict(data: dict[str, Any], index: int) -> Stage:
    return Stage(
        index=int(data.get("index", index)),
        name=str(data.get("name") or f"Stage {index + 1}"),
        kind=data.get("kind") or "interval",  # type: ignore[arg-type]
        duration_s=data.get("duration_s"),
        target_mode=data.get("target_mode") or "erg",  # type: ignore[arg-type]
        target_w=data.get("target_w"),
        start_w=data.get("start_w"),
        end_w=data.get("end_w"),
        resistance_pct=data.get("resistance_pct"),
        cadence_hint=data.get("cadence_hint"),
        note=data.get("note"),
    )
