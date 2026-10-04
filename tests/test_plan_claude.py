"""Tests for Claude materialization and post-ride plan refresh helpers."""

from __future__ import annotations

import urllib.error
from datetime import date, timedelta
from io import BytesIO
from unittest.mock import MagicMock

import pytest

from kickr_pi.plan.claude import normalize_model, probe_claude
from kickr_pi.plan.models import PlanGoals, TrainingPlan
from kickr_pi.plan.service import (
    LONG_RIDE_MIN_S,
    goals_for_post_ride_refresh,
    maybe_refresh_plan_after_ride,
)
from kickr_pi.plan.sketch import materialize_days


def test_normalize_model_upgrades_legacy_default() -> None:
    assert normalize_model("") == "claude-sonnet-5-5"
    assert normalize_model("claude-sonnet-4-5") == "claude-sonnet-5-5"
    assert normalize_model("claude-sonnet-5-5") == "claude-sonnet-5-5"
    assert normalize_model("claude-opus-4-7") == "claude-opus-4-7"


def test_probe_claude_missing_key() -> None:
    out = probe_claude("")
    assert out["ok"] is False
    assert out["configured"] is False
    assert "API key" in out["message"]


def test_probe_claude_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise urllib.error.HTTPError(
            "https://api.anthropic.com/v1/messages",
            401,
            "Unauthorized",
            hdrs={},
            fp=BytesIO(b'{"error":{"type":"authentication_error"}}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", boom)
    out = probe_claude("sk-ant-bad", "claude-sonnet-5-5")
    assert out["ok"] is False
    assert out["configured"] is True
    assert "unauthorized" in out["message"].lower()


def test_probe_claude_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resp:
        def read(self) -> bytes:
            return b'{"content":[{"type":"text","text":"OK"}]}'

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: Resp())
    out = probe_claude("sk-ant-good", "claude-sonnet-5-5")
    assert out["ok"] is True
    assert out["configured"] is True
    assert "Claude OK" in out["message"]


def test_messages_omits_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    """Newer Claude models reject temperature; never send it."""
    import json

    captured: dict = {}

    class Resp:
        def read(self) -> bytes:
            return b'{"content":[{"type":"text","text":"OK"}]}'

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def fake_urlopen(req, timeout=0):  # noqa: ARG001
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    out = probe_claude("sk-ant-good", "claude-sonnet-5-5")
    assert out["ok"] is True
    assert "temperature" not in captured["body"]
    assert "top_p" not in captured["body"]
    assert "top_k" not in captured["body"]
    assert captured["body"]["model"] == "claude-sonnet-5-5"
    assert captured["body"].get("thinking") == {"type": "between_tools"}

def test_materialize_fills_missing_days_and_builds_erg() -> None:
    start = date(2026, 10, 6)
    end = start + timedelta(days=6)
    days = materialize_days(
        [
            {
                "date": start.isoformat(),
                "sport": "cycling",
                "kind": "tempo",
                "title": "Tempo",
                "duration_min": 60,
                "rationale": "quality",
            },
            {
                "date": (start + timedelta(days=2)).isoformat(),
                "sport": "running",
                "kind": "easy",
                "title": "Easy",
                "duration_min": 40,
                "rationale": "shakeout",
            },
        ],
        start=start,
        end=end,
        ftp_w=220,
    )
    assert len(days) == 7
    bike = days[0]
    assert bike.sport == "cycling" and bike.playable and bike.stages
    assert any(s.get("target_mode") == "erg" for s in bike.stages)
    # Missing days become rest
    assert days[1].sport == "rest"
    run = days[2]
    assert run.sport == "running" and not run.playable and run.distance_m


def test_goals_for_post_ride_are_one_week_from_tomorrow() -> None:
    existing = TrainingPlan(
        id="x",
        created_at="",
        ftp_w=200,
        goals=PlanGoals(
            weeks=8,
            hours_per_week=7.5,
            bike_days_per_week=4,
            run_days_per_week=1,
            goal="event",
            notes="race",
        ),
        summary="",
        history_note="",
    )
    g = goals_for_post_ride_refresh(existing)
    assert g.weeks == 1
    assert g.hours_per_week == 7.5
    assert g.bike_days_per_week == 4
    assert g.run_days_per_week == 1
    assert g.start_date == (date.today() + timedelta(days=1)).isoformat()


@pytest.mark.asyncio
async def test_maybe_refresh_skips_short_rides() -> None:
    app = MagicMock()
    out = await maybe_refresh_plan_after_ride(app, duration_s=LONG_RIDE_MIN_S - 1)
    assert out is None
    app.repo.list_rides.assert_not_called()
