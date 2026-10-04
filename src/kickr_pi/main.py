"""Application entry – FastAPI lifespan and CLI."""

from __future__ import annotations

import asyncio
import logging
import socket
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from kickr_pi.api.routes import router
from kickr_pi.config import Settings, apply_persisted_settings, load_settings, persisted_settings
from kickr_pi.engine.engine import WorkoutEngine
from kickr_pi.garmin.source import GarminSource
from kickr_pi.hr import create_heart_rate
from kickr_pi.hr.autoconnect import HeartRateAutoconnect
from kickr_pi.platform_sleep import SleepGuard
from kickr_pi.storage.repository import Repository
from kickr_pi.trainer.autoconnect import AutoconnectService
from kickr_pi.trainer.dircon import DirConTrainer
from kickr_pi.trainer.simulated import SimulatedTrainer

logger = logging.getLogger(__name__)


def _lan_ipv4_addresses() -> list[str]:
    """Best-effort list of non-loopback IPv4 addresses for phone-on-LAN URLs."""
    found: set[str] = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM):
            addr = info[4][0]
            if not addr.startswith("127."):
                found.add(addr)
    except OSError:
        pass
    # Also probe the default-route interface without sending packets
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            addr = probe.getsockname()[0]
            if not addr.startswith("127."):
                found.add(addr)
        finally:
            probe.close()
    except OSError:
        pass
    return sorted(found)


def _log_listen_urls(host: str, port: int) -> None:
    if host in ("0.0.0.0", "::", ""):
        urls = [f"http://127.0.0.1:{port}"]
        for ip in _lan_ipv4_addresses():
            urls.append(f"http://{ip}:{port}")
        logger.info("UI listening on all interfaces — open %s", " or ".join(urls))
    else:
        logger.info("UI listening at http://%s:%s", host, port)


