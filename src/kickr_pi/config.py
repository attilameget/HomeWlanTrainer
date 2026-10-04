from __future__ import annotations

from pathlib import Path
from typing import Any

from platformdirs import user_config_dir, user_data_dir
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from kickr_pi.plan.claude import DEFAULT_MODEL, normalize_model


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
    trainer_mode: str = "dircon"  # dircon (real KICKR) | simulated (emulator)
    allow_simulated: bool = False  # persist when Emulator mode is chosen in Settings
    trainer_host: str | None = None
    trainer_port: int = 36866
    trainer_serial: str | None = None
    keepalive_s: float = 10.0
    ramp_step_s: float = 1.0
    erg_zero_cadence_drop: float = 0.5
    free_ride_resistance_tenths: int = 20
    discover_timeout_s: float = 8.0
    auto_connect: bool = True
    # Bluetooth heart-rate strap (macOS only). CoreBluetooth id, not a MAC.
    hr_device_id: str | None = None
    hr_device_name: str | None = None
    hr_auto_connect: bool = True
    # Anthropic Claude for adaptive plan sketches (ERG stages still built on-host).
    # Empty key → rules planner only.
    anthropic_api_key: str = ""
    anthropic_model: str = DEFAULT_MODEL
    # Last Plan-screen generate form (restored whenever Plan is opened)
    plan_weeks: int = 4
    plan_hours_per_week: float = 6.0
    plan_bike_days_per_week: int = 3
    plan_run_days_per_week: int = 2
    plan_goal: str = "general"
    plan_notes: str = ""

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

    @property
    def rides_dir(self) -> Path:
        path = self.data_dir / "rides"
        path.mkdir(parents=True, exist_ok=True)
        return path


def load_settings() -> Settings:
    return Settings()


def persisted_settings(settings: Settings) -> dict[str, Any]:
    """Fields written to the SQLite settings blob."""
    return {
        "ftp_w": settings.ftp_w,
        "trainer_mode": settings.trainer_mode,
        "trainer_host": settings.trainer_host,
        "trainer_port": settings.trainer_port,
        "allow_simulated": bool(settings.allow_simulated),
        "auto_connect": bool(settings.auto_connect),
        "hr_device_id": settings.hr_device_id,
        "hr_device_name": settings.hr_device_name,
        "hr_auto_connect": bool(settings.hr_auto_connect),
        "anthropic_api_key": str(getattr(settings, "anthropic_api_key", "") or ""),
        "anthropic_model": normalize_model(
            getattr(settings, "anthropic_model", DEFAULT_MODEL)
        ),
        "plan_weeks": int(getattr(settings, "plan_weeks", 4) or 4),
        "plan_hours_per_week": float(getattr(settings, "plan_hours_per_week", 6) or 6),
        "plan_bike_days_per_week": int(
            getattr(settings, "plan_bike_days_per_week", 3) or 3
        ),
        "plan_run_days_per_week": int(
            getattr(settings, "plan_run_days_per_week", 2) or 0
        ),
        "plan_goal": str(getattr(settings, "plan_goal", "general") or "general"),
        "plan_notes": str(getattr(settings, "plan_notes", "") or ""),
    }
