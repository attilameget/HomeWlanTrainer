"""Tests for Ollama materialization and post-ride plan refresh helpers."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from kickr_pi.plan.models import PlanGoals, TrainingPlan
from kickr_pi.plan.ollama import _materialize_days, probe_ollama
from kickr_pi.plan.service import (
    LONG_RIDE_MIN_S,
    goals_for_post_ride_refresh,
    maybe_refresh_plan_after_ride,
)


def test_probe_ollama_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise OSError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    out = probe_ollama("http://127.0.0.1:9", "llama3.1:8b")
    assert out["ok"] is False
    assert out["reachable"] is False
    assert "Cannot reach Ollama" in out["message"]


def test_probe_ollama_missing_model(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resp:
        def read(self) -> bytes:
            return b'{"models":[{"name":"llama3.2:3b"}]}'

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: Resp())
    out = probe_ollama("http://127.0.0.1:11434", "llama3.1:8b")
    assert out["reachable"] is True
    assert out["model_present"] is False
    assert out["ok"] is False
    assert "ollama pull llama3.1:8b" in out["message"]


def test_probe_ollama_model_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resp:
        def read(self) -> bytes:
            return b'{"models":[{"name":"llama3.1:8b"}]}'

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: Resp())
    out = probe_ollama("http://127.0.0.1:11434", "llama3.1:8b")
    assert out["ok"] is True
    assert out["model_present"] is True


def test_materialize_fills_missing_days_and_builds_erg() -> None:
    start = date(2026, 10, 6)
    end = start + timedelta(days=6)
    days = _materialize_days(
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
