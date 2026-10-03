"""Upload plan sessions to Garmin Connect and schedule them on the calendar."""

from __future__ import annotations

import logging
from typing import Any

from kickr_pi.plan.models import PlanDay, TrainingPlan

logger = logging.getLogger(__name__)


async def sync_plan_to_garmin(client: Any, plan: TrainingPlan) -> TrainingPlan:
    """
    Create Garmin workouts for plan days and schedule them.

    Bike days use power targets; run days use time (and estimated distance in the name).
    Updates plan day garmin_workout_id / scheduled flags in place.
    """
    import asyncio

    for day in plan.days:
        if day.sport == "rest":
            continue
        if day.garmin_workout_id and day.scheduled:
            continue
        try:
            workout_payload = _to_garmin_workout(day)
            result = await asyncio.to_thread(client.upload_workout, workout_payload)
            wid = str(
                result.get("workoutId")
                or result.get("workout_id")
                or (result.get("workout") or {}).get("workoutId")
                or ""
            )
            if not wid:
                logger.warning("Garmin upload returned no workoutId for %s", day.id)
                continue
            day.garmin_workout_id = wid
            await asyncio.to_thread(client.schedule_workout, wid, day.date)
            day.scheduled = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to sync plan day %s: %s", day.id, exc)
    plan.synced_to_garmin = any(d.scheduled for d in plan.days)
    return plan


def _to_garmin_workout(day: PlanDay) -> dict[str, Any]:
    if day.sport == "running":
        return _run_workout_dict(day)
    return _bike_workout_dict(day)


def _bike_workout_dict(day: PlanDay) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    order = 1
    for stage in day.stages:
        duration = float(stage.get("duration_s") or 0)
        if duration <= 0:
            continue
        kind = str(stage.get("kind") or "interval")
        step_type = _step_type(kind)
        target_w = stage.get("target_w")
        start_w = stage.get("start_w")
        end_w = stage.get("end_w")
        if target_w is not None:
            lo = max(0, int(target_w) - 5)
            hi = int(target_w) + 5
            target = {
                "workoutTargetTypeId": 2,
                "workoutTargetTypeKey": "power.custom",
                "displayOrder": 1,
            }
            # Garmin accepts custom power via value one/two on many clients
            step = {
                "type": "ExecutableStepDTO",
                "stepOrder": order,
                "stepType": step_type,
                "endCondition": _time_condition(),
                "endConditionValue": duration,
                "targetType": target,
                "targetValueOne": float(lo),
                "targetValueTwo": float(hi),
                "description": stage.get("name") or day.title,
            }
        elif start_w is not None and end_w is not None:
            mid = (int(start_w) + int(end_w)) // 2
            step = {
                "type": "ExecutableStepDTO",
                "stepOrder": order,
                "stepType": step_type,
                "endCondition": _time_condition(),
                "endConditionValue": duration,
                "targetType": {
                    "workoutTargetTypeId": 2,
                    "workoutTargetTypeKey": "power.custom",
                    "displayOrder": 1,
                },
                "targetValueOne": float(max(0, mid - 10)),
                "targetValueTwo": float(mid + 10),
                "description": stage.get("name") or day.title,
            }
        else:
            step = {
                "type": "ExecutableStepDTO",
                "stepOrder": order,
                "stepType": step_type,
                "endCondition": _time_condition(),
                "endConditionValue": duration,
                "targetType": {
                    "workoutTargetTypeId": 1,
                    "workoutTargetTypeKey": "no.target",
                    "displayOrder": 1,
                },
                "description": stage.get("name") or day.title,
            }
        steps.append(step)
        order += 1

    return {
        "workoutName": f"sg · {day.title}",
        "description": day.rationale,
        "sportType": {
            "sportTypeId": 2,
            "sportTypeKey": "cycling",
            "displayOrder": 2,
        },
        "estimatedDurationInSecs": day.duration_s,
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": {"sportTypeId": 2, "sportTypeKey": "cycling"},
                "workoutSteps": steps,
            }
        ],
    }


def _run_workout_dict(day: PlanDay) -> dict[str, Any]:
    duration = float(max(60, day.duration_s))
    km = (day.distance_m or 0) / 1000.0
    name = f"sg · {day.title}"
    if km > 0:
        name = f"{name} (~{km:.1f} km)"
    step = {
        "type": "ExecutableStepDTO",
        "stepOrder": 1,
        "stepType": {
            "stepTypeId": 3,
            "stepTypeKey": "interval",
            "displayOrder": 3,
        },
        "endCondition": _time_condition(),
        "endConditionValue": duration,
        "targetType": {
            "workoutTargetTypeId": 1,
            "workoutTargetTypeKey": "no.target",
            "displayOrder": 1,
        },
        "description": day.rationale or day.title,
    }
    return {
        "workoutName": name,
        "description": day.rationale,
        "sportType": {
            "sportTypeId": 1,
            "sportTypeKey": "running",
            "displayOrder": 1,
        },
        "estimatedDurationInSecs": day.duration_s,
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
                "workoutSteps": [step],
            }
        ],
    }


def _time_condition() -> dict[str, Any]:
    return {
        "conditionTypeId": 2,
        "conditionTypeKey": "time",
        "displayOrder": 2,
        "displayable": True,
    }


def _step_type(kind: str) -> dict[str, Any]:
    mapping = {
        "warmup": (1, "warmup", 1),
        "cooldown": (2, "cooldown", 2),
        "interval": (3, "interval", 3),
        "recovery": (4, "recovery", 4),
        "rest": (5, "rest", 5),
        "free": (3, "interval", 3),
    }
    sid, key, order = mapping.get(kind, (3, "interval", 3))
    return {"stepTypeId": sid, "stepTypeKey": key, "displayOrder": order}
