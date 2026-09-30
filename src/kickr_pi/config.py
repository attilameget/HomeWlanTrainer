from __future__ import annotations

from pathlib import Path

from platformdirs import user_config_dir, user_data_dir
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


APP_NAME = "kickr-pi"
APP_AUTHOR = "kickr-pi"


class Settings(BaseSettings):
    """Runtime settings. Persisted fields are also mirrored in SQLite later."""

    model_config = SettingsConfigDict(
        env_prefix="KICKR_",
        env_file=".env",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8080
    ftp_w: int = 200
    trainer_mode: str = "dircon"  # dircon (real KICKR) | simulated (tests only)
    trainer_host: str | None = None
    trainer_port: int = 36866
    trainer_serial: str | None = None
    keepalive_s: float = 10.0
    ramp_step_s: float = 1.0
    erg_zero_cadence_drop: float = 0.5
    free_ride_resistance_tenths: int = 20
    discover_timeout_s: float = 8.0
    auto_connect: bool = True

    # Power zones as midpoints (% FTP) for zones 1–7 if Garmin zones unavailable
    power_zones: list[float] = Field(
        default_factory=lambda: [0.45, 0.55, 0.65, 0.75, 0.87, 1.05, 1.25]
    )

    @property
    def data_dir(self) -> Path:
        path = Path(user_data_dir(APP_NAME, APP_AUTHOR))
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def config_dir(self) -> Path:
        path = Path(user_config_dir(APP_NAME, APP_AUTHOR))
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def garth_dir(self) -> Path:
        # Legacy name from SPEC; now holds garminconnect token files
        path = self.config_dir / "garmin"
        path.mkdir(parents=True, exist_ok=True)
        try:
            path.chmod(0o700)
        except OSError:
            pass
        return path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "kickr_pi.db"

    @property
    def samples_dir(self) -> Path:
        path = self.data_dir / "samples"
        path.mkdir(parents=True, exist_ok=True)
        return path


def load_settings() -> Settings:
    return Settings()
