"""In-memory ride recording produced by the workout engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class RideSample:
    elapsed_s: float
    power_w: int
    cadence_rpm: float
    speed_kph: float
    heart_rate_bpm: int | None
    target_w: int


@dataclass
class RideRecording:
    started_at: datetime
    ended_at: datetime
    duration_s: float
    avg_power_w: int | None
    workout_name: str | None
    samples: list[RideSample] = field(default_factory=list)
