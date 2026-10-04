"""mDNS / LAN discovery for Wahoo Direct Connect trainers.

Always prefer a dotted-quad IPv4 before returning a trainer — hostname-only
``.local`` results often fail to connect when Local Network permission is
partial or getaddrinfo is flaky.
"""

from __future__ import annotations

import asyncio
import ipaddress
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
DIRCON_PORT = 36866


def _is_ipv4(host: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(host), ipaddress.IPv4Address)
    except ValueError:
        return False


def _ipv4_host(info: AsyncServiceInfo) -> str | None:
    for addr in info.addresses:
        if len(addr) == 4:
            return socket.inet_ntoa(addr)
    parsed = info.parsed_addresses()
    for host in parsed:
        if _is_ipv4(host):
            return host
    return None


def _serial_from_properties(properties: dict[Any, Any] | None) -> str | None:
    if not properties:
        return None
    for key, value in properties.items():
        k = key.decode() if isinstance(key, bytes) else str(key)
        if k.lower() in ("serial", "serialnumber", "serial-number", "sn", "deviceid") and value:
            return value.decode() if isinstance(value, bytes) else str(value)
    return None


def _resolve_hostname_sync(host: str) -> str | None:
    """Resolve hostname to IPv4 via getaddrinfo. Returns None if not an IPv4."""
    host = host.rstrip(".")
    if _is_ipv4(host):
        return host
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
        if infos:
            ip = infos[0][4][0]
            return ip if _is_ipv4(ip) else None
    except OSError as exc:
        logger.debug("could not resolve %s: %s", host, exc)
    return None


async def _dns_sd_resolve_ipv4(hostname: str, timeout_s: float = 3.0) -> str | None:
    """macOS: `dns-sd -G v4 host.local` → IPv4 address."""
    if platform.system() != "Darwin":
        return None
    host = hostname.rstrip(".")
    if _is_ipv4(host):
        return host
    if not host.endswith(".local"):
        host = f"{host}.local"
    proc = await asyncio.create_subprocess_exec(
        "dns-sd",
        "-G",
        "v4",
        host,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    assert proc.stdout is not None
    # dns-sd -G lines include: "... Timestamp ... Address <ipv4>"
    addr_re = re.compile(r"\bAddress\s+(\d+\.\d+\.\d+\.\d+)\b")
    try:
        deadline = asyncio.get_running_loop().time() + timeout_s
        while asyncio.get_running_loop().time() < deadline:
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=0.4)
            except asyncio.TimeoutError:
                continue
            if not line:
                break
            text = line.decode(errors="replace")
            m = addr_re.search(text)
            if m and _is_ipv4(m.group(1)):
                return m.group(1)
    finally:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            proc.kill()
    return None


async def resolve_to_ipv4(host: str, timeout_s: float = 3.0) -> str | None:
    """Return a dotted-quad IPv4 for `host`, or None if it cannot be resolved."""
    host = (host or "").strip().rstrip(".")
    if not host:
        return None
    if _is_ipv4(host):
        return host
    ip = await asyncio.to_thread(_resolve_hostname_sync, host)
    if ip:
        return ip
    return await _dns_sd_resolve_ipv4(host, timeout_s=timeout_s)


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
            host = await resolve_to_ipv4(info.server, timeout_s=min(4.0, timeout_s))
        if not host or not _is_ipv4(host):
            logger.warning(
                "discovered %s without usable IPv4 (server=%s)",
                name,
                getattr(info, "server", None),
            )
            return
        display = name
        suffix = f".{SERVICE_TYPE}"
        if display.endswith(suffix):
            display = display[: -len(suffix)]
        trainer = TrainerInfo(
            name=display or name,
            host=host,
            port=info.port or DIRCON_PORT,
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
    return [t for t in trainers if t.host and _is_ipv4(t.host)]


async def _dns_sd_lookup(instance_name: str, timeout_s: float = 4.0) -> TrainerInfo:
    """Resolve instance via `dns-sd -L` → IPv4:port (+ optional serial)."""
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
    port = DIRCON_PORT
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
                # Resolve hostname → IPv4 before accepting the result
                host = await resolve_to_ipv4(m.group(1), timeout_s=min(3.0, timeout_s))
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


def _local_ipv4_addrs() -> list[str]:
    """Best-effort primary LAN IPv4 addresses for this host."""
    found: set[str] = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM):
            addr = info[4][0]
            if not addr.startswith("127."):
                found.add(addr)
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        addr = probe.getsockname()[0]
        probe.close()
        if not addr.startswith("127."):
            found.add(addr)
    except OSError:
        pass
    return sorted(found)


