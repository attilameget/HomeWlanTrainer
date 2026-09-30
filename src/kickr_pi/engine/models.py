"""Workout domain models and engine state machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class EngineState(str, Enum):
    IDLE = "idle"
    LOADED = "loaded"
    RUNNING = "running"
    PAUSED = "paused"
    RECONNECTING = "reconnecting"
    FINISHED = "finished"


StageKind = Literal["warmup", "interval", "recovery", "rest", "cooldown", "free"]
TargetMode = Literal["erg", "ramp", "resistance"]


@dataclass
class Stage:
    index: int
    name: str
    kind: StageKind
    duration_s: int | None  # None = open-ended
    target_mode: TargetMode
    target_w: int | None = None
    start_w: int | None = None
    end_w: int | None = None
    resistance_pct: int | None = None
    cadence_hint: int | None = None
    note: str | None = None


@dataclass
class Workout:
    id: str
    name: str
    sport: str
    stages: list[Stage]
    source: str = "local"
    source_id: str | None = None
    scheduled_date: str | None = None
    total_s: int = 0

    def __post_init__(self) -> None:
        if not self.total_s:
            self.total_s = sum(s.duration_s or 0 for s in self.stages)


@dataclass
class LiveState:
    engine_state: EngineState = EngineState.IDLE
    workout_id: str | None = None
    workout_name: str | None = None
    stage_index: int = 0
    stage_name: str = ""
    stage_count: int = 0
    stage_elapsed_s: float = 0.0
    stage_remaining_s: float | None = None
    total_elapsed_s: float = 0.0
    total_remaining_s: float | None = None
    target_w: int = 0
    power_w: int = 0
    cadence_rpm: float = 0.0
    speed_kph: float = 0.0
    intensity_pct: int = 100
    next_stage_name: str | None = None
    trainer_connected: bool = False
    garmin_ok: bool = False
    message: str | None = None


def demo_workout(ftp_w: int = 200) -> Workout:
    """Hard-coded workout for engine testing without Garmin."""
    stages = [
        Stage(0, "Warm-up", "warmup", 60, "ramp", start_w=int(ftp_w * 0.4), end_w=int(ftp_w * 0.6)),
        Stage(1, "Steady", "interval", 90, "erg", target_w=int(ftp_w * 0.75)),
        Stage(2, "Recovery", "recovery", 45, "erg", target_w=int(ftp_w * 0.5)),
        Stage(3, "Hard", "interval", 60, "erg", target_w=int(ftp_w * 0.95)),
        Stage(4, "Cool-down", "cooldown", 60, "ramp", start_w=int(ftp_w * 0.55), end_w=int(ftp_w * 0.35)),
    ]
    return Workout(id="demo-1", name="Demo Intervals", sport="cycling", stages=stages)
