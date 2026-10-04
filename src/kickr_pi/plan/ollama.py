"""Ollama-backed plan sketch → TrainingPlan (ERG stages from templates)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any

from kickr_pi.plan.history import describe_history, weekly_hours
from kickr_pi.plan.models import (
    ActivitySummary,
    PlanDay,
    PlanGoals,
    SessionKind,
    TrainingPlan,
)
from kickr_pi.plan.templates import build_bike_stages, run_distance_m

logger = logging.getLogger(__name__)

VALID_SPORTS = frozenset({"cycling", "running", "rest"})
VALID_KINDS = frozenset(
    {
        "endurance",
        "tempo",
        "intervals",
        "long",
        "recovery",
        "easy",
        "rest",
    }
)


class OllamaError(Exception):
    """Ollama request or parse failure."""


def ollama_available(base_url: str, *, timeout_s: float = 2.0) -> bool:
    return bool(probe_ollama(base_url, model="", timeout_s=timeout_s).get("reachable"))


def probe_ollama(
    base_url: str,
    model: str = "",
    *,
    timeout_s: float = 5.0,
) -> dict[str, Any]:
    """
    Check whether the Ollama HTTP API is up and (optionally) whether ``model``
    is present in ``/api/tags``.
    """
    url = base_url.rstrip("/") + "/api/tags"
    want = (model or "").strip()
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "reachable": False,
            "model_present": False,
            "models": [],
            "message": (
                f"Cannot reach Ollama at {base_url.rstrip('/')}. "
                f"Install/start Ollama, then try again. ({exc})"
            ),
        }
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "reachable": True,
            "model_present": False,
            "models": [],
            "message": "Ollama responded but /api/tags was not valid JSON.",
        }
    names: list[str] = []
    for item in data.get("models") or []:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("model") or "").strip()
            if name:
                names.append(name)
    if not want:
        return {
            "ok": True,
            "reachable": True,
            "model_present": True,
            "models": names,
            "message": (
                f"Ollama is reachable ({len(names)} model(s) listed)."
                if names
                else "Ollama is reachable, but no models are installed yet "
                "(run: ollama pull llama3.1:8b)."
            ),
        }
    # Exact name or same tag with a digest suffix (llama3.1:8b vs llama3.1:8b-q4_…)
    present = want in names or any(
        n == want or n.startswith(f"{want}-") for n in names
    )
    if present:
        return {
            "ok": True,
            "reachable": True,
            "model_present": True,
            "models": names,
            "message": f"Ollama OK — model “{want}” is available.",
        }
    hint = ", ".join(names[:6]) if names else "(none — run ollama pull …)"
    return {
        "ok": False,
        "reachable": True,
        "model_present": False,
        "models": names,
        "message": (
            f"Ollama is reachable, but model “{want}” is not installed. "
            f"Run: ollama pull {want}. Installed: {hint}"
        ),
    }


async def generate_plan_via_ollama(
    goals: PlanGoals,
    *,
    ftp_w: int,
    activities: list[ActivitySummary],
    base_url: str,
    model: str,
    timeout_s: float = 120.0,
) -> TrainingPlan:
    """Call Ollama for a week-level sketch; materialize ERG stages locally."""
    import asyncio

    return await asyncio.to_thread(
        _generate_sync,
        goals,
        ftp_w,
        activities,
        base_url,
        model,
        timeout_s,
    )


def _generate_sync(
    goals: PlanGoals,
    ftp_w: int,
    activities: list[ActivitySummary],
    base_url: str,
    model: str,
    timeout_s: float,
) -> TrainingPlan:
    g = goals.clamp()
    ftp = max(80, int(ftp_w))
    start = _parse_start(g.start_date)
    end = start + timedelta(days=7 * g.weeks - 1)
    history_note = describe_history(activities)
    recent_h = weekly_hours(activities)
    bike_h = weekly_hours(activities, sport="cycling")
    run_h = weekly_hours(activities, sport="running")

    payload_schema = {
        "summary": "short plan summary string",
        "days": [
            {
                "date": "YYYY-MM-DD",
                "sport": "cycling|running|rest",
                "kind": "endurance|tempo|intervals|long|recovery|easy|rest",
                "title": "session title",
                "duration_min": 45,
                "rationale": "one sentence why",
            }
        ],
    }
    system = (
        "You are an endurance coach for bike+run athletes. "
        "Return ONLY valid JSON matching the schema. "
        "Bike sessions use indoor ERG later; run sessions are outdoors/treadmill guidance. "
        "Respect recovery: do not stack hard bike (intervals/tempo) with hard run the same day "
        "or consecutive days. Cap weekly hours near the rider target. "
        "Include exactly one entry per calendar day from start through end inclusive."
    )
    user = {
        "ftp_w": ftp,
        "goals": {
            "weeks": g.weeks,
            "hours_per_week": g.hours_per_week,
            "bike_days_per_week": g.bike_days_per_week,
            "run_days_per_week": g.run_days_per_week,
            "goal": g.goal,
            "notes": g.notes,
        },
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "recent_load_hours_7d": {
            "total": round(recent_h, 2),
            "bike": round(bike_h, 2),
            "run": round(run_h, 2),
        },
        "history_note": history_note,
        "schema": payload_schema,
        "constraints": [
            "Prefer gradual progression; after a long hard ride keep next day easy or rest.",
            "Bike kinds map to ERG templates; keep durations realistic (30–150 min).",
            "Run days: easy/tempo/long only; rest days sport=rest kind=rest duration_min=0.",
        ],
    }
    body = {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user)},
        ],
        "options": {"temperature": 0.3},
    }
    url = base_url.rstrip("/") + "/api/chat"
    raw_text = _post_json(url, body, timeout_s=timeout_s)
    try:
        envelope = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise OllamaError(f"invalid Ollama envelope: {exc}") from exc
    content = (envelope.get("message") or {}).get("content") or ""
    try:
        sketch = json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError as exc:
        raise OllamaError(f"model did not return JSON: {exc}") from exc
    if not isinstance(sketch, dict):
        raise OllamaError("model JSON root must be an object")

    days = _materialize_days(sketch.get("days") or [], start=start, end=end, ftp_w=ftp)
    if not days:
        raise OllamaError("model returned no usable days")

    summary = str(sketch.get("summary") or "").strip()
    if not summary:
        summary = (
            f"{g.weeks}-week Ollama plan · ~{g.hours_per_week:.1f} h/week · FTP {ftp} W"
        )
    return TrainingPlan(
        id=str(__import__("uuid").uuid4()),
        created_at=datetime.now(timezone.utc).isoformat(),
        ftp_w=ftp,
        goals=g,
        summary=summary,
        history_note=history_note,
        days=days,
        generator="ollama",
        model=model,
    )


def _post_json(url: str, body: dict[str, Any], *, timeout_s: float) -> str:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise OllamaError(f"HTTP {exc.code}: {detail}") from exc
    except Exception as exc:  # noqa: BLE001
        raise OllamaError(str(exc)) from exc


def _materialize_days(
    raw_days: list[Any],
    *,
    start: date,
    end: date,
    ftp_w: int,
) -> list[PlanDay]:
    by_date: dict[str, dict[str, Any]] = {}
    for item in raw_days:
        if not isinstance(item, dict):
            continue
        d = str(item.get("date") or "")[:10]
        try:
            day_date = date.fromisoformat(d)
        except ValueError:
            continue
        if day_date < start or day_date > end:
            continue
        sport = str(item.get("sport") or "rest").lower()
        kind = str(item.get("kind") or "rest").lower()
        if sport not in VALID_SPORTS:
            sport = "rest"
        if kind not in VALID_KINDS:
            kind = "rest" if sport == "rest" else "endurance" if sport == "cycling" else "easy"
        if sport == "rest":
            kind = "rest"
        by_date[d] = {
            "sport": sport,
            "kind": kind,
            "title": str(item.get("title") or _default_title(sport, kind)),
            "duration_min": max(0, int(float(item.get("duration_min") or 0))),
            "rationale": str(item.get("rationale") or ""),
        }

    out: list[PlanDay] = []
    cursor = start
    while cursor <= end:
        key = cursor.isoformat()
        item = by_date.get(key) or {
            "sport": "rest",
            "kind": "rest",
            "title": "Rest / mobility",
            "duration_min": 0,
            "rationale": "Recovery day filled in locally.",
        }
        sport = item["sport"]
        kind: SessionKind = item["kind"]  # type: ignore[assignment]
        if sport == "cycling":
            dur_s = max(20 * 60, int(item["duration_min"]) * 60)
            stages = build_bike_stages(kind, ftp_w=ftp_w, duration_s=dur_s)
            total = sum(int(s.get("duration_s") or 0) for s in stages)
            out.append(
                PlanDay(
                    id=f"plan-day-{key}-bike",
                    date=key,
                    sport="cycling",
                    kind=kind,
                    title=item["title"],
                    duration_s=total,
                    rationale=item["rationale"] or "Bike session from Ollama sketch.",
                    playable=True,
                    stages=stages,
                    intensity_note=kind,
                )
            )
        elif sport == "running":
            dur_s = max(20 * 60, int(item["duration_min"]) * 60)
            out.append(
                PlanDay(
                    id=f"plan-day-{key}-run",
                    date=key,
                    sport="running",
                    kind=kind if kind != "rest" else "easy",
                    title=item["title"],
                    duration_s=dur_s,
                    distance_m=run_distance_m(
                        kind if kind != "rest" else "easy", dur_s
                    ),
                    rationale=item["rationale"] or "Run guidance from Ollama sketch.",
                    playable=False,
                    intensity_note=kind,
                )
            )
        else:
            out.append(
                PlanDay(
                    id=f"plan-day-{key}-rest",
                    date=key,
                    sport="rest",
                    kind="rest",
                    title=item["title"],
                    duration_s=0,
                    rationale=item["rationale"] or "Rest day.",
                    playable=False,
                )
            )
        cursor += timedelta(days=1)
    return out


def _default_title(sport: str, kind: str) -> str:
    if sport == "rest":
        return "Rest / mobility"
    if sport == "running":
        return f"{kind.capitalize()} run"
    return f"{kind.capitalize()} ride"


def _parse_start(value: str | None) -> date:
    if value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            pass
    return date.today()