def _resolve_web_dir() -> Path:
    """Web UI path — works from source and from a PyInstaller freeze."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        for candidate in (meipass / "kickr_pi" / "web", meipass / "web"):
            if candidate.is_dir():
                return candidate
    return Path(__file__).resolve().parent / "web"


WEB_DIR = _resolve_web_dir()


@dataclass
class AppState:
    settings: Settings
    trainer: Any
    engine: WorkoutEngine
    workout_source: Any
    repo: Repository
    sleep_guard: SleepGuard
    autoconnect: AutoconnectService | None = None
    heart_rate: Any = None
    hr_autoconnect: HeartRateAutoconnect | None = None


def create_trainer(mode: str) -> DirConTrainer | SimulatedTrainer:
    """Single factory for DirCon vs emulator (used by main and mode hot-swap)."""
    if mode == "simulated":
        return SimulatedTrainer()
    return DirConTrainer()


def build_trainer(settings: Settings) -> Any:
    return create_trainer(settings.trainer_mode)


async def connect_trainer(trainer: Any, settings: Settings) -> bool:
    """Discover and/or connect to a real DirCon trainer. Returns True on success.

    Never blocks forever: DirCon TCP connect is timed so Emulator↔Real mode
    switches work even when the bike is offline.
    """
    if settings.trainer_mode == "simulated":
        await trainer.connect("127.0.0.1", 36866)
        await trainer.request_control()
        return True

    host = settings.trainer_host
    port = settings.trainer_port

    if not host:
        logger.info(
            "discovering Wahoo Direct Connect trainers (timeout %.1fs)…",
            settings.discover_timeout_s,
        )
        found = await trainer.discover(settings.discover_timeout_s)
        if not found:
            logger.warning(
                "no KICKR found via mDNS (_wahoo-fitness-tnp._tcp); "
                "use Settings → Discover or set KICKR_TRAINER_HOST"
            )
            return False
        chosen = found[0]
        host, port = chosen.host, chosen.port
        settings.trainer_host = host
        settings.trainer_port = port
        settings.trainer_serial = chosen.serial
        logger.info(
            "using trainer %s at %s:%s",
            chosen.name,
            host,
            port,
        )

    connect_timeout = max(5.0, float(settings.discover_timeout_s) + 3.0)
    try:
        await asyncio.wait_for(trainer.connect(host, port), timeout=connect_timeout)
        await asyncio.wait_for(trainer.request_control(), timeout=5.0)
        logger.info("trainer connected at %s:%s", host, port)
        return True
    except asyncio.TimeoutError:
        logger.warning(
            "trainer connect to %s:%s timed out after %.1fs (bike offline?)",
            host,
            port,
            connect_timeout,
        )
        try:
            await trainer.disconnect()
        except Exception:  # noqa: BLE001
            pass
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("trainer connect to %s:%s failed: %s", host, port, exc)
        return False


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        repo = Repository(settings.db_path)
        saved = repo.get_settings()
        apply_persisted_settings(settings, saved)
        # Persist only the safety downgrade (simulated without allow → dircon).
        # Env overrides (KICKR_TRAINER_MODE=simulated) apply for this process only
        # so a one-off desk launch does not stick Emulator into SQLite forever.
        if (
            saved.get("trainer_mode") == "simulated"
            and settings.trainer_mode == "dircon"
            and not settings.allow_simulated
        ):
            repo.save_settings({**saved, **persisted_settings(settings)})
        logger.info(
            "startup trainer mode: %s (allow_simulated=%s)",
            settings.trainer_mode,
            settings.allow_simulated,
        )

        trainer = build_trainer(settings)
        if settings.auto_connect or settings.trainer_mode == "simulated":
            await connect_trainer(trainer, settings)

        heart_rate = create_heart_rate()
        engine = WorkoutEngine(
            trainer,
            ftp_w=settings.ftp_w,
            keepalive_s=settings.keepalive_s,
            erg_zero_cadence_drop=settings.erg_zero_cadence_drop,
            free_ride_resistance_tenths=settings.free_ride_resistance_tenths,
            heart_rate=heart_rate,
        )
        sleep_guard = SleepGuard()
        engine.add_listener(sleep_guard.on_live)
        source = GarminSource(settings.garth_dir, ftp_w=settings.ftp_w)
        restored = await source.try_restore_session()

        # Placeholder; get_app closes over app after FastAPI is created — set below
        state_box: dict[str, Any] = {"state": None}

        def _get_app() -> Any:
            return state_box["state"]

        autoconnect = AutoconnectService(
            get_app=_get_app,
            connect_fn=connect_trainer,
            interval_s=15.0,
        )
        hr_autoconnect = HeartRateAutoconnect(get_app=_get_app, interval_s=15.0)
        app_state = AppState(
            settings=settings,
            trainer=trainer,
            engine=engine,
            workout_source=source,
            repo=repo,
            sleep_guard=sleep_guard,
            autoconnect=autoconnect,
            heart_rate=heart_rate,
            hr_autoconnect=hr_autoconnect,
        )
        state_box["state"] = app_state
        app.state = app_state
        if (
            heart_rate.supported
            and settings.hr_auto_connect
            and settings.hr_device_id
        ):
            try:
                await heart_rate.connect(settings.hr_device_id, settings.hr_device_name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("heart rate connect at startup failed: %s", exc)
        logger.info(
            "steadyGrind ready on %s:%s (trainer=%s connected=%s host=%s garmin=%s auto_connect=%s hr=%s)",
            settings.host,
            settings.port,
            settings.trainer_mode,
            trainer.connected,
            settings.trainer_host,
            "ok" if restored else "logged-out",
            settings.auto_connect,
            "on" if heart_rate.supported else "off",
        )
        _log_listen_urls(settings.host, settings.port)
        autoconnect.start()
        hr_autoconnect.start()
        yield
        await hr_autoconnect.stop()
        await autoconnect.stop()
        await sleep_guard.release()
        await engine.shutdown()
        await heart_rate.disconnect()
        await trainer.disconnect()

    app = FastAPI(title="steadyGrind", lifespan=lifespan)
    app.include_router(router)

    if WEB_DIR.exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")

        @app.get("/")
        async def index() -> FileResponse:
            return FileResponse(WEB_DIR / "index.html")

    return app


def main() -> None:
    settings = load_settings()
    # Always bind all interfaces by default so phones on the LAN can reach the UI.
    # Override with KICKR_HOST=127.0.0.1 if you want localhost-only.
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
