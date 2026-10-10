"""Persist the active training plan in SQLite via Repository."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from steadygrind.plan.models import PlanGoals, TrainingPlan

if TYPE_CHECKING:
    from steadygrind.storage.repository import Repository


ACTIVE_PLAN_KEY = "active_training_plan"


def save_plan(repo: Repository, plan: TrainingPlan) -> None:
    repo.save_training_plan(plan.to_dict())


def load_plan(repo: Repository) -> TrainingPlan | None:
    data = repo.get_training_plan()
    if not data:
        return None
    return TrainingPlan.from_dict(data)


def clear_plan(repo: Repository) -> None:
    repo.clear_training_plan()


# Factory Plan form. A quit used to write these before the form had loaded,
# which hid the hours, session counts, and rest days on the active plan.
_FACTORY_PLAN_FORM: dict[str, Any] = {
    "plan_weeks": 4,
    "plan_hours_per_week": 6.0,
    "plan_bike_days_per_week": 3,
    "plan_run_days_per_week": 2,
    "plan_strength_days_per_week": 0,
    "plan_rest_weekdays": [4, 6],
    "plan_goal": "general",
    "plan_notes": "",
}


def plan_form_settings_from_goals(goals: PlanGoals) -> dict[str, Any]:
    """Settings keys that restore the Plan generate form."""
    g = goals.clamp()
    return {
        "plan_weeks": int(g.weeks),
        "plan_hours_per_week": float(g.hours_per_week),
        "plan_bike_days_per_week": int(g.bike_days_per_week),
        "plan_run_days_per_week": int(g.run_days_per_week),
        "plan_strength_days_per_week": int(g.strength_days_per_week),
        "plan_rest_weekdays": list(g.rest_weekdays),
        "plan_goal": str(g.goal or "general"),
        "plan_notes": str(g.notes or ""),
        "plan_form_saved": True,
    }


def plan_form_is_factory(saved: dict[str, Any]) -> bool:
    """True when stored plan_* values are missing or still the factory form."""
    for key, default in _FACTORY_PLAN_FORM.items():
        current = saved.get(key, default)
        if key == "plan_hours_per_week":
            try:
                if float(current) != float(default):
                    return False
            except (TypeError, ValueError):
                return False
        elif key == "plan_rest_weekdays":
            days = list(current) if isinstance(current, list) else list(default)
            if days != list(default):
                return False
        elif key == "plan_notes":
            if str(current or "") != "":
                return False
        else:
            if current != default:
                return False
    return True


def recover_plan_form_settings(
    settings: Any, saved: dict[str, Any], plan: TrainingPlan | None
) -> bool:
    """Copy the active plan's goals onto settings when the form was never saved.

    Returns True when ``settings`` changed and should be written back.
    A form the rider already saved (``plan_form_saved``) is left alone, as is
    a form that already differs from the factory defaults.
    """
    if saved.get("plan_form_saved"):
        return False
    if plan is None or not plan_form_is_factory(saved):
        return False
    for key, value in plan_form_settings_from_goals(plan.goals).items():
        setattr(settings, key, value)
    return True


def get_plan_day(repo: Repository, day_id: str) -> dict | None:
    plan = load_plan(repo)
    if plan is None:
        return None
    for day in plan.days:
        if day.id == day_id:
            return day.to_workout_dict()
    return None
