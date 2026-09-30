"""Application entry – FastAPI lifespan and CLI."""

from __future__ import annotations

import logging
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
from kickr_pi.garmin.parser import LocalDemoSource
from kickr_pi.storage.repository import Repository
from kickr_pi.trainer.dircon import DirConTrainer
from kickr_pi.trainer.simulated import SimulatedTrainer

logger = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parent / "web"


@dataclass
class AppState:
    settings: Settings
    trainer: Any
    engine: WorkoutEngine
    workout_source: Any
    repo: Repository


def build_trainer(settings: Settings) -> Any:
    if settings.trainer_mode == "dircon":
        return DirConTrainer()
    return SimulatedTrainer()


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

        trainer = build_trainer(settings)
        # Auto-connect simulated trainer for desk use
        if settings.trainer_mode == "simulated":
            await trainer.connect("127.0.0.1", 36866)
            await trainer.request_control()
        elif settings.trainer_host:
            try:
                await trainer.connect(settings.trainer_host, settings.trainer_port)
                await trainer.request_control()
            except Exception as exc:  # noqa: BLE001
                logger.warning("trainer connect failed: %s", exc)

        engine = WorkoutEngine(
            trainer,
            ftp_w=settings.ftp_w,
            keepalive_s=settings.keepalive_s,
            erg_zero_cadence_drop=settings.erg_zero_cadence_drop,
            free_ride_resistance_tenths=settings.free_ride_resistance_tenths,
        )
        source = LocalDemoSource(ftp_w=settings.ftp_w)
        app.state = AppState(
            settings=settings,
            trainer=trainer,
            engine=engine,
            workout_source=source,
            repo=repo,
        )
        logger.info(
            "kickr-pi ready on %s:%s (trainer=%s)",
            settings.host,
            settings.port,
            settings.trainer_mode,
        )
        yield
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
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
