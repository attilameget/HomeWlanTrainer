"""Training plan domain models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Sport = Literal["cycling", "running", "rest"]
SessionKind = Literal[
    "endurance",
    "tempo",
    "intervals",
    "long",
    "recovery",
    "easy",
    "rest",
]


@dataclass
class PlanGoals:
    """Rider goals for plan generation."""

    weeks: int = 4
    hours_per_week: float = 6.0
    bike_days_per_week: int = 3
    run_days_per_week: int = 2
    goal: str = "general"  # general | event | fitness
    notes: str = ""
    start_date: str | None = None  # YYYY-MM-DD; default today

    def clamp(self) -> PlanGoals:
        weeks = max(1, min(16, int(self.weeks)))
        hours = max(2.0, min(20.0, float(self.hours_per_week)))
        bike = max(1, min(6, int(self.bike_days_per_week)))
        run = max(0, min(5, int(self.run_days_per_week)))
        # bike + run may exceed 7 days: same-day doubles (e.g. easy run AM + bike PM)
        # are allowed. Do not silently cut run_days to fit one-session-per-day.
        goal = self.goal if self.goal in ("general", "event", "fitness") else "general"
        return PlanGoals(
            weeks=weeks,
            hours_per_week=hours,
            bike_days_per_week=bike,
            run_days_per_week=run,
            goal=goal,
            notes=(self.notes or "")[:400],
            start_date=self.start_date,
        )


@dataclass
class ActivitySummary:
    """Normalized recent activity used for load-aware planning."""

    id: str
    sport: Sport
    started_at: str
    duration_s: float
    avg_power_w: int | None = None
    distance_m: float | None = None
    name: str | None = None
    source: str = "garmin"  # garmin | local


@dataclass
class PlanDay:
    """One calendar day in a generated plan."""

    id: str
    date: str  # YYYY-MM-DD
    sport: Sport
    kind: SessionKind
    title: str
    duration_s: int
    rationale: str
    playable: bool = False
    stages: list[dict[str, Any]] = field(default_factory=list)
    distance_m: int | None = None
    intensity_note: str | None = None
    garmin_workout_id: str | None = None
    scheduled: bool = False

    def to_workout_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.title,
            "sport": self.sport,
            "source": "plan",
            "source_id": self.id,
            "scheduled_date": self.date,
            "total_s": self.duration_s,
            "stages": self.stages,
            "playable": self.playable,
            "kind": self.kind,
            "rationale": self.rationale,
            "distance_m": self.distance_m,
            "intensity_note": self.intensity_note,
        }


@dataclass
class TrainingPlan:
    """A multi-week multi-sport plan stored locally."""

    id: str
    created_at: str
    ftp_w: int
    goals: PlanGoals
    summary: str
    history_note: str
    days: list[PlanDay] = field(default_factory=list)
    synced_to_garmin: bool = False
    generator: str = "rules"  # rules | claude | rules-fallback
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "ftp_w": self.ftp_w,
            "goals": asdict(self.goals),
            "summary": self.summary,
            "history_note": self.history_note,
            "days": [asdict(d) for d in self.days],
            "synced_to_garmin": self.synced_to_garmin,
            "generator": self.generator,
            "model": self.model,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrainingPlan:
        goals_raw = data.get("goals") or {}
        goals = PlanGoals(
            weeks=int(goals_raw.get("weeks") or 4),
            hours_per_week=float(goals_raw.get("hours_per_week") or 6),
            bike_days_per_week=int(goals_raw.get("bike_days_per_week") or 3),
            run_days_per_week=int(goals_raw.get("run_days_per_week") or 2),
            goal=str(goals_raw.get("goal") or "general"),
            notes=str(goals_raw.get("notes") or ""),
            start_date=goals_raw.get("start_date"),
        )
        days = [
            PlanDay(
                id=str(d["id"]),
                date=str(d["date"]),
                sport=d.get("sport") or "rest",  # type: ignore[arg-type]
                kind=d.get("kind") or "rest",  # type: ignore[arg-type]
                title=str(d.get("title") or "Session"),
                duration_s=int(d.get("duration_s") or 0),
                rationale=str(d.get("rationale") or ""),
                playable=bool(d.get("playable")),
                stages=list(d.get("stages") or []),
                distance_m=d.get("distance_m"),
                intensity_note=d.get("intensity_note"),
                garmin_workout_id=(
                    str(d["garmin_workout_id"])
                    if d.get("garmin_workout_id") is not None
                    else None
                ),
                scheduled=bool(d.get("scheduled")),
            )
            for d in data.get("days") or []
        ]
        return cls(
            id=str(data["id"]),
            created_at=str(data.get("created_at") or ""),
            ftp_w=int(data.get("ftp_w") or 200),
            goals=goals,
            summary=str(data.get("summary") or ""),
            history_note=str(data.get("history_note") or ""),
            days=days,
            synced_to_garmin=bool(data.get("synced_to_garmin")),
            generator=str(data.get("generator") or "rules"),
            model=data.get("model"),
        )
