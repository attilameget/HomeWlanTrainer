"""Discovery helpers: IPv4-first resolution and LAN DirCon probe."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from steadygrind.trainer import discover as disc
from steadygrind.trainer.base import TrainerInfo


def test_is_ipv4() -> None:
    assert disc._is_ipv4("192.168.1.42")
    assert not disc._is_ipv4("KICKR.local")
    assert not disc._is_ipv4("::1")


@pytest.mark.asyncio
async def test_resolve_to_ipv4_passthrough() -> None:
    assert await disc.resolve_to_ipv4("10.0.0.5") == "10.0.0.5"


@pytest.mark.asyncio
async def test_resolve_to_ipv4_via_getaddrinfo() -> None:
    with patch.object(disc, "_resolve_hostname_sync", return_value="192.168.0.9"):
        assert await disc.resolve_to_ipv4("kickr.local") == "192.168.0.9"


@pytest.mark.asyncio
async def test_resolve_to_ipv4_dns_sd_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(disc.platform, "system", lambda: "Darwin")
    with patch.object(disc, "_resolve_hostname_sync", return_value=None):
        with patch.object(
            disc, "_dns_sd_resolve_ipv4", new=AsyncMock(return_value="192.168.1.77")
        ):
            assert await disc.resolve_to_ipv4("KICKR-ABC.local") == "192.168.1.77"


@pytest.mark.asyncio
async def test_discover_falls_back_to_lan_scan() -> None:
    fake = [TrainerInfo(name="KICKR @192.168.1.50", host="192.168.1.50", port=36866)]
    with patch.object(disc.platform, "system", lambda: "Linux"):
        with patch.object(disc, "_discover_zeroconf", new=AsyncMock(return_value=[])):
            with patch.object(
                disc, "_discover_lan_port_scan", new=AsyncMock(return_value=fake)
            ) as scan:
                found = await disc.discover_dircon(timeout_s=2.0)
    assert found == fake
    scan.assert_awaited()


@pytest.mark.asyncio
async def test_lan_scan_probes_open_port() -> None:
    with patch.object(disc, "_local_ipv4_addrs", return_value=["192.168.1.10"]):

        async def fake_open(ip: str, port: int, timeout_s: float) -> bool:
            return ip == "192.168.1.50"

        with patch.object(disc, "_tcp_open", side_effect=fake_open):
            found = await disc._discover_lan_port_scan(timeout_s=2.0)
    assert len(found) == 1
    assert found[0].host == "192.168.1.50"
    assert found[0].port == 36866


@pytest.mark.asyncio
async def test_dns_sd_lookup_resolves_hostname_to_ip() -> None:
    import asyncio

    class FakeProc:
        def __init__(self) -> None:
            self.stdout = self
            self._lines = [
                b"  KICKR-1._wahoo-fitness-tnp._tcp.local. can be reached at "
                b"KICKR-1.local.:36866\n"
            ]
            self._i = 0

        async def readline(self) -> bytes:
            if self._i >= len(self._lines):
                return b""
            line = self._lines[self._i]
            self._i += 1
            return line

        def terminate(self) -> None:
            return None

        def kill(self) -> None:
            return None

        async def wait(self) -> int:
            return 0

    async def fake_exec(*_a, **_k):
        return FakeProc()

    with patch.object(asyncio, "create_subprocess_exec", side_effect=fake_exec):
        with patch.object(
            disc, "resolve_to_ipv4", new=AsyncMock(return_value="192.168.1.20")
        ):
            info = await disc._dns_sd_lookup("KICKR-1", timeout_s=2.0)
    assert info.host == "192.168.1.20"
    assert info.port == 36866
