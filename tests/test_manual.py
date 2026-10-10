import pytest

from steadygrind.engine.engine import WorkoutEngine
from steadygrind.engine.models import EngineState, manual_workout
from steadygrind.trainer.simulated import SimulatedTrainer


@pytest.mark.asyncio
async def test_manual_set_and_adjust_watts():
    trainer = SimulatedTrainer()
    await trainer.connect("127.0.0.1", 36866)
    engine = WorkoutEngine(trainer, ftp_w=200, keepalive_s=1.0)
    engine.load(manual_workout(100))
    await engine.start()
    assert engine.live.manual is True
    assert engine.live.target_w == 100

    await engine.set_target_watts(150)
    assert engine.live.target_w == 150
    assert engine.live.stage_name == "Hold 150 W"

    await engine.adjust_target_watts(-25)
    assert engine.live.target_w == 125

    await engine.stop()
    assert engine.live.engine_state == EngineState.FINISHED
    await engine.shutdown()
    await trainer.disconnect()
