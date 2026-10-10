"""History load profile and run-volume caps for plan generation."""

from __future__ import annotations

from steadygrind.plan.history import build_load_profile
from steadygrind.plan.models import ActivitySummary
from steadygrind.plan.sketch import clamp_run_volumes, materialize_days
from datetime import date, timedelta


def _run(km: float, day: str) -> ActivitySummary:
    return ActivitySummary(
        id=f"r-{day}",
        sport="running",
        started_at=f"{day}T07:00:00+00:00",
        duration_s=35 * 60,
        distance_m=km * 1000,
        name="Easy",
        source="garmin",
    )


def test_load_profile_caps_near_typical_6_7km_runs() -> None:
    # Four ~6.5 km runs in the last week → caps must stay near that, not 14 km
    today = date.today()
    acts = [
        _run(6.2, (today - timedelta(days=1)).isoformat()),
        _run(6.8, (today - timedelta(days=2)).isoformat()),
        _run(7.0, (today - timedelta(days=4)).isoformat()),
        _run(6.5, (today - timedelta(days=6)).isoformat()),
    ]
    profile = build_load_profile(acts, ftp_w=240)
    caps = profile["volume_caps"]
    assert profile["ftp_w"] == 240
    assert profile["typical_run_km"] is not None
    assert 6.0 <= profile["typical_run_km"] <= 7.2
    assert caps["easy_run_km_max"] <= 8.5
    assert caps["long_run_km_max"] <= 11.0
    assert caps["week1_run_km_max"] <= 35.0


def test_clamp_run_volumes_cuts_oversized_claude_runs() -> None:
    start = date(2026, 10, 5)  # Monday
    days = materialize_days(
        [
            {
                "date": start.isoformat(),
                "sport": "running",
                "kind": "easy",
                "title": "Easy",
                "duration_min": 55,
                "distance_km": 10.5,
                "rationale": "too long",
            },
            {
                "date": (start + timedelta(days=2)).isoformat(),
                "sport": "running",
                "kind": "long",
                "title": "Long",
                "duration_min": 80,
                "distance_km": 14.0,
                "rationale": "way too long",
            },
        ],
        start=start,
        end=start + timedelta(days=6),
        ftp_w=200,
    )
    caps = {
        "easy_run_km_max": 7.0,
        "tempo_run_km_max": 7.5,
        "long_run_km_max": 9.0,
        "week1_run_km_max": 20.0,
    }
    clamped = clamp_run_volumes(days, start=start, weeks=1, volume_caps=caps)
    runs = [d for d in clamped if d.sport == "running"]
    assert len(runs) == 2
    assert (runs[0].distance_m or 0) / 1000 <= 7.01
    assert (runs[1].distance_m or 0) / 1000 <= 9.01
    assert sum((d.distance_m or 0) for d in runs) / 1000 <= 20.01


def test_materialize_honors_distance_km() -> None:
    start = date(2026, 10, 5)
    days = materialize_days(
        [
            {
                "date": start.isoformat(),
                "sport": "running",
                "kind": "easy",
                "title": "Easy 6.5",
                "duration_min": 90,
                "distance_km": 6.5,
                "rationale": "match history",
            }
        ],
        start=start,
        end=start,
        ftp_w=200,
    )
    run = days[0]
    assert run.sport == "running"
    assert abs((run.distance_m or 0) / 1000 - 6.5) < 0.05
    # Duration must not stay at 90 min (which would imply ~14 km at easy pace)
    assert run.duration_s < 70 * 60