async def _tcp_open(ip: str, port: int, timeout_s: float) -> bool:
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=timeout_s
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        return True
    except Exception:  # noqa: BLE001
        return False


async def _discover_lan_port_scan(
    timeout_s: float, port: int = DIRCON_PORT
) -> list[TrainerInfo]:
    """Scan local /24 subnets for an open Direct Connect TCP port (find IP first)."""
    locals_ = _local_ipv4_addrs()
    if not locals_:
        logger.info("LAN port scan skipped — no local IPv4 interface")
        return []

    candidates: list[str] = []
    self_ips = set(locals_)
    for local in locals_:
        try:
            net = ipaddress.ip_network(f"{local}/24", strict=False)
        except ValueError:
            continue
        for host in net.hosts():
            ip = str(host)
            if ip in self_ips:
                continue
            candidates.append(ip)

    if not candidates:
        return []

    # Bound total work: ~timeout_s wall clock with concurrency
    per_host = min(0.35, max(0.12, timeout_s / 40.0))
    sem = asyncio.Semaphore(64)
    hits: list[str] = []

    async def check(ip: str) -> None:
        async with sem:
            if await _tcp_open(ip, port, per_host):
                hits.append(ip)
                logger.info("LAN probe found open %s:%s", ip, port)

    logger.info(
        "LAN port scan for DirCon :%s across %s hosts (%.2fs/host)…",
        port,
        len(candidates),
        per_host,
    )
    try:
        await asyncio.wait_for(
            asyncio.gather(*(check(ip) for ip in candidates)),
            timeout=max(timeout_s, 2.0),
        )
    except asyncio.TimeoutError:
        logger.info("LAN port scan timed out with %s hit(s)", len(hits))

    return [
        TrainerInfo(name=f"KICKR @{ip}", host=ip, port=port, serial=None)
        for ip in sorted(set(hits))
    ]


async def discover_dircon(timeout_s: float = 8.0) -> list[TrainerInfo]:
    """Browse the LAN for Wahoo Direct Connect (`_wahoo-fitness-tnp._tcp`).

    Order: mDNS (zeroconf, and dns-sd in parallel on macOS) → LAN TCP :36866
    probe. Every result has a dotted-quad IPv4 host.
    """
    timeout_s = max(2.0, float(timeout_s))

    if platform.system() == "Darwin":
        # Run Bonjour CLI alongside zeroconf — either may win.
        zc_task = asyncio.create_task(_discover_zeroconf(timeout_s))
        sd_task = asyncio.create_task(_discover_dns_sd(timeout_s))
        done, pending = await asyncio.wait(
            {zc_task, sd_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        found: list[TrainerInfo] = []
        for task in done:
            try:
                found = task.result() or []
            except Exception as exc:  # noqa: BLE001
                logger.warning("discovery task failed: %s", exc)
                found = []
            if found:
                for t in pending:
                    t.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                return found
        # Wait for the other
        if pending:
            rest = await asyncio.gather(*pending, return_exceptions=True)
            for item in rest:
                if isinstance(item, list) and item:
                    return item
        # Both empty — fall through to LAN scan with a fresh budget
        logger.info("mDNS found nothing; probing LAN for TCP :%s", DIRCON_PORT)
        return await _discover_lan_port_scan(timeout_s)

    found = await _discover_zeroconf(timeout_s)
    if found:
        return found

    logger.info("zeroconf found nothing; probing LAN for TCP :%s", DIRCON_PORT)
    found = await _discover_lan_port_scan(timeout_s)
    if found:
        return found

    logger.warning("no Direct Connect trainers discovered")
    return []
