"""Tests for Claude materialization and plan helpers."""

from __future__ import annotations

import urllib.error
from datetime import date, timedelta
from io import BytesIO

import pytest

from kickr_pi.plan.claude import normalize_model, probe_claude
from kickr_pi.plan.models import PlanGoals
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


def test_materialize_allows_same_day_bike_and_run() -> None:
    start = date(2026, 10, 6)
    end = start
    days = materialize_days(
        [
            {
                "date": start.isoformat(),
                "sport": "running",
                "kind": "easy",
                "title": "AM easy",
                "duration_min": 35,
                "rationale": "morning",
            },
            {
                "date": start.isoformat(),
                "sport": "cycling",
                "kind": "endurance",
                "title": "PM bike",
                "duration_min": 60,
                "rationale": "afternoon",
            },
        ],
        start=start,
        end=end,
        ftp_w=200,
    )
    assert len(days) == 2
    assert days[0].sport == "running" and days[0].date == start.isoformat()
    assert days[1].sport == "cycling" and days[1].playable


def test_clamp_preserves_high_run_days_with_many_bike_days() -> None:
    g = PlanGoals(bike_days_per_week=5, run_days_per_week=4).clamp()
    assert g.bike_days_per_week == 5
    assert g.run_days_per_week == 4


def test_weeks_meet_session_goals_detects_undercount() -> None:
    from kickr_pi.plan.claude import weeks_meet_session_goals
    from kickr_pi.plan.models import PlanDay

    start = date(2026, 10, 6)
    goals = PlanGoals(weeks=1, bike_days_per_week=5, run_days_per_week=4)
    # Only one run — should fail
    days = [
        PlanDay(
            id="b",
            date=(start + timedelta(days=i)).isoformat(),
            sport="cycling",
            kind="endurance",
            title="Bike",
            duration_s=3600,
            rationale="",
            playable=True,
        )
        for i in range(5)
    ] + [
        PlanDay(
            id="r",
            date=(start + timedelta(days=6)).isoformat(),
            sport="running",
            kind="easy",
            title="Run",
            duration_s=2400,
            rationale="",
            playable=False,
        )
    ]
    assert weeks_meet_session_goals(days, goals, start) is False


@pytest.mark.asyncio
async def test_claude_falls_back_when_sketch_undercounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If Claude returns too few runs, on-host rules calendar must win."""
    import json

    from kickr_pi.plan.claude import generate_plan_via_claude

    start = date.today()
    # 5 bikes + 1 run for one week — under-count vs goals 5/4
    thin_days = []
    for i in range(5):
        thin_days.append(
            {
                "date": (start + timedelta(days=i)).isoformat(),
                "sport": "cycling",
                "kind": "endurance",
                "title": "Bike",
                "duration_min": 50,
                "rationale": "x",
            }
        )
    thin_days.append(
        {
            "date": (start + timedelta(days=6)).isoformat(),
            "sport": "running",
            "kind": "easy",
            "title": "Run",
            "duration_min": 40,
            "rationale": "x",
        }
    )
    payload = {"summary": "5 bike + 1 run weekly", "days": thin_days}

    class Resp:
        def read(self) -> bytes:
            return json.dumps(
                {"content": [{"type": "text", "text": json.dumps(payload)}]}
            ).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: Resp())

    plan = await generate_plan_via_claude(
        PlanGoals(
            weeks=1,
            hours_per_week=10,
            bike_days_per_week=5,
            run_days_per_week=4,
            start_date=start.isoformat(),
        ),
        ftp_w=200,
        activities=[],
        api_key="sk-test",
        model="claude-sonnet-5-5",
    )
    assert plan.generator == "rules-fallback"
    assert sum(1 for d in plan.days if d.sport == "cycling") == 5
    assert sum(1 for d in plan.days if d.sport == "running") == 4
    assert "4 run" in plan.summary
