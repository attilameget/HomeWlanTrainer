"""Plan generation orchestration: Claude with rules fallback (user-triggered only)."""

from __future__ import annotations

import logging
from typing import Any

from steadygrind.plan.claude import (
    ClaudeError,
    api_key_configured,
    generate_plan_via_claude,
)
from steadygrind.plan.generator import generate_plan
from steadygrind.plan.models import PlanGoals, TrainingPlan

logger = logging.getLogger(__name__)


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
