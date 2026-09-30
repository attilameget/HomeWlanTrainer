"""Application entry – FastAPI lifespan and CLI."""

from __future__ import annotations

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
from kickr_pi.config import Settings, load_settings
from kickr_pi.engine.engine import WorkoutEngine
from kickr_pi.garmin.source import GarminSource
from kickr_pi.platform_sleep import SleepGuard
from kickr_pi.storage.repository import Repository
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


def build_trainer(settings: Settings) -> Any:
    if settings.trainer_mode == "simulated":
        return SimulatedTrainer()
    return DirConTrainer()


async def connect_trainer(trainer: Any, settings: Settings) -> bool:
    """Discover and/or connect to a real DirCon trainer. Returns True on success."""
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
        # Persist so next start can skip a full browse if desired
        # (still rediscovers when host is cleared in settings)

    try:
        await trainer.connect(host, port)
        await trainer.request_control()
        logger.info("trainer connected at %s:%s", host, port)
        return True
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
        for key, value in saved.items():
            if hasattr(settings, key) and value is not None:
                setattr(settings, key, value)
        # Force real trainer unless explicitly overridden via env for tests
        if settings.trainer_mode == "simulated" and not saved.get(
            "allow_simulated", False
        ):
            # Drop stale "simulated" preference from earlier Phase A runs
            settings.trainer_mode = "dircon"
            saved.pop("trainer_mode", None)
            repo.save_settings(
                {
                    **{k: v for k, v in saved.items() if k != "trainer_mode"},
                    "trainer_mode": "dircon",
                    "ftp_w": settings.ftp_w,
                    "trainer_host": settings.trainer_host,
                    "trainer_port": settings.trainer_port,
                }
            )

        trainer = build_trainer(settings)
        if settings.auto_connect:
            await connect_trainer(trainer, settings)

        engine = WorkoutEngine(
            trainer,
            ftp_w=settings.ftp_w,
            keepalive_s=settings.keepalive_s,
            erg_zero_cadence_drop=settings.erg_zero_cadence_drop,
            free_ride_resistance_tenths=settings.free_ride_resistance_tenths,
        )
        sleep_guard = SleepGuard()
        engine.add_listener(sleep_guard.on_live)
        source = GarminSource(settings.garth_dir, ftp_w=settings.ftp_w)
        restored = await source.try_restore_session()
        app.state = AppState(
            settings=settings,
            trainer=trainer,
            engine=engine,
            workout_source=source,
            repo=repo,
            sleep_guard=sleep_guard,
        )
        logger.info(
            "kickr-pi ready on %s:%s (trainer=%s connected=%s host=%s garmin=%s)",
            settings.host,
            settings.port,
            settings.trainer_mode,
            trainer.connected,
            settings.trainer_host,
            "ok" if restored else "logged-out",
        )
        _log_listen_urls(settings.host, settings.port)
        yield
        await sleep_guard.release()
        await engine.shutdown()
        await trainer.disconnect()

    app = FastAPI(title="KICKR Pi Trainer", lifespan=lifespan)
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
