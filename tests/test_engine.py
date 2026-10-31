import asyncio

import pytest

from steadygrind.engine.engine import WorkoutEngine
from steadygrind.engine.models import EngineState, Stage, Workout, demo_workout
from steadygrind.garmin.parser import parse_garmin_workout
from steadygrind.trainer.ftms import BikeData
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


def test_parse_keeps_requested_id_when_payload_omits_it():
    raw = {
        "name": "Sprint",
        "stages": [
            {
                "index": 0,
                "name": "Recovery",
                "kind": "recovery",
                "duration_s": 120,
                "target_mode": "erg",
                "target_w": 90,
            }
        ],
    }
    missing = parse_garmin_workout(raw, ftp_w=200)
    assert missing.id == "unknown"
    kept = parse_garmin_workout(raw, ftp_w=200, fallback_id="48211")
    assert kept.id == "48211"
    assert kept.stages[0].target_w == 90


@pytest.mark.asyncio
async def test_total_remaining_ignores_open_ended_cooldown():
    """Garmin cooldowns are often open-ended; Total must still show timed leftovers."""
    trainer = SimulatedTrainer()
    await trainer.connect("127.0.0.1", 36866)
    workout = Workout(
        id="open-cd",
        name="Open cooldown",
        sport="cycling",
        stages=[
            Stage(0, "Warmup", "warmup", 600, "erg", target_w=120),
            Stage(1, "Work", "interval", 300, "erg", target_w=200),
            Stage(2, "Cooldown", "cooldown", None, "resistance", resistance_pct=20),
        ],
    )
    engine = WorkoutEngine(trainer, ftp_w=200, keepalive_s=1.0)
    engine.load(workout)
    await engine.start()
    live = engine.live
    assert live.stage_remaining_s == 600
    # Timed leftovers only — open cooldown must not blank Total.
    assert live.total_remaining_s == 900
    await engine.stop()
    await engine.shutdown()
    await trainer.disconnect()


@pytest.mark.asyncio
async def test_engine_sends_incline_on_start_default_flat():
    trainer = SimulatedTrainer()
    await trainer.connect("127.0.0.1", 36866)
    engine = WorkoutEngine(trainer, ftp_w=200, incline_pct=0.0, keepalive_s=1.0)
    engine.load(demo_workout(200))
    await engine.start()
    assert engine.live.incline_pct == 0.0
    assert trainer.status()["incline_pct"] == 0.0
    await engine.adjust_incline(1.0)
    assert engine.live.incline_pct == 1.0
    assert trainer.status()["incline_pct"] == 1.0
    await engine.stop()
    await engine.shutdown()
    await trainer.disconnect()


def test_engine_exposes_loaded_workout_for_the_ride_chart():
    trainer = SimulatedTrainer()
    engine = WorkoutEngine(trainer, ftp_w=200)
    workout = parse_garmin_workout(
        {
            "name": "Sprint",
            "stages": [
                {
                    "index": 0,
                    "name": "Recovery",
                    "kind": "recovery",
                    "duration_s": 120,
                    "target_mode": "erg",
                    "target_w": 90,
                }
            ],
        },
        ftp_w=200,
        fallback_id="48211",
    )
    engine.load(workout)
    assert engine.workout is workout
    assert engine.live.workout_id == "48211"
    assert engine.workout.stages[0].name == "Recovery"


@pytest.mark.asyncio
async def test_engine_integrates_distance_and_ascent_from_speed():
    trainer = SimulatedTrainer()
    await trainer.connect("127.0.0.1", 36866)
    engine = WorkoutEngine(trainer, ftp_w=200, incline_pct=10.0, keepalive_s=30.0)
    engine.load_manual(150)
    await engine.start()
    engine.update_metrics(BikeData(speed_kph=36.0, cadence_rpm=90.0, power_w=150))
    # 36 km/h → 10 m/s; one second → 10 m; ~0.995 m ascent at 10%.
    engine._accumulate_distance(1.0)
    assert abs(engine.live.distance_m - 10.0) < 1e-6
    assert abs(engine.live.ascent_m - 0.9950371906) < 1e-6
    rec = engine.take_ride_recording()
    # Under 1 s elapsed → None; bump elapsed so recording includes distance.
    engine._total_elapsed = 1.0
    rec = engine.take_ride_recording()
    assert rec is not None
    assert abs((rec.distance_m or 0) - 10.0) < 1e-6
    assert abs((rec.ascent_m or 0) - 0.9950371906) < 1e-6
    await engine.stop()
    await engine.shutdown()
    await trainer.disconnect()


@pytest.mark.asyncio
async def test_engine_prefers_trainer_total_distance():
    trainer = SimulatedTrainer()
    await trainer.connect("127.0.0.1", 36866)
    engine = WorkoutEngine(trainer, ftp_w=200, incline_pct=5.0, keepalive_s=30.0)
    engine.load_manual(150)
    await engine.start()
    engine.update_metrics(
        BikeData(speed_kph=20.0, cadence_rpm=80.0, power_w=150, distance_m=1000)
    )
    assert engine._trainer_distance_baseline == 1000.0
    engine.update_metrics(
        BikeData(speed_kph=20.0, cadence_rpm=80.0, power_w=150, distance_m=1250)
    )
    engine._accumulate_distance(1.0)
    assert abs(engine.live.distance_m - 250.0) < 1e-6
    assert engine.live.ascent_m > 0
    await engine.stop()
    await engine.shutdown()
    await trainer.disconnect()
