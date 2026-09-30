import asyncio

import pytest

from kickr_pi.engine.engine import WorkoutEngine
from kickr_pi.engine.models import EngineState, demo_workout
from kickr_pi.garmin.parser import parse_garmin_workout
from kickr_pi.trainer.simulated import SimulatedTrainer


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
