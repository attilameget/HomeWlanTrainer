"""Startup settings merge: SQLite + KICKR_* env overrides."""

from __future__ import annotations

import os

import pytest

from steadygrind.config import (
    Settings,
    apply_persisted_settings,
    clamp_incline_pct,
    persisted_settings,
)


@pytest.fixture(autouse=True)
def _clear_trainer_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KICKR_TRAINER_MODE", raising=False)
    monkeypatch.delenv("KICKR_ALLOW_SIMULATED", raising=False)


def test_db_dircon_unchanged_without_env() -> None:
    s = Settings(trainer_mode="dircon", allow_simulated=False)
    apply_persisted_settings(
        s, {"trainer_mode": "dircon", "allow_simulated": False, "ftp_w": 210}
    )
    assert s.trainer_mode == "dircon"
    assert s.allow_simulated is False
    assert s.ftp_w == 210


def test_env_simulated_overrides_db_dircon(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: desk launch with KICKR_TRAINER_MODE=simulated must not hunt KICKR."""
    monkeypatch.setenv("KICKR_TRAINER_MODE", "simulated")
    s = Settings()
    # pydantic already saw the env; re-seed as if DB overwrote first
    s.trainer_mode = "dircon"
    s.allow_simulated = False
    apply_persisted_settings(
        s, {"trainer_mode": "dircon", "allow_simulated": False}
    )
    assert s.trainer_mode == "simulated"
    assert s.allow_simulated is True


def test_env_simulated_implies_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KICKR_TRAINER_MODE", "simulated")
    s = Settings(trainer_mode="simulated", allow_simulated=False)
    apply_persisted_settings(s, {})
    assert s.trainer_mode == "simulated"
    assert s.allow_simulated is True


def test_env_allow_false_blocks_simulated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KICKR_TRAINER_MODE", "simulated")
    monkeypatch.setenv("KICKR_ALLOW_SIMULATED", "false")
    s = Settings(trainer_mode="simulated", allow_simulated=True)
    apply_persisted_settings(s, {"trainer_mode": "simulated", "allow_simulated": True})
    assert s.trainer_mode == "dircon"
    assert s.allow_simulated is False


def test_db_simulated_with_allow_kept() -> None:
    s = Settings(trainer_mode="dircon", allow_simulated=False)
    apply_persisted_settings(
        s, {"trainer_mode": "simulated", "allow_simulated": True}
    )
    assert s.trainer_mode == "simulated"
    assert s.allow_simulated is True


def test_db_simulated_without_allow_downgrades() -> None:
    s = Settings(trainer_mode="simulated", allow_simulated=False)
    apply_persisted_settings(
        s, {"trainer_mode": "simulated", "allow_simulated": False}
    )
    assert s.trainer_mode == "dircon"
    assert s.allow_simulated is False


def test_incline_defaults_to_flat_and_survives_settings_merge() -> None:
    assert clamp_incline_pct(None) == 0.0
    assert clamp_incline_pct(1) == 1.0
    assert clamp_incline_pct(99) == 20.0
    assert clamp_incline_pct(-99) == -10.0
    s = Settings()
    assert s.incline_pct == 0.0
    assert persisted_settings(s)["incline_pct"] == 0.0
    apply_persisted_settings(s, {"ftp_w": 210})
    assert s.incline_pct == 0.0
    apply_persisted_settings(s, {"incline_pct": 1.5})
    assert s.incline_pct == 1.5
    blob = persisted_settings(s)
    assert blob["incline_pct"] == 1.5
    s2 = Settings()
    apply_persisted_settings(s2, blob)
    assert s2.incline_pct == 1.5
