"""Persist the active training plan in SQLite via Repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

from steadygrind.plan.models import TrainingPlan

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


def get_plan_day(repo: Repository, day_id: str) -> dict | None:
    plan = load_plan(repo)
    if plan is None:
        return None
    for day in plan.days:
        if day.id == day_id:
            return day.to_workout_dict()
    return None
