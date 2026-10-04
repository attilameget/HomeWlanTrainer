"""Anthropic Claude-backed plan sketch → TrainingPlan (ERG stages from templates)."""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from kickr_pi.plan.history import describe_history, weekly_hours
from kickr_pi.plan.models import ActivitySummary, PlanGoals, TrainingPlan
from kickr_pi.plan.sketch import materialize_days, parse_start

logger = logging.getLogger(__name__)

ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5-5"
# Previous Plan-page default — upgrade silently so Test/Generate use Sonnet 5.5.
_LEGACY_DEFAULT_MODELS = frozenset(
    {
        "claude-sonnet-4-5",
        "claude-sonnet-4-5-20250929",
    }
)


class ClaudeError(Exception):
    """Anthropic request or parse failure."""


def api_key_configured(api_key: str | None) -> bool:
    return bool((api_key or "").strip())


def normalize_model(model: str | None) -> str:
    """Resolve empty / prior app defaults to the current DEFAULT_MODEL."""
    m = (model or "").strip()
    if not m or m in _LEGACY_DEFAULT_MODELS:
        return DEFAULT_MODEL
    return m


def probe_claude(
    api_key: str,
    model: str = DEFAULT_MODEL,
    *,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """Lightweight Messages call to verify the API key and model."""
    key = (api_key or "").strip()
    model = normalize_model(model)
    if not key:
        return {
            "ok": False,
            "configured": False,
            "message": "Paste your Anthropic API key first (console.anthropic.com).",
        }
    try:
        _messages(
            api_key=key,
            model=model,
            system="Reply with the single word OK.",
            user="OK?",
            max_tokens=64,
            timeout_s=timeout_s,
        )
    except ClaudeError as exc:
        return {
            "ok": False,
            "configured": True,
            "message": str(exc),
        }
    return {
        "ok": True,
        "configured": True,
        "message": f"Claude OK — API key works with model “{model}”.",
    }


async def generate_plan_via_claude(
    goals: PlanGoals,
    *,
    ftp_w: int,
    activities: list[ActivitySummary],
    api_key: str,
    model: str = DEFAULT_MODEL,
    timeout_s: float = 180.0,
) -> TrainingPlan:
    """Call Claude for a week-level sketch; materialize ERG stages locally."""
    import asyncio

    return await asyncio.to_thread(
        _generate_sync,
        goals,
        ftp_w,
        activities,
        api_key,
        model,
        timeout_s,
    )


def _generate_sync(
    goals: PlanGoals,
    ftp_w: int,
    activities: list[ActivitySummary],
    api_key: str,
    model: str,
    timeout_s: float,
) -> TrainingPlan:
    g = goals.clamp()
    ftp = max(80, int(ftp_w))
    start = parse_start(g.start_date)
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
        "Return ONLY valid JSON matching the schema (no markdown fences). "
        "Bike sessions use indoor ERG later; run sessions are outdoors/treadmill guidance. "
        "HARD REQUIREMENT: every calendar week in the window must include exactly "
        "goals.bike_days_per_week cycling sessions AND exactly goals.run_days_per_week "
        "running sessions — never reduce run days to make room for bike days. "
        "When bike_days + run_days > 7, schedule same-day doubles: two day entries that "
        "share a date (sport=running AND sport=cycling). Prefer easy/recovery run with "
        "an endurance bike that day; do not stack hard bike (intervals/tempo) with a hard "
        "run the same day. Honor rider notes (e.g. morning run / afternoon bike). "
        "Cap weekly hours near the rider target. "
        "Include every calendar day from start through end; dates with no session are rest "
        "(sport=rest). Doubles mean two entries for that date, not a rest row."
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
        "required_sessions_per_week": {
            "cycling": g.bike_days_per_week,
            "running": g.run_days_per_week,
            "same_day_doubles_required": g.bike_days_per_week + g.run_days_per_week > 7,
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
            "Run kinds: easy/tempo/long only; rest days sport=rest kind=rest duration_min=0.",
            "Summary must state the requested bike and run day counts accurately.",
        ],
    }
    content = _messages(
        api_key=api_key.strip(),
        model=normalize_model(model),
        system=system,
        user=json.dumps(user),
        max_tokens=8192,
        timeout_s=timeout_s,
    )
    sketch = _parse_json_object(content)
    days = materialize_days(
        sketch.get("days") or [],
        start=start,
        end=end,
        ftp_w=ftp,
        sketch_source="Claude",
    )
    if not days:
        raise ClaudeError("model returned no usable days")

    summary = str(sketch.get("summary") or "").strip()
    if not summary:
        summary = (
            f"{g.weeks}-week Claude plan · ~{g.hours_per_week:.1f} h/week · FTP {ftp} W"
        )
    return TrainingPlan(
        id=str(__import__("uuid").uuid4()),
        created_at=datetime.now(timezone.utc).isoformat(),
        ftp_w=ftp,
        goals=g,
        summary=summary,
        history_note=history_note,
        days=days,
        generator="claude",
        model=normalize_model(model),
    )


def _messages(
    *,
    api_key: str,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    timeout_s: float,
) -> str:
    # Sonnet 5 / 5.5 reject non-default temperature, top_p, and top_k — omit them.
    # Use between_tools on Sonnet 5.x so adaptive thinking does not consume the
    # tiny probe budget (and keeps plan sketches as plain text).
    model = normalize_model(model)
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    lower = model.lower()
    if "sonnet-5" in lower:
        body["thinking"] = {"type": "between_tools"}
    for banned in ("temperature", "top_p", "top_k"):
        body.pop(banned, None)
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        ANTHROPIC_API,
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        if exc.code in (401, 403):
            raise ClaudeError(
                "Anthropic rejected the API key (unauthorized). "
                "Check the key at console.anthropic.com."
            ) from exc
        if exc.code == 404:
            raise ClaudeError(
                f"Anthropic model “{model}” was not found. "
                f"Try {DEFAULT_MODEL} or another current model id."
            ) from exc
        if exc.code == 400 and "temperature" in detail.lower():
            raise ClaudeError(
                "Anthropic rejected temperature for this model. "
                "Restart steadyGrind / kickr-pi so the build that omits "
                "temperature is loaded, then Test again."
            ) from exc
        raise ClaudeError(f"Anthropic HTTP {exc.code}: {detail}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ClaudeError(f"Anthropic request failed: {exc}") from exc

    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ClaudeError(f"invalid Anthropic envelope: {exc}") from exc

    parts: list[str] = []
    for block in envelope.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    text = "".join(parts).strip()
    if not text:
        raise ClaudeError("Anthropic returned empty content")
    return text


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ClaudeError("model did not return JSON") from None
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ClaudeError(f"model did not return JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ClaudeError("model JSON root must be an object")
    return data
