"""On-host adaptive multi-sport training plans."""

from steadygrind.plan.generator import generate_plan
from steadygrind.plan.models import PlanGoals, TrainingPlan

__all__ = ["PlanGoals", "TrainingPlan", "generate_plan"]
