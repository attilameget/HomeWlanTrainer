"""Plan generation orchestration: Claude with rules fallback + post-ride refresh."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from kickr_pi.plan.claude import (
    ClaudeError,
    api_key_configured,
    generate_plan_via_claude,
)
from kickr_pi.plan.generator import generate_plan
from kickr_pi.plan.history import merge_history
from kickr_pi.plan.models import PlanGoals, TrainingPlan
from kickr_pi.plan.store import load_plan, save_plan

logger = logging.getLogger(__name__)

LONG_RIDE_MIN_S = 30 * 60
AUTO_PLAN_WEEKS = 1


async def build_plan(
    *,
    goals: PlanGoals,
    ftp_w: int,
    activities: list[Any],
    anthropic_api_key: str,
    anthropic_model: str,
) -> TrainingPlan:
    """Try Claude when an API key is set; always fall back to on-host rules."""
    if api_key_configured(anthropic_api_key):
        try:
            plan = await generate_plan_via_claude(
                goals,
                ftp_w=ftp_w,
                activities=activities,
                api_key=anthropic_api_key,
                model=anthropic_model,
            )
            logger.info(
                "plan generated via Claude model=%s days=%s",
                anthropic_model,
                len(plan.days),
            )
            return plan
        except ClaudeError as exc:
            logger.warning("Claude plan failed, using rules: %s", exc)
            plan = generate_plan(goals, ftp_w=ftp_w, activities=activities)
            plan.generator = "rules-fallback"
            plan.summary = (plan.summary or "") + " (rules fallback — Claude unavailable)"
            return plan
    plan = generate_plan(goals, ftp_w=ftp_w, activities=activities)
    plan.generator = "rules"
    return plan


def goals_for_post_ride_refresh(existing: TrainingPlan | None) -> PlanGoals:
    """One week ahead, starting tomorrow; reuse prior day/hour preferences."""
    start = (date.today() + timedelta(days=1)).isoformat()
    if existing is not None:
        g = existing.goals.clamp()
        return PlanGoals(
            weeks=AUTO_PLAN_WEEKS,
            hours_per_week=g.hours_per_week,
            bike_days_per_week=g.bike_days_per_week,
            run_days_per_week=g.run_days_per_week,
            goal=g.goal,
            notes=(g.notes or "")[:400],
            start_date=start,
        )
    return PlanGoals(
        weeks=AUTO_PLAN_WEEKS,
        hours_per_week=6.0,
        bike_days_per_week=3,
        run_days_per_week=2,
        goal="general",
        notes="Auto-refreshed after a long ride (≥30 min).",
        start_date=start,
    )


async def maybe_refresh_plan_after_ride(app: Any, *, duration_s: float) -> TrainingPlan | None:
    """
    After a ride of at least 30 minutes, regenerate the next week of training.

    Uses Claude when an API key is configured; falls back to rules. Never raises.
    """
    if duration_s < LONG_RIDE_MIN_S:
        return None
    try:
        settings = app.settings
        src = app.workout_source
        garmin_raw: list[dict] = []
        if getattr(src, "authenticated", False) and hasattr(src, "recent_activities"):
            try:
                garmin_raw = await src.recent_activities(lookback_days=28)
            except Exception as exc:  # noqa: BLE001
                logger.warning("post-ride Garmin history failed: %s", exc)
        activities = merge_history(garmin_raw, app.repo.list_rides())
        existing = load_plan(app.repo)
        goals = goals_for_post_ride_refresh(existing)
        plan = await build_plan(
            goals=goals,
            ftp_w=settings.ftp_w,
            activities=activities,
            anthropic_api_key=str(getattr(settings, "anthropic_api_key", "") or ""),
            anthropic_model=str(
                getattr(settings, "anthropic_model", "claude-sonnet-4-5")
                or "claude-sonnet-4-5"
            ),
        )
        plan.summary = (
            f"Auto week-ahead plan after {int(duration_s // 60)} min ride. "
            + (plan.summary or "")
        )
        save_plan(app.repo, plan)
        logger.info(
            "post-ride plan refresh ok generator=%s days=%s",
            plan.generator,
            len(plan.days),
        )
        return plan
    except Exception as exc:  # noqa: BLE001
        logger.warning("post-ride plan refresh failed: %s", exc)
        return None
