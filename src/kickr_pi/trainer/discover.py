"""mDNS discovery for Wahoo Direct Connect trainers."""

from __future__ import annotations

import asyncio
import logging
import platform
import re
import socket
from typing import Any

from zeroconf import IPVersion, InterfaceChoice, ServiceStateChange, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from kickr_pi.trainer.base import TrainerInfo

logger = logging.getLogger(__name__)

SERVICE_TYPE = "_wahoo-fitness-tnp._tcp.local."
SERVICE_TYPE_SHORT = "_wahoo-fitness-tnp._tcp"


def _ipv4_host(info: AsyncServiceInfo) -> str | None:
    for addr in info.addresses:
        if len(addr) == 4:
            return socket.inet_ntoa(addr)
    parsed = info.parsed_addresses()
    for host in parsed:
        if ":" not in host:
            return host
    return parsed[0] if parsed else None


def _serial_from_properties(properties: dict[Any, Any] | None) -> str | None:
    if not properties:
        return None
    for key, value in properties.items():
        k = key.decode() if isinstance(key, bytes) else str(key)
        if k.lower() in ("serial", "serialnumber", "serial-number", "sn", "deviceid") and value:
            return value.decode() if isinstance(value, bytes) else str(value)
    return None


def _resolve_hostname(host: str) -> str:
    """Prefer IPv4 for a .local hostname; fall back to the hostname itself."""
    host = host.rstrip(".")
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
        if infos:
            return infos[0][4][0]
    except OSError as exc:
        logger.debug("could not resolve %s: %s", host, exc)
    return host


async def _discover_zeroconf(timeout_s: float) -> list[TrainerInfo]:
    found: dict[str, TrainerInfo] = {}
    pending: set[asyncio.Task[None]] = set()
    azc = AsyncZeroconf(interfaces=InterfaceChoice.All, ip_version=IPVersion.V4Only)
    zc = azc.zeroconf

    async def resolve(name: str) -> None:
        info = AsyncServiceInfo(SERVICE_TYPE, name)
        ok = await info.async_request(zc, timeout=max(1000, int(timeout_s * 1000)))
        if not ok:
            logger.debug("no service info for %s", name)
            return
        host = _ipv4_host(info)
        if not host and info.server:
            host = _resolve_hostname(info.server)
        if not host:
            logger.warning("discovered %s without usable address", name)
            return
        display = name
        suffix = f".{SERVICE_TYPE}"
        if display.endswith(suffix):
            display = display[: -len(suffix)]
        trainer = TrainerInfo(
            name=display or name,
            host=host,
            port=info.port or 36866,
            serial=_serial_from_properties(info.properties),
        )
        found[name] = trainer
        logger.info(
            "discovered trainer %s at %s:%s (serial=%s)",
            trainer.name,
            trainer.host,
            trainer.port,
            trainer.serial,
        )

    def on_service_state_change(
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        if state_change not in (ServiceStateChange.Added, ServiceStateChange.Updated):
            return
        task = asyncio.create_task(resolve(name))
        pending.add(task)
        task.add_done_callback(pending.discard)

    browser = AsyncServiceBrowser(zc, SERVICE_TYPE, handlers=[on_service_state_change])
    try:
        await asyncio.sleep(timeout_s)
        if pending:
            await asyncio.wait(pending, timeout=3.0)
    finally:
        await browser.async_cancel()
        await azc.async_close()
    return list(found.values())


async def _discover_dns_sd(timeout_s: float) -> list[TrainerInfo]:
    """macOS Bonjour CLI fallback – works when python-zeroconf misses LAN ads."""
    browse = await asyncio.create_subprocess_exec(
        "dns-sd",
        "-B",
        SERVICE_TYPE_SHORT,
        "local.",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    assert browse.stdout is not None
    names: list[str] = []
    pattern = re.compile(r"\bAdd\b.*?" + re.escape(SERVICE_TYPE_SHORT) + r"\.\s+(.+)$")
    try:
        deadline = asyncio.get_running_loop().time() + timeout_s
        while asyncio.get_running_loop().time() < deadline:
            try:
                line = await asyncio.wait_for(browse.stdout.readline(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            if not line:
                break
            text = line.decode(errors="replace").rstrip()
            match = pattern.search(text)
            if match:
                instance = match.group(1).strip()
                if instance and instance not in names:
                    names.append(instance)
                    logger.info("dns-sd browse found %s", instance)
    finally:
        browse.terminate()
        try:
            await asyncio.wait_for(browse.wait(), timeout=2.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            browse.kill()

    trainers: list[TrainerInfo] = []
    for name in names:
        trainers.append(await _dns_sd_lookup(name, timeout_s=max(3.0, timeout_s / 2)))
    return [t for t in trainers if t.host]


async def _dns_sd_lookup(instance_name: str, timeout_s: float = 4.0) -> TrainerInfo:
    """Resolve instance via `dns-sd -L` → host:port (+ optional serial)."""
    proc = await asyncio.create_subprocess_exec(
        "dns-sd",
        "-L",
        instance_name,
        SERVICE_TYPE_SHORT,
        "local.",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    assert proc.stdout is not None
    host: str | None = None
    port = 36866
    serial: str | None = None
    reached = re.compile(
        r"can be reached at\s+([^\s]+)\.?:(\d+)", re.IGNORECASE
    )
    serial_re = re.compile(r"serial-number=([^\s]+)", re.IGNORECASE)
    try:
        deadline = asyncio.get_running_loop().time() + timeout_s
        while asyncio.get_running_loop().time() < deadline and host is None:
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            if not line:
                break
            text = line.decode(errors="replace")
            m = reached.search(text)
            if m:
                host = _resolve_hostname(m.group(1))
                port = int(m.group(2))
            sm = serial_re.search(text)
            if sm:
                serial = sm.group(1)
            if host:
                break
    finally:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            proc.kill()

    return TrainerInfo(
        name=instance_name,
        host=host or "",
        port=port,
        serial=serial,
    )


async def discover_dircon(timeout_s: float = 8.0) -> list[TrainerInfo]:
    """Browse the LAN for Wahoo Direct Connect (`_wahoo-fitness-tnp._tcp`)."""
    found = await _discover_zeroconf(timeout_s)
    if found:
        return found

    if platform.system() == "Darwin":
        logger.info("zeroconf found nothing; trying macOS dns-sd fallback")
        found = await _discover_dns_sd(timeout_s)
        if found:
            return found

    logger.warning("no Direct Connect trainers discovered")
    return []
