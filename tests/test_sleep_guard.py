import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from steadygrind.platform_sleep import SleepGuard


@pytest.mark.asyncio
async def test_sleep_guard_noop_when_not_darwin():
    guard = SleepGuard()
    guard._enabled = False
    await guard.acquire()
    assert guard.active is False
    await guard.release()


@pytest.mark.asyncio
async def test_sleep_guard_starts_caffeinate_on_darwin():
    guard = SleepGuard()
    guard._enabled = True
    fake = AsyncMock()
    fake.pid = 12345
    fake.returncode = None
    fake.wait = AsyncMock(return_value=0)
    fake.terminate = lambda: None
    fake.kill = lambda: None

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fake)) as spawn:
        await guard.sync("running")
        spawn.assert_awaited()
        assert guard.active is True
        args = spawn.await_args.args
        assert args[0] == "caffeinate"
        assert "-dims" in args

        await guard.sync("running")  # idempotent
        assert spawn.await_count == 1

        await guard.sync("finished")
        assert guard.active is False


@pytest.mark.asyncio
async def test_on_live_schedules_sync():
    guard = SleepGuard()
    guard._enabled = False
    guard.sync = AsyncMock()
    live = SimpleNamespace(engine_state=SimpleNamespace(value="paused"))
    guard.on_live(live)
    await asyncio.sleep(0)
    guard.sync.assert_awaited_with("paused")
