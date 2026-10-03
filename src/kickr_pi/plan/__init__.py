"""On-host adaptive multi-sport training plans."""

from kickr_pi.plan.generator import generate_plan
from kickr_pi.plan.models import PlanGoals, TrainingPlan

__all__ = ["PlanGoals", "TrainingPlan", "generate_plan"]
