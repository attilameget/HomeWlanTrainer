import asyncio

import pytest

from steadygrind.engine.engine import WorkoutEngine
from steadygrind.engine.models import EngineState, demo_workout
from steadygrind.garmin.parser import parse_garmin_workout
from steadygrind.trainer.simulated import SimulatedTrainer


@pytest.mark.asyncio
async def test_engine_runs_demo_against_simulator():
    trainer = SimulatedTrainer()
    await trainer.connect("127.0.0.1", 36866)
    engine = WorkoutEngine(trainer, ftp_w=200, keepalive_s=1.0)
    engine.load(demo_workout(200))
    assert engine.live.engine_state == EngineState.LOADED

    await engine.start()
    assert engine.live.engine_state == EngineState.RUNNING
    assert engine.live.target_w > 0

    # Let a few ticks / metrics flow
    await asyncio.sleep(1.5)
    assert engine.live.power_w >= 0

    await engine.pause()
    assert engine.live.engine_state == EngineState.PAUSED
    await engine.resume()
    assert engine.live.engine_state == EngineState.RUNNING
    await engine.adjust_intensity(5)
    assert engine.live.intensity_pct == 105
    await engine.stop()
    assert engine.live.engine_state == EngineState.FINISHED
    await engine.shutdown()
    await trainer.disconnect()


@pytest.mark.asyncio
async def test_auto_pause_resume_when_trainer_pauses():
    trainer = SimulatedTrainer(ramp_w_s=500.0, tick_s=0.05)
    await trainer.connect("127.0.0.1", 36866)
    engine = WorkoutEngine(
        trainer,
        ftp_w=200,
        keepalive_s=30.0,
        auto_pause_idle_s=30.0,  # don't trip cadence idle in this test
    )
    engine.load_manual(150)
    await engine.start()
    assert engine.live.engine_state == EngineState.RUNNING

    await trainer.emulator_pause()
    # Metrics loop should notice trainer.paused
    for _ in range(40):
        if engine.live.engine_state == EngineState.PAUSED:
            break
        await asyncio.sleep(0.05)
    assert engine.live.engine_state == EngineState.PAUSED
    assert "trainer" in (engine.live.message or "").lower()
    paused_elapsed = engine.live.total_elapsed_s
    await asyncio.sleep(0.6)
    assert engine.live.total_elapsed_s == paused_elapsed  # clock frozen

    await trainer.emulator_resume()
    for _ in range(40):
        if engine.live.engine_state == EngineState.RUNNING:
            break
        await asyncio.sleep(0.05)
    assert engine.live.engine_state == EngineState.RUNNING

    await engine.stop()
    await engine.shutdown()
    await trainer.disconnect()


@pytest.mark.asyncio
async def test_user_pause_does_not_auto_resume():
    trainer = SimulatedTrainer(ramp_w_s=500.0, tick_s=0.05)
    await trainer.connect("127.0.0.1", 36866)
    engine = WorkoutEngine(trainer, ftp_w=200, auto_pause_idle_s=30.0)
    engine.load_manual(120)
    await engine.start()
    await engine.pause()
    assert engine.live.engine_state == EngineState.PAUSED
    # Trainer still producing cadence after a forced resume on trainer side
    await trainer.emulator_resume()
    await asyncio.sleep(0.4)
    assert engine.live.engine_state == EngineState.PAUSED

    await engine.resume()
    assert engine.live.engine_state == EngineState.RUNNING
    await engine.stop()
    await engine.shutdown()
    await trainer.disconnect()


@pytest.mark.asyncio
async def test_auto_pause_on_zero_cadence_freezes_clock():
    trainer = SimulatedTrainer(ramp_w_s=500.0, tick_s=0.05, cadence_rpm=0.0)
    await trainer.connect("127.0.0.1", 36866)
    engine = WorkoutEngine(trainer, ftp_w=200, auto_pause_idle_s=2.0)
    engine.load_manual(100)
    await engine.start()
    for _ in range(50):
        if engine.live.engine_state == EngineState.PAUSED:
            break
        await asyncio.sleep(0.1)
    assert engine.live.engine_state == EngineState.PAUSED
    assert "pedaling" in (engine.live.message or "").lower()
    # Clock must never have advanced without cadence
    assert engine.live.total_elapsed_s == 0.0
    frozen = engine.live.total_elapsed_s
    await asyncio.sleep(0.8)
    assert engine.live.total_elapsed_s == frozen

    await engine.stop()
    await engine.shutdown()
    await trainer.disconnect()


@pytest.mark.asyncio
async def test_timer_starts_only_when_cadence_present():
    trainer = SimulatedTrainer(ramp_w_s=500.0, tick_s=0.05, cadence_rpm=0.0)
    await trainer.connect("127.0.0.1", 36866)
    engine = WorkoutEngine(
        trainer,
        ftp_w=200,
        auto_pause_idle_s=30.0,  # stay Running while we assert freeze
    )
    engine.load_manual(100)
    await engine.start()
    await asyncio.sleep(1.6)
    assert engine.live.engine_state == EngineState.RUNNING
    assert engine.live.total_elapsed_s == 0.0

    trainer._base_cadence = 85.0
    trainer._cadence = 85.0
    for _ in range(40):
        if engine.live.total_elapsed_s >= 1.0:
            break
        await asyncio.sleep(0.1)
    assert engine.live.total_elapsed_s >= 1.0

    await engine.stop()
    await engine.shutdown()
    await trainer.disconnect()


def test_parse_normalized_stages():
    raw = {
        "id": "x",
        "name": "Test",
        "sport": "cycling",
        "stages": [
            {
                "index": 0,
                "name": "A",
                "kind": "interval",
                "duration_s": 30,
                "target_mode": "erg",
                "target_w": 180,
            }
        ],
    }
    w = parse_garmin_workout(raw, ftp_w=200)
    assert w.total_s == 30
    assert w.stages[0].target_w == 180


def test_parse_garmin_repeat_and_ftp():
    raw = {
        "workoutId": 99,
        "workoutName": "Repeats",
        "sportType": {"sportTypeKey": "cycling"},
        "workoutSegments": [
            {
                "workoutSteps": [
                    {
                        "type": "RepeatStep",
                        "numberOfIterations": 2,
                        "steps": [
                            {
                                "intensity": "interval",
                                "durationType": "time",
                                "durationValue": 10,
                                "targetType": "percent.of.ftp",
                                "targetValue": 90,
                            },
                            {
                                "intensity": "recovery",
                                "durationType": "time",
                                "durationValue": 5,
                                "targetType": "watt",
                                "targetValue": 100,
                            },
                        ],
                    }
                ]
            }
        ],
    }
    w = parse_garmin_workout(raw, ftp_w=200)
    assert len(w.stages) == 4
    assert w.stages[0].target_w == 180
    assert w.stages[1].target_w == 100
