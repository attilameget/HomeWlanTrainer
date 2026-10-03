"""Saved rides: FIT writer, repository, and Stop finalize."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fit_tool.fit_file import FitFile

from kickr_pi.api import routes as routes_mod
from kickr_pi.engine.engine import WorkoutEngine
from kickr_pi.engine.models import EngineState, LiveState
from kickr_pi.rides.fit import build_activity_fit
from kickr_pi.rides.models import RideRecording, RideSample
from kickr_pi.rides.store import delete_ride_files, download_filename, save_ride
from kickr_pi.storage.repository import Repository
from kickr_pi.trainer.ftms import BikeData
from kickr_pi.trainer.simulated import SimulatedTrainer


def _sample(elapsed: float, power: int = 150) -> RideSample:
    return RideSample(
        elapsed_s=elapsed,
        power_w=power,
        cadence_rpm=90.0,
        speed_kph=28.0,
        heart_rate_bpm=140,
        target_w=150,
    )


def test_build_activity_fit_is_parseable():
    started = datetime(2026, 10, 3, 18, 0, 0, tzinfo=timezone.utc)
    recording = RideRecording(
        started_at=started,
        ended_at=datetime(2026, 10, 3, 18, 0, 5, tzinfo=timezone.utc),
        duration_s=5.0,
        avg_power_w=152,
        workout_name="Manual ERG",
        samples=[_sample(1.0, 150), _sample(2.0, 154)],
    )
    data = build_activity_fit(recording)
    assert len(data) > 50
    assert b".FIT" in data[:16]
    parsed = FitFile.from_bytes(data)
    assert len(list(parsed.records)) >= 5


def test_save_and_delete_ride(tmp_path: Path):
    repo = Repository(tmp_path / "test.db")
    rides_dir = tmp_path / "rides"
    started = datetime(2026, 10, 3, 18, 0, 0, tzinfo=timezone.utc)
    recording = RideRecording(
        started_at=started,
        ended_at=datetime(2026, 10, 3, 18, 10, 0, tzinfo=timezone.utc),
        duration_s=600.0,
        avg_power_w=180,
        workout_name="Manual ERG",
        samples=[_sample(float(i), 180) for i in range(1, 6)],
    )
    saved = save_ride(recording, repo=repo, rides_dir=rides_dir)
    assert saved is not None
    assert saved["avg_power_w"] == 180
    listed = repo.list_rides()
    assert len(listed) == 1
    ride = repo.get_ride(saved["id"])
    assert ride is not None
    assert Path(ride["fit_path"]).is_file()
    assert download_filename(ride).startswith("steadyGrind-20261003-")

    deleted = repo.delete_ride(saved["id"])
    assert deleted is not None
    delete_ride_files(deleted)
    assert not Path(deleted["fit_path"]).exists()
    assert repo.list_rides() == []


def test_save_skips_short_recording(tmp_path: Path):
    repo = Repository(tmp_path / "test.db")
    recording = RideRecording(
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
        duration_s=0.5,
        avg_power_w=100,
        workout_name=None,
        samples=[],
    )
    assert save_ride(recording, repo=repo, rides_dir=tmp_path / "rides") is None
    assert repo.list_rides() == []


@pytest.mark.asyncio
async def test_engine_records_samples_while_running():
    trainer = SimulatedTrainer()
    await trainer.connect("127.0.0.1", 36866)
    engine = WorkoutEngine(trainer, ftp_w=200, auto_pause_idle_s=30.0)
    engine.load_manual(120)
    await engine.start()
    engine.update_metrics(BikeData(power_w=140, cadence_rpm=90.0, speed_kph=30.0))
    for _ in range(3):
        async with engine._lock:  # noqa: SLF001
            await engine._on_tick()  # noqa: SLF001
    recording = engine.take_ride_recording()
    assert recording is not None
    assert recording.duration_s >= 3.0
    assert len(recording.samples) >= 3
    assert recording.avg_power_w is not None
    await engine.stop()
    await engine.shutdown()
    await trainer.disconnect()


@pytest.mark.asyncio
async def test_stop_command_saves_emulator_ride(tmp_path: Path):
    """Emulator (SimulatedTrainer) rides must save on Stop like Real KICKR."""
    trainer = SimulatedTrainer()
    assert trainer.emulator is True
    await trainer.connect("127.0.0.1", 36866)
    engine = WorkoutEngine(trainer, ftp_w=200, auto_pause_idle_s=30.0)
    engine.load_manual(100)
    await engine.start()
    engine.update_metrics(BikeData(power_w=120, cadence_rpm=85.0, speed_kph=25.0))
    for _ in range(2):
        async with engine._lock:  # noqa: SLF001
            await engine._on_tick()  # noqa: SLF001

    settings = MagicMock()
    settings.rides_dir = tmp_path / "rides"
    repo = Repository(tmp_path / "db.sqlite")
    req = MagicMock()
    req.app.state = MagicMock()
    req.app.state.engine = engine
    req.app.state.trainer = trainer
    req.app.state.repo = repo
    req.app.state.settings = settings

    out = await routes_mod.session_command(
        routes_mod.CommandBody(command="stop"), req
    )
    assert out["ok"] is True
    assert out.get("saved_ride") is not None
    listed = repo.list_rides()
    assert len(listed) == 1
    fit = Path(repo.get_ride(listed[0]["id"])["fit_path"])
    assert fit.is_file() and fit.stat().st_size > 50
    assert engine.live.engine_state == EngineState.FINISHED
    await engine.shutdown()
    await trainer.disconnect()


@pytest.mark.asyncio
async def test_stop_skips_save_when_no_elapsed(tmp_path: Path):
    engine = MagicMock()
    engine.take_ride_recording.return_value = None
    engine.live = LiveState(engine_state=EngineState.FINISHED)
    engine.stop = MagicMock(return_value=None)

    async def _stop() -> None:
        return None

    engine.stop = _stop
    req = MagicMock()
    req.app.state = MagicMock()
    req.app.state.engine = engine
    req.app.state.repo = Repository(tmp_path / "db.sqlite")
    req.app.state.settings = MagicMock(rides_dir=tmp_path / "rides")

    out = await routes_mod.session_command(
        routes_mod.CommandBody(command="stop"), req
    )
    assert "saved_ride" not in out
