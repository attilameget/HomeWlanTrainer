"""Plan form recovers from the active plan when quit stored factory defaults."""

from __future__ import annotations

from steadygrind.config import Settings
from steadygrind.plan.models import PlanGoals, TrainingPlan
from steadygrind.plan.store import plan_form_is_factory, recover_plan_form_settings


def _plan() -> TrainingPlan:
    return TrainingPlan(
        id="p1",
        created_at="2026-10-10T00:00:00Z",
        ftp_w=200,
        goals=PlanGoals(
            weeks=8,
            hours_per_week=9,
            bike_days_per_week=4,
            run_days_per_week=1,
            strength_days_per_week=1,
            rest_weekdays=[0, 3],
            goal="event",
            notes="mornings",
        ),
        summary="",
        history_note="",
    )


def test_factory_settings_recover_from_the_active_plan() -> None:
    settings = Settings()
    saved = {
        "plan_weeks": 4,
        "plan_hours_per_week": 6.0,
        "plan_bike_days_per_week": 3,
        "plan_run_days_per_week": 2,
        "plan_strength_days_per_week": 0,
        "plan_rest_weekdays": [4, 6],
        "plan_goal": "general",
        "plan_notes": "",
    }
    assert plan_form_is_factory(saved)
    assert recover_plan_form_settings(settings, saved, _plan())
    assert settings.plan_hours_per_week == 9
    assert settings.plan_bike_days_per_week == 4
    assert settings.plan_run_days_per_week == 1
    assert settings.plan_strength_days_per_week == 1
    assert settings.plan_rest_weekdays == [0, 3]
    assert settings.plan_weeks == 8
    assert settings.plan_form_saved is True


def test_saved_form_is_not_replaced_by_the_plan() -> None:
    settings = Settings()
    settings.plan_hours_per_week = 6
    saved = {"plan_form_saved": True, "plan_hours_per_week": 6.0}
    assert not recover_plan_form_settings(settings, saved, _plan())
    assert settings.plan_hours_per_week == 6


def test_custom_form_without_the_flag_is_kept() -> None:
    settings = Settings()
    settings.plan_hours_per_week = 7
    saved = {"plan_hours_per_week": 7.0}
    assert not plan_form_is_factory(saved)
    assert not recover_plan_form_settings(settings, saved, _plan())
    assert settings.plan_hours_per_week == 7
