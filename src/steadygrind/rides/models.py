"""In-memory ride recording produced by the workout engine."""

from __future__ import annotations

import math
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
    kcal: int | None = None
    distance_m: float | None = None
    ascent_m: float | None = None


def ascent_from_distance_m(distance_m: float, incline_pct: float) -> float:
    """Vertical rise for a distance at a constant grade (metres)."""
    if distance_m <= 0 or incline_pct <= 0:
        return 0.0
    grade = float(incline_pct) / 100.0
    return float(distance_m) * math.sin(math.atan(grade))


def estimate_kcal(
    *,
    samples: list[RideSample] | None = None,
    avg_power_w: int | None = None,
    duration_s: float | None = None,
) -> int | None:
    """Estimate kilocalories from work (1 kJ ≈ 1 kcal, common indoor-bike rule)."""
    rows = samples or []
    if len(rows) >= 2:
        joules = 0.0
        for prev, cur in zip(rows, rows[1:]):
            dt = max(0.0, float(cur.elapsed_s) - float(prev.elapsed_s))
            joules += max(0, int(prev.power_w)) * dt
        # Carry the last sample to the recorded duration when available.
        if duration_s is not None and duration_s > rows[-1].elapsed_s:
            joules += max(0, int(rows[-1].power_w)) * (
                float(duration_s) - float(rows[-1].elapsed_s)
            )
        return max(0, int(round(joules / 1000.0)))
    if avg_power_w is not None and duration_s is not None and duration_s > 0:
        return max(0, int(round(float(avg_power_w) * float(duration_s) / 1000.0)))
    return None
