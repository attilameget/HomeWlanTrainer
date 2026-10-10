"""SimulatedTrainer / emulator unit tests."""

from __future__ import annotations

import asyncio

import pytest

from steadygrind.trainer.simulated import PRESETS, SimulatedTrainer


@pytest.mark.asyncio
async def test_ramp_toward_target():
    trainer = SimulatedTrainer(ramp_w_s=200.0, tick_s=0.05)
    await trainer.connect("127.0.0.1", 36866)
    await trainer.request_control()
    await trainer.set_target_power(200)

    samples = []
    async def collect():
        async for data in trainer.live_metrics():
            samples.append(data.power_w)
            if data.power_w >= 195 or len(samples) > 80:
                break

    await asyncio.wait_for(collect(), timeout=5.0)
    assert samples[0] < samples[-1]
    assert samples[-1] >= 195
    await trainer.disconnect()


@pytest.mark.asyncio
async def test_pause_and_resume():
    trainer = SimulatedTrainer(ramp_w_s=500.0, tick_s=0.05)
    await trainer.connect("127.0.0.1", 36866)
    await trainer.request_control()
    await trainer.set_target_power(150)
    await asyncio.sleep(0.3)
    await trainer.stop_pause(pause=True)
    assert trainer.status()["paused"] is True
    await asyncio.sleep(0.25)
    paused_power = trainer.status()["power_w"]
    await asyncio.sleep(0.25)
    # While paused, power should not climb toward the hold target
    assert trainer.status()["power_w"] <= paused_power
    await trainer.start_resume()
    assert trainer.status()["paused"] is False
    assert trainer.status()["target_w"] == 150
    await trainer.disconnect()


@pytest.mark.asyncio
async def test_quick_stages_preset_runs():
    trainer = SimulatedTrainer(ramp_w_s=400.0, tick_s=0.05)
    # Shrink preset durations for a fast test via direct segment override
    from steadygrind.trainer.simulated import PresetSegment

    PRESETS["test_fast"] = [
        PresetSegment("hold", 0.2, watts=100),
        PresetSegment("ramp", 0.3, watts=100, end_watts=180),
        PresetSegment("pause", 0.2),
        PresetSegment("hold", 0.2, watts=90),
    ]
    try:
        await trainer.run_preset("test_fast")
        assert trainer.status()["preset_name"] == "test_fast"
        await asyncio.sleep(1.2)
        # Preset should finish
        assert trainer.status()["preset_name"] is None
        assert trainer.status()["target_w"] == 90
    finally:
        PRESETS.pop("test_fast", None)
        await trainer.disconnect()


@pytest.mark.asyncio
async def test_unknown_preset_raises():
    trainer = SimulatedTrainer()
    with pytest.raises(ValueError, match="unknown preset"):
        await trainer.run_preset("nope")


@pytest.mark.asyncio
async def test_desk_hold_ignores_engine_target():
    trainer = SimulatedTrainer(ramp_w_s=500.0, tick_s=0.05)
    await trainer.connect("127.0.0.1", 36866)
    await trainer.request_control()
    await trainer.emulator_set_target(220)
    assert trainer.status()["desk_hold"] is True
    assert trainer.status()["target_w"] == 220
    # Engine keepalive / ERG must not overwrite desk hold
    await trainer.set_target_power(100)
    assert trainer.status()["target_w"] == 220
    await asyncio.sleep(0.4)
    assert trainer.status()["power_w"] >= 200
    await trainer.emulator_follow_engine()
    assert trainer.status()["desk_hold"] is False
    await trainer.set_target_power(100)
    assert trainer.status()["target_w"] == 100
    await trainer.disconnect()
