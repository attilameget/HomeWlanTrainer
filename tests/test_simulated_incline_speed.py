"""Emulator virtual speed responds to incline."""

from __future__ import annotations

import pytest

from steadygrind.trainer.simulated import SimulatedTrainer


def test_simulated_speed_slows_on_climb_and_speeds_on_descent():
    trainer = SimulatedTrainer(cadence_rpm=85.0)
    trainer._incline_pct = 0.0
    flat = trainer.speed_kph_for_cadence(85.0)
    assert abs(flat - 34.0) < 1e-9

    trainer._incline_pct = 10.0
    climb = trainer.speed_kph_for_cadence(85.0)
    assert climb < flat
    assert abs(climb - flat / 1.35) < 1e-9

    trainer._incline_pct = -5.0
    descent = trainer.speed_kph_for_cadence(85.0)
    assert descent > flat


@pytest.mark.asyncio
async def test_set_incline_updates_reported_speed():
    trainer = SimulatedTrainer(cadence_rpm=90.0, tick_s=0.05, ramp_w_s=500.0)
    await trainer.connect("127.0.0.1", 36866)
    await trainer.request_control()
    await trainer.set_target_power(150)
    await trainer.set_incline(0.0)

    flat_speed = None
    async for data in trainer.live_metrics():
        if data.speed_kph is not None and data.power_w and data.power_w > 0:
            flat_speed = data.speed_kph
            break
    assert flat_speed is not None

    await trainer.set_incline(8.0)
    climb_speed = None
    async for data in trainer.live_metrics():
        if data.speed_kph is not None:
            climb_speed = data.speed_kph
            break
    assert climb_speed is not None
    assert climb_speed < flat_speed

    await trainer.disconnect()
