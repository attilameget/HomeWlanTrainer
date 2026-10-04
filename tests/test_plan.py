"""Unit tests for on-host multi-sport plan generator."""

from __future__ import annotations

from kickr_pi.plan.generator import generate_plan
from kickr_pi.plan.history import merge_history, normalize_garmin_activity, weekly_hours
from kickr_pi.plan.models import ActivitySummary, PlanGoals


def test_generate_plan_includes_bike_and_run() -> None:
    plan = generate_plan(
        PlanGoals(weeks=2, hours_per_week=6, bike_days_per_week=3, run_days_per_week=2),
        ftp_w=220,
        activities=[],
    )
    assert plan.ftp_w == 220
    assert len(plan.days) == 14
    sports = {d.sport for d in plan.days}
    assert "cycling" in sports
    assert "running" in sports
    assert "rest" in sports
    bike = [d for d in plan.days if d.sport == "cycling"]
    assert all(d.playable and d.stages for d in bike)
    runs = [d for d in plan.days if d.sport == "running"]
    assert all(not d.playable for d in runs)
    assert all(d.distance_m and d.distance_m > 0 for d in runs)


def test_generate_plan_honors_high_run_count_with_doubles() -> None:
    plan = generate_plan(
        PlanGoals(
            weeks=1,
            hours_per_week=10,
            bike_days_per_week=5,
            run_days_per_week=4,
            notes="Runs on the morning, bikes on the afternoon.",
        ),
        ftp_w=200,
        activities=[],
    )
    assert plan.goals.run_days_per_week == 4
    assert plan.goals.bike_days_per_week == 5
    bikes = [d for d in plan.days if d.sport == "cycling"]
    runs = [d for d in plan.days if d.sport == "running"]
    assert len(bikes) == 5
    assert len(runs) == 4
    # At least one calendar date hosts both sports
    bike_dates = {d.date for d in bikes}
    run_dates = {d.date for d in runs}
    assert bike_dates & run_dates


def test_generate_plan_uses_requested_hours_without_recent_load() -> None:
    acts = [
        ActivitySummary(
            id="1",
            sport="cycling",
            started_at="2020-01-01T10:00:00+00:00",
            duration_s=3600,
        )
    ]
    plan = generate_plan(
        PlanGoals(weeks=1, hours_per_week=12, bike_days_per_week=4, run_days_per_week=0),
        ftp_w=200,
        activities=acts,
    )
    assert "12.0" in plan.summary

def test_normalize_garmin_running_and_cycling() -> None:
    run = normalize_garmin_activity(
        {
            "activityId": 11,
            "activityName": "Morning Run",
            "startTimeLocal": "2026-09-01T07:00:00",
            "duration": 2400,
            "distance": 8000,
            "activityType": {"typeKey": "running", "typeId": 1},
        }
    )
    bike = normalize_garmin_activity(
        {
            "activityId": 12,
            "activityName": "Indoor",
            "startTimeLocal": "2026-09-02T07:00:00",
            "duration": 3600,
            "averagePower": 180,
            "activityType": {"typeKey": "indoor_cycling", "typeId": 2},
        }
    )
    assert run is not None and run.sport == "running"
    assert bike is not None and bike.sport == "cycling" and bike.avg_power_w == 180


def test_merge_history_includes_local_rides() -> None:
    merged = merge_history(
        [],
        [
            {
                "id": "abc",
                "started_at": "2026-09-28T12:00:00+00:00",
                "duration_s": 1800,
                "avg_power_w": 150,
                "workout_name": "Manual",
            }
        ],
        lookback_days=60,
    )
    assert len(merged) == 1
    assert merged[0].source == "local"
    assert weekly_hours(merged, sport="cycling") >= 0


def test_bike_stages_have_erg_targets() -> None:
    plan = generate_plan(
        PlanGoals(weeks=2, bike_days_per_week=3, run_days_per_week=1, hours_per_week=5),
        ftp_w=250,
    )
    quality = next(
        d
        for d in plan.days
        if d.sport == "cycling" and d.kind in ("intervals", "tempo")
    )
    erg = [s for s in quality.stages if s.get("target_mode") == "erg"]
    assert erg
    assert any((s.get("target_w") or 0) >= int(250 * 0.8) for s in erg)


def test_generate_plan_honors_rest_weekdays() -> None:
    # Wed=2, Sat=5
    plan = generate_plan(
        PlanGoals(
            weeks=1,
            hours_per_week=6,
            bike_days_per_week=3,
            run_days_per_week=1,
            strength_days_per_week=0,
            rest_weekdays=[2, 5],
            start_date="2026-10-05",  # Monday
        ),
        ftp_w=200,
        activities=[],
    )
    by_date = {}
    for d in plan.days:
        by_date.setdefault(d.date, []).append(d.sport)
    # Wednesday 2026-10-07 and Saturday 2026-10-10 must be rest-only
    assert by_date["2026-10-07"] == ["rest"]
    assert by_date["2026-10-10"] == ["rest"]
    assert sum(1 for d in plan.days if d.sport == "cycling") == 3
    assert sum(1 for d in plan.days if d.sport == "running") == 1


def test_generate_plan_includes_strength_guidance() -> None:
    plan = generate_plan(
        PlanGoals(
            weeks=1,
            hours_per_week=7,
            bike_days_per_week=3,
            run_days_per_week=1,
            strength_days_per_week=2,
            rest_weekdays=[6],  # Sunday only
            start_date="2026-10-05",
        ),
        ftp_w=210,
        activities=[],
    )
    strength = [d for d in plan.days if d.sport == "strength"]
    assert len(strength) == 2
    assert all(not d.playable and d.duration_s > 0 for d in strength)
    assert all("Strength" in d.title for d in strength)
    # Sunday rest
    sunday = [d for d in plan.days if d.date == "2026-10-11"]
    assert sunday and all(d.sport == "rest" for d in sunday)


def test_clamp_rest_weekdays_defaults_and_caps() -> None:
    g = PlanGoals(rest_weekdays=[]).clamp()
    assert g.rest_weekdays == [4, 6]
    g2 = PlanGoals(rest_weekdays=[0, 1, 2, 3, 4, 5, 6]).clamp()
    assert len(g2.rest_weekdays) == 6
    assert 2 not in g2.rest_weekdays  # Wednesday dropped first
