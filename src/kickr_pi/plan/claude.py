"""Anthropic Claude-backed plan sketch → TrainingPlan (ERG stages from templates)."""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any

from kickr_pi.plan.history import build_load_profile, describe_history
from kickr_pi.plan.models import (
    ActivitySummary,
    PlanCoaching,
    PlanDay,
    PlanGoals,
    TrainingPlan,
)
from kickr_pi.plan.sketch import clamp_run_volumes, materialize_days, parse_start

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
    from kickr_pi.plan.generator import generate_plan

    g = goals.clamp()
    ftp = max(80, int(ftp_w))
    start = parse_start(g.start_date)
    end = start + timedelta(days=7 * g.weeks - 1)
    load = build_load_profile(activities, ftp_w=ftp)
    history_note = describe_history(activities, ftp_w=ftp)
    caps = load["volume_caps"]
    rest_set = set(g.rest_weekdays)
    available = max(1, 7 - len(rest_set))
    sessions_per_week = (
        g.bike_days_per_week + g.run_days_per_week + g.strength_days_per_week
    )
    need_doubles = sessions_per_week > available
    rest_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    rest_names = ", ".join(rest_labels[d] for d in g.rest_weekdays)

    payload_schema = {
        "summary": "one-line plan headline with exact day counts",
        "coaching": {
            "goal": "primary training goal for this block (2–4 sentences)",
            "why": (
                "strong reasoning: how FTP, recent bike hours/km, run km and "
                "typical session sizes shaped week structure, intensities, and volumes"
            ),
            "expect": (
                "what the athlete should expect after these weeks "
                "(fitness, durability, risks to avoid) — concrete outcomes"
            ),
        },
        "days": [
            {
                "date": "YYYY-MM-DD",
                "sport": "cycling|running|strength|rest",
                "kind": (
                    "endurance|tempo|intervals|long|recovery|easy|rest|"
                    "full_body|upper|lower|core|mobility"
                ),
                "title": "session title",
                "duration_min": 45,
                "distance_km": 6.5,
                "rationale": "one sentence why this session sits on this day",
            }
        ],
    }
    system = (
        "You are an endurance coach for bike+run+strength athletes. "
        "Return ONLY valid JSON matching the schema (no markdown fences). "
        "Bike = indoor ERG later; run = outdoors/treadmill guidance; "
        "strength = gym / weights guidance (not on the trainer). "
        "GROUND TRUTH: size EVERY session from rider_load (FTP + recent Garmin "
        "bike/run hours and km). If the rider typically runs ~6–7 km, easy runs "
        "must stay near that — never invent 9–14 km weeks from nowhere. "
        f"HARD VOLUME CAPS (week 1): total run km ≤ {caps['week1_run_km_max']}; "
        f"easy ≤ {caps['easy_run_km_max']} km; tempo ≤ {caps['tempo_run_km_max']} km; "
        f"long ≤ {caps['long_run_km_max']} km. "
        "Every running day MUST include distance_km within those caps. "
        "Bike duration_min must respect recent bike hours "
        f"(week1 bike hours ≤ {caps.get('week1_bike_h_max') or 'rider target'}). "
        f"NON-NEGOTIABLE SESSION COUNTS: every Mon–Sun week must contain "
        f"EXACTLY {g.bike_days_per_week} cycling, "
        f"EXACTLY {g.run_days_per_week} running, and "
        f"EXACTLY {g.strength_days_per_week} strength. "
        "Never drop sessions to protect recovery — shorten distance/duration instead. "
        f"HARD REST WEEKDAYS (0=Mon … 6=Sun): {g.rest_weekdays} ({rest_names}). "
        "Those weekdays MUST be sport=rest only. "
        + (
            f"Sessions ({sessions_per_week}) exceed available days ({available}): "
            "emit same-day doubles on non-rest days. "
            if need_doubles
            else "Fill non-rest days with sessions; rest only on selected weekdays. "
        )
        + "Do not stack hard bike (intervals/tempo) with tempo/long run same day. "
        "Honor rider notes. Rest: sport=rest kind=rest duration_min=0 distance_km=0. "
        "Strength kinds: full_body|upper|lower|core|mobility (~40–50 min). "
        "coaching.goal / coaching.why / coaching.expect are REQUIRED and must be "
        "specific to THIS rider's FTP and recent mileage — not generic filler. "
        "summary must include the exact bike/run/strength day counts."
    )
    user = {
        "ftp_w": ftp,
        "rider_load": load,
        "must_schedule_every_week": {
            "cycling_sessions": g.bike_days_per_week,
            "running_sessions": g.run_days_per_week,
            "strength_sessions": g.strength_days_per_week,
            "rest_weekdays": g.rest_weekdays,
            "same_day_doubles_required": need_doubles,
        },
        "goals": {
            "weeks": g.weeks,
            "hours_per_week": g.hours_per_week,
            "bike_days_per_week": g.bike_days_per_week,
            "run_days_per_week": g.run_days_per_week,
            "strength_days_per_week": g.strength_days_per_week,
            "rest_weekdays": g.rest_weekdays,
            "goal": g.goal,
            "notes": g.notes,
        },
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "history_note": history_note,
        "schema": payload_schema,
        "constraints": [
            "Base volumes on rider_load.recent_sessions and volume_caps — not on wishful race paces.",
            "If recent runs are 6–7 km, week-1 runs should be ~6–7.5 km easy / slightly longer long run only within long_run_km_max.",
            "Bike kinds map to ERG templates; keep durations realistic vs recent bike_h.",
            "Run kinds: easy/tempo/long only; always set distance_km.",
            "Strength kinds: full_body/upper/lower/core/mobility only.",
            f"Forbidden: rest-weekday training ({g.rest_weekdays}).",
            "Forbidden: jumping weekly run km more than ~10% above recent baseline in week 1.",
            "coaching.why must cite FTP and recent bike/run km or hours explicitly.",
        ],
    }
    content = _messages(
        api_key=api_key.strip(),
        model=normalize_model(model),
        system=system,
        user=json.dumps(user),
        max_tokens=12288,
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
    days = clamp_run_volumes(
        days,
        start=start,
        weeks=g.weeks,
        volume_caps=caps,
    )

    coaching = PlanCoaching.from_dict(sketch.get("coaching"))
    counts_ok = weeks_meet_session_goals(days, g, start)
    generator = "claude"
    strength_bit = (
        f" / {g.strength_days_per_week} strength" if g.strength_days_per_week else ""
    )
    count_phrase = (
        f"{g.bike_days_per_week} bike / {g.run_days_per_week} run"
        f"{strength_bit} days per week"
    )
    if not counts_ok:
        logger.warning(
            "Claude sketch missed session counts or rest weekdays "
            "(need %s bike / %s run / %s strength; rest %s); "
            "enforcing with rules calendar",
            g.bike_days_per_week,
            g.run_days_per_week,
            g.strength_days_per_week,
            g.rest_weekdays,
        )
        rules = generate_plan(g, ftp_w=ftp, activities=activities)
        days = rules.days
        generator = "rules-fallback"
        summary = (
            f"{g.weeks}-week plan · {count_phrase} · ~{g.hours_per_week:.1f} h/week · "
            f"FTP {ftp} W. Calendar enforced on-host because Claude under-counted "
            "sessions or violated rest days."
        )
        if coaching is None:
            coaching = PlanCoaching(
                goal=f"Build toward your “{g.goal}” target over {g.weeks} weeks "
                f"at about {g.hours_per_week:.1f} h/week (FTP {ftp} W).",
                why=(
                    f"Claude’s sketch missed required session counts or rest days, "
                    f"so the on-host rules calendar was applied. Recent load: {history_note} "
                    f"Week-1 run volume is capped at ~{caps['week1_run_km_max']} km "
                    f"(easy ≤ {caps['easy_run_km_max']} km) based on your Garmin history."
                ),
                expect=(
                    f"After {g.weeks} weeks you should hold steadier aerobic bike power "
                    f"near your FTP zones and clearer run durability near your recent "
                    f"weekly mileage — without a sudden jump in run kilometres."
                ),
            )
    else:
        summary = str(sketch.get("summary") or "").strip()
        if not summary:
            summary = (
                f"{g.weeks}-week Claude plan · {count_phrase} · "
                f"~{g.hours_per_week:.1f} h/week · FTP {ftp} W"
            )
        elif count_phrase not in summary and f"{g.run_days_per_week} run" not in summary:
            summary = f"{count_phrase}. {summary}"
        if coaching is None:
            coaching = PlanCoaching(
                goal=f"{g.weeks}-week block aimed at “{g.goal}” (FTP {ftp} W).",
                why=f"Sized from recent history: {history_note}",
                expect=(
                    f"Expect gradual fitness over {g.weeks} weeks while keeping run "
                    f"volume near your recent baseline (week-1 ≤ ~{caps['week1_run_km_max']} km)."
                ),
            )

    return TrainingPlan(
        id=str(__import__("uuid").uuid4()),
        created_at=datetime.now(timezone.utc).isoformat(),
        ftp_w=ftp,
        goals=g,
        summary=summary,
        history_note=history_note,
        days=days,
        generator=generator,
        model=normalize_model(model),
        coaching=coaching,
    )


def weeks_meet_session_goals(
    days: list[PlanDay],
    goals: PlanGoals,
    start: date,
) -> bool:
    """True when every plan week has requested counts and rest weekdays are rest-only."""
    g = goals.clamp()
    rest_set = set(g.rest_weekdays)
    for week in range(g.weeks):
        week_start = start + timedelta(days=7 * week)
        week_end = week_start + timedelta(days=6)
        bike = run = strength = 0
        for day in days:
            try:
                d = date.fromisoformat(str(getattr(day, "date", ""))[:10])
            except ValueError:
                continue
            if d < week_start or d > week_end:
                continue
            sport = getattr(day, "sport", "")
            dow = d.weekday()  # Mon=0
            if dow in rest_set and sport != "rest":
                return False
            if sport == "cycling":
                bike += 1
            elif sport == "running":
                run += 1
            elif sport == "strength":
                strength += 1
        if (
            bike != g.bike_days_per_week
            or run != g.run_days_per_week
            or strength != g.strength_days_per_week
        ):
            return False
    return True


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
