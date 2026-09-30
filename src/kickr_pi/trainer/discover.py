"""mDNS discovery for Wahoo Direct Connect trainers."""

from __future__ import annotations

import asyncio
import logging

from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf
from zeroconf.asyncio import AsyncZeroconf

from kickr_pi.trainer.base import TrainerInfo

logger = logging.getLogger(__name__)

SERVICE_TYPE = "_wahoo-fitness-tnp._tcp.local."


async def discover_dircon(timeout_s: float = 5.0) -> list[TrainerInfo]:
    """Browse the LAN for Wahoo Direct Connect trainers."""
    found: dict[str, TrainerInfo] = {}
    azc = AsyncZeroconf()
    zc = azc.zeroconf

    def on_service_state_change(
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        if state_change not in (ServiceStateChange.Added, ServiceStateChange.Updated):
            return
        info = zeroconf.get_service_info(service_type, name)
        if info is None or not info.addresses:
            return
        host = ".".join(str(b) for b in info.addresses[0])
        # Prefer IPv4
        for addr in info.addresses:
            if len(addr) == 4:
                host = ".".join(str(b) for b in addr)
                break
        serial = None
        if info.properties:
            for key, value in info.properties.items():
                k = key.decode() if isinstance(key, bytes) else str(key)
                if k.lower() in ("serial", "serialnumber", "sn") and value:
                    serial = value.decode() if isinstance(value, bytes) else str(value)
        display = name.replace(f".{SERVICE_TYPE}", "").rstrip(".")
        found[name] = TrainerInfo(
            name=display,
            host=host,
            port=info.port or 36866,
            serial=serial,
        )
        logger.info("discovered trainer %s at %s:%s", display, host, info.port)

    browser = ServiceBrowser(zc, SERVICE_TYPE, handlers=[on_service_state_change])
    try:
        await asyncio.sleep(timeout_s)
    finally:
        browser.cancel()
        await azc.async_close()

    return list(found.values())
