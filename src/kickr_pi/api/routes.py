"""FastAPI routes and WebSocket live feed."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Any

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from kickr_pi.config import persisted_settings
from kickr_pi.engine.models import manual_workout
from kickr_pi.garmin.parser import parse_garmin_workout
from kickr_pi.garmin.source import GarminAuthError
from kickr_pi.hr.monitor import HeartRateDevice, HeartRateLink
from kickr_pi.plan.garmin_sync import sync_plan_to_garmin
from kickr_pi.plan.history import merge_history
from kickr_pi.plan.models import PlanGoals
from kickr_pi.plan.service import build_plan, maybe_refresh_plan_after_ride
from kickr_pi.plan.store import clear_plan, get_plan_day, load_plan, save_plan
from kickr_pi.rides.store import delete_ride_files, download_filename, save_ride
from kickr_pi.trainer.simulated import SimulatedTrainer

logger = logging.getLogger(__name__)
router = APIRouter()


class StartSessionBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    workout_id: str = Field(alias="workoutId")
    target_w: int | None = Field(default=None, alias="targetW")


class CommandBody(BaseModel):
    command: str


class SettingsUpdate(BaseModel):
    ftp_w: int | None = None
    trainer_mode: str | None = None
    trainer_host: str | None = None
    trainer_port: int | None = None
    allow_simulated: bool | None = None
    auto_connect: bool | None = None
    hr_device_id: str | None = None
    hr_device_name: str | None = None
    hr_auto_connect: bool | None = None
    ollama_enabled: bool | None = None
    ollama_base_url: str | None = None
    ollama_model: str | None = None


class TrainerModeBody(BaseModel):
    mode: str  # dircon | simulated


class EmulatorTargetBody(BaseModel):
    watts: int = Field(ge=0, le=2000)


class EmulatorPresetBody(BaseModel):
    name: str


class EmulatorCadenceBody(BaseModel):
    rpm: float = Field(ge=0, le=200)


class GarminLoginBody(BaseModel):
    email: str
    password: str
    mfa: str | None = None


class HeartRateConnectBody(BaseModel):
    device_id: str | None = None
    name: str | None = None


class PlanGenerateBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    weeks: int = 4
    hours_per_week: float = Field(default=6.0, alias="hoursPerWeek")
    bike_days_per_week: int = Field(default=3, alias="bikeDaysPerWeek")
    run_days_per_week: int = Field(default=2, alias="runDaysPerWeek")
    goal: str = "general"
    notes: str = ""
    start_date: str | None = Field(default=None, alias="startDate")


def _app(request: Request) -> Any:
    return request.app.state


def _heart_rate(app: Any) -> HeartRateLink | None:
    hr = getattr(app, "heart_rate", None)
    if isinstance(hr, HeartRateLink):
        return hr
    return None


def _require_hr(app: Any) -> HeartRateLink:
    hr = _heart_rate(app)
    if hr is None or not hr.supported:
        raise HTTPException(
            status_code=404,
            detail="heart rate is only available on macOS",
        )
    return hr


@router.get("/api/status")
async def status(request: Request) -> dict[str, Any]:
    app = _app(request)
    live = app.engine.live
    endpoint = getattr(app.trainer, "endpoint", None)
    src = app.workout_source
    hr = _heart_rate(app)
    return {
        "engine": asdict(live),
        "trainer_mode": app.settings.trainer_mode,
        "trainer_host": app.settings.trainer_host,
        "trainer_port": app.settings.trainer_port,
        "trainer_endpoint": (
            {"host": endpoint[0], "port": endpoint[1]} if endpoint else None
        ),
        "allow_simulated": bool(getattr(app.settings, "allow_simulated", False)),
        "emulator": isinstance(app.trainer, SimulatedTrainer),
        "garmin_authenticated": bool(getattr(src, "authenticated", False)),
        "garmin_display_name": getattr(src, "display_name", None),
        "hr_supported": bool(hr and hr.supported),
        "hr_connected": bool(hr and hr.connected),
    }


@router.get("/api/workouts/today")
async def workouts_today(request: Request) -> list[dict[str, Any]]:
    """Today's Garmin calendar bike session(s) only — plan workouts appear in Library."""
    app = _app(request)
    src = app.workout_source
    if not getattr(src, "authenticated", False):
        return []
    try:
        items = await src.todays_workouts()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [asdict(i) for i in items]


@router.get("/api/workouts")
async def workouts_library(request: Request) -> list[dict[str, Any]]:
    """Library: today's Garmin sessions first, then Garmin library, then plan bike days."""
    app = _app(request)
    src = app.workout_source
    today_items: list[Any] = []
    library_items: list[Any] = []
    if getattr(src, "authenticated", False):
        try:
            # Calendar + library are independent Garmin calls — overlap them
            today_items, library_items = await asyncio.gather(
                src.todays_workouts(),
                src.library(),
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    today_ids = {i.id for i in today_items}
    out: list[dict[str, Any]] = []
    for item in today_items:
        row = asdict(item)
        row["is_today"] = True
        out.append(row)
    for item in library_items:
        if item.id in today_ids:
            continue
        row = asdict(item)
        row["is_today"] = False
        out.append(row)

    # Playable plan bike sessions appear in Library only (not on Today card)
    plan = load_plan(app.repo)
    if plan is not None:
        from datetime import date

        today = date.today().isoformat()
        for day in plan.days:
            if not (day.playable and day.sport == "cycling"):
                continue
            out.append(
                {
                    "id": day.id,
                    "name": f"{day.date} · {day.title}",
                    "sport": "cycling",
                    "duration_s": day.duration_s,
                    "scheduled_date": day.date,
                    "source": "plan",
                    "is_today": day.date == today,
                }
            )
    return out


@router.get("/api/workouts/{workout_id}")
async def workout_detail(workout_id: str, request: Request) -> dict[str, Any]:
    app = _app(request)
    if workout_id == "manual":
        target = int(request.query_params.get("target_w") or 100)
        w = manual_workout(target)
    elif workout_id in ("demo", "demo-1"):
        from kickr_pi.engine.models import demo_workout

        w = demo_workout(app.settings.ftp_w)
    elif workout_id.startswith("plan-day-"):
        day = get_plan_day(app.repo, workout_id)
        if day is None:
            raise HTTPException(status_code=404, detail="plan day not found")
        if day.get("sport") != "cycling" or not day.get("playable"):
            raise HTTPException(
                status_code=400,
                detail="only bike plan days can be loaded on the trainer",
            )
        w = parse_garmin_workout(day, ftp_w=app.settings.ftp_w)
        return {
            "id": w.id,
            "name": w.name,
            "sport": w.sport,
            "total_s": w.total_s,
            "manual": False,
            "source": "plan",
            "rationale": day.get("rationale"),
            "stages": [asdict(s) for s in w.stages],
        }
    else:
        try:
            raw = await app.workout_source.get_workout(workout_id)
        except GarminAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        w = parse_garmin_workout(raw, ftp_w=app.settings.ftp_w)
    return {
        "id": w.id,
        "name": w.name,
        "sport": w.sport,
        "total_s": w.total_s,
        "manual": w.id == "manual",
        "stages": [asdict(s) for s in w.stages],
    }


@router.post("/api/session")
async def start_session(body: StartSessionBody, request: Request) -> dict[str, Any]:
    app = _app(request)
    try:
        await app.engine.prepare_new_session()
        if body.workout_id == "manual":
            target = body.target_w if body.target_w is not None else 100
            app.engine.load_manual(target)
        else:
            detail = await workout_detail(body.workout_id, request)
            workout = parse_garmin_workout(detail, ftp_w=app.settings.ftp_w)
            app.engine.load(workout)
        await app.engine.start()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "live": asdict(app.engine.live)}


@router.post("/api/session/command")
async def session_command(body: CommandBody, request: Request) -> dict[str, Any]:
    app = _app(request)
    cmd = body.command.strip().lower()
    saved_ride: dict[str, Any] | None = None
    try:
        if cmd == "pause":
            await app.engine.pause()
        elif cmd == "resume":
            await app.engine.resume()
        elif cmd == "stop":
            # Real KICKR and Emulator use the same path — mode does not gate saving.
            recording = app.engine.take_ride_recording()
            if recording is not None:
                try:
                    saved_ride = save_ride(
                        recording,
                        repo=app.repo,
                        rides_dir=app.settings.rides_dir,
                    )
                    if saved_ride is not None:
                        logger.info(
                            "saved ride id=%s duration=%.1fs emulator=%s",
                            saved_ride["id"],
                            recording.duration_s,
                            isinstance(app.trainer, SimulatedTrainer),
                        )
                        # Long rides (≥30 min) refresh the next week of training
                        if recording.duration_s >= 30 * 60:
                            asyncio.create_task(
                                maybe_refresh_plan_after_ride(
                                    app, duration_s=recording.duration_s
                                )
                            )
                            saved_ride["plan_refresh"] = "started"
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "ride save failed (emulator=%s): %s",
                        isinstance(app.trainer, SimulatedTrainer),
                        exc,
                    )
            await app.engine.stop()
        elif cmd == "skip":
            await app.engine.skip()
        elif cmd == "previous":
            await app.engine.previous()
        elif cmd in ("intensity:+5", "intensity+5", "+5"):
            await app.engine.adjust_intensity(5)
        elif cmd in ("intensity:-5", "intensity-5", "-5"):
            await app.engine.adjust_intensity(-5)
        elif cmd.startswith("target:"):
            raw = cmd.split(":", 1)[1].strip()
            if raw.startswith("+") or raw.startswith("-"):
                await app.engine.adjust_target_watts(int(raw))
            else:
                await app.engine.set_target_watts(int(raw))
        else:
            raise HTTPException(status_code=400, detail=f"unknown command: {cmd}")
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"bad command: {cmd}") from exc
    payload: dict[str, Any] = {"ok": True, "live": asdict(app.engine.live)}
    if saved_ride is not None:
        payload["saved_ride"] = saved_ride
    return payload


@router.get("/api/rides")
async def list_rides(request: Request) -> list[dict[str, Any]]:
    return _app(request).repo.list_rides()


@router.get("/api/rides/{ride_id}/fit")
async def download_ride_fit(ride_id: str, request: Request) -> FileResponse:
    app = _app(request)
    ride = app.repo.get_ride(ride_id)
    if ride is None:
        raise HTTPException(status_code=404, detail="ride not found")
    path = Path(ride["fit_path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="FIT file missing")
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=download_filename(ride),
    )


@router.delete("/api/rides/{ride_id}")
async def delete_ride(ride_id: str, request: Request) -> dict[str, Any]:
    app = _app(request)
    ride = app.repo.delete_ride(ride_id)
    if ride is None:
        raise HTTPException(status_code=404, detail="ride not found")
    delete_ride_files(ride)
    return {"ok": True, "id": ride_id}


@router.get("/api/plan")
async def get_plan(request: Request) -> dict[str, Any]:
    plan = load_plan(_app(request).repo)
    if plan is None:
        return {"plan": None}
    return {"plan": plan.to_dict()}


@router.post("/api/plan/generate")
async def plan_generate(body: PlanGenerateBody, request: Request) -> dict[str, Any]:
    app = _app(request)
    src = app.workout_source
    garmin_raw: list[dict[str, Any]] = []
    if getattr(src, "authenticated", False) and hasattr(src, "recent_activities"):
        try:
            garmin_raw = await src.recent_activities(lookback_days=28)
        except Exception as exc:  # noqa: BLE001
            logger.warning("plan history fetch failed: %s", exc)
    activities = merge_history(garmin_raw, app.repo.list_rides())
    goals = PlanGoals(
        weeks=body.weeks,
        hours_per_week=body.hours_per_week,
        bike_days_per_week=body.bike_days_per_week,
        run_days_per_week=body.run_days_per_week,
        goal=body.goal,
        notes=body.notes,
        start_date=body.start_date,
    )
    plan = await build_plan(
        goals=goals,
        ftp_w=app.settings.ftp_w,
        activities=activities,
        ollama_enabled=bool(getattr(app.settings, "ollama_enabled", False)),
        ollama_base_url=str(
            getattr(app.settings, "ollama_base_url", "http://127.0.0.1:11434")
        ),
        ollama_model=str(getattr(app.settings, "ollama_model", "llama3.1:8b")),
    )
    save_plan(app.repo, plan)
    return {"ok": True, "plan": plan.to_dict()}


@router.delete("/api/plan")
async def plan_delete(request: Request) -> dict[str, Any]:
    clear_plan(_app(request).repo)
    return {"ok": True}


@router.post("/api/plan/sync-garmin")
async def plan_sync_garmin(request: Request) -> dict[str, Any]:
    app = _app(request)
    src = app.workout_source
    if not getattr(src, "authenticated", False):
        raise HTTPException(status_code=401, detail="Garmin login required")
    plan = load_plan(app.repo)
    if plan is None:
        raise HTTPException(status_code=404, detail="no active plan")
    try:
        client = src.require_client()
        plan = await sync_plan_to_garmin(client, plan)
    except GarminAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    save_plan(app.repo, plan)
    synced = sum(1 for d in plan.days if d.scheduled)
    return {
        "ok": True,
        "synced_days": synced,
        "plan": plan.to_dict(),
    }


@router.get("/api/settings")
async def get_settings(request: Request) -> dict[str, Any]:
    s = _app(request).settings
    return {
        "ftp_w": s.ftp_w,
        "trainer_mode": s.trainer_mode,
        "trainer_host": s.trainer_host,
        "trainer_port": s.trainer_port,
        "allow_simulated": bool(getattr(s, "allow_simulated", False)),
        "auto_connect": bool(getattr(s, "auto_connect", True)),
        "hr_device_id": getattr(s, "hr_device_id", None),
        "hr_device_name": getattr(s, "hr_device_name", None),
        "hr_auto_connect": bool(getattr(s, "hr_auto_connect", True)),
        "ollama_enabled": bool(getattr(s, "ollama_enabled", False)),
        "ollama_base_url": getattr(s, "ollama_base_url", "http://127.0.0.1:11434"),
        "ollama_model": getattr(s, "ollama_model", "llama3.1:8b"),
        "port": s.port,
    }


def _persist_trainer_settings(app: Any) -> None:
    app.repo.save_settings(persisted_settings(app.settings))


@router.put("/api/settings")
async def put_settings(body: SettingsUpdate, request: Request) -> dict[str, Any]:
    app = _app(request)
    data = body.model_dump(exclude_none=True)
    prev_auto = bool(getattr(app.settings, "auto_connect", True))
    prev_hr_auto = bool(getattr(app.settings, "hr_auto_connect", True))
    for key, value in data.items():
        setattr(app.settings, key, value)
    if app.settings.trainer_mode == "simulated":
        app.settings.allow_simulated = True
    _persist_trainer_settings(app)
    if "hr_auto_connect" in data:
        hr_ac = getattr(app, "hr_autoconnect", None)
        if app.settings.hr_auto_connect:
            if hr_ac is not None:
                hr_ac.resume()
                hr = _heart_rate(app)
                if (
                    hr is not None
                    and hr.supported
                    and not hr.connected
                    and app.settings.hr_device_id
                ):
                    await hr_ac.try_connect_now()
        elif hr_ac is not None and prev_hr_auto and not app.settings.hr_auto_connect:
            hr_ac.pause()
    # Turning autoconnect on resumes background attempts and tries once
    if "auto_connect" in data:
        ac = getattr(app, "autoconnect", None)
        if app.settings.auto_connect:
            if ac is not None:
                ac.resume()
                if (
                    app.settings.trainer_mode == "dircon"
                    and not app.trainer.connected
                ):
                    await ac.try_connect_now()
        elif ac is not None and prev_auto and not app.settings.auto_connect:
            ac.pause()
    return await get_settings(request)


@router.post("/api/garmin/login")
async def garmin_login(body: GarminLoginBody, request: Request) -> dict[str, Any]:
    app = _app(request)
    src = app.workout_source
    if not hasattr(src, "login"):
        raise HTTPException(status_code=501, detail="Garmin source unavailable")
    try:
        result = await src.login(body.email, body.password, body.mfa)
    except GarminAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": bool(result.get("authenticated")),
        "authenticated": bool(result.get("authenticated")),
        "needs_mfa": bool(result.get("needs_mfa")),
        "display_name": result.get("display_name"),
    }


@router.post("/api/garmin/logout")
async def garmin_logout(request: Request) -> dict[str, Any]:
    app = _app(request)
    src = app.workout_source
    if hasattr(src, "logout"):
        await src.logout()
    return {"ok": True, "authenticated": False}


@router.post("/api/trainer/discover")
async def trainer_discover(request: Request) -> dict[str, Any]:
    app = _app(request)
    trainers = await app.trainer.discover(app.settings.discover_timeout_s)
    payload = [
        {
            "name": t.name,
            "host": t.host,
            "port": t.port,
            "serial": t.serial,
        }
        for t in trainers
    ]
    if trainers and not app.settings.trainer_host:
        app.settings.trainer_host = trainers[0].host
        app.settings.trainer_port = trainers[0].port
        app.settings.trainer_serial = trainers[0].serial
    return {"trainers": payload, "count": len(payload)}


class TrainerConnectBody(BaseModel):
    host: str | None = None
    port: int | None = None


@router.post("/api/trainer/connect")
async def trainer_connect(
    request: Request, body: TrainerConnectBody | None = None
) -> dict[str, Any]:
    app = _app(request)
    body = body or TrainerConnectBody()
    host = body.host or app.settings.trainer_host
    port = body.port or app.settings.trainer_port
    if not host:
        found = await app.trainer.discover(app.settings.discover_timeout_s)
        if not found:
            raise HTTPException(
                status_code=404,
                detail="no trainer found on LAN (mDNS _wahoo-fitness-tnp._tcp)",
            )
        host, port = found[0].host, found[0].port
        app.settings.trainer_serial = found[0].serial
    app.settings.trainer_host = host
    app.settings.trainer_port = port

    endpoint = getattr(app.trainer, "endpoint", None)
    if app.trainer.connected and endpoint == (host, port):
        return {
            "ok": True,
            "host": host,
            "port": port,
            "connected": True,
            "already_connected": True,
        }

    try:
        await app.trainer.connect(host, port)
        await app.trainer.request_control()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=(
                f"{exc}. Direct Connect is 1:1 — close Zwift/Wahoo apps, "
                "wait a few seconds, then try again."
            ),
        ) from exc
    _persist_trainer_settings(app)
    ac = getattr(app, "autoconnect", None)
    if ac is not None:
        ac.resume()
    try:
        await app.engine.set_trainer(app.trainer)
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "host": host,
        "port": port,
        "connected": True,
        "already_connected": False,
    }


@router.post("/api/trainer/disconnect")
async def trainer_disconnect(request: Request) -> dict[str, Any]:
    app = _app(request)
    live = app.engine.live
    if live.engine_state in ("running", "paused", "reconnecting"):
        raise HTTPException(
            status_code=409,
            detail="stop the workout before disconnecting the trainer",
        )
    was_connected = bool(app.trainer.connected)
    endpoint = getattr(app.trainer, "endpoint", None)
    await app.trainer.disconnect()
    ac = getattr(app, "autoconnect", None)
    if ac is not None:
        # Keep Direct Connect free for other apps until Connect or Autoconnect on
        ac.pause()
    return {
        "ok": True,
        "was_connected": was_connected,
        "disconnected_from": (
            {"host": endpoint[0], "port": endpoint[1]} if endpoint else None
        ),
        "connected": False,
    }


def _hr_device_payload(devices: list[HeartRateDevice]) -> list[dict[str, str]]:
    return [{"device_id": d.device_id, "name": d.name} for d in devices]


@router.post("/api/hr/discover")
async def hr_discover(request: Request) -> dict[str, Any]:
    app = _app(request)
    hr = _require_hr(app)
    try:
        devices = await hr.discover(app.settings.discover_timeout_s)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if devices and not getattr(app.settings, "hr_device_id", None):
        app.settings.hr_device_id = devices[0].device_id
        app.settings.hr_device_name = devices[0].name
    payload = _hr_device_payload(devices)
    return {"devices": payload, "count": len(payload)}


@router.post("/api/hr/connect")
async def hr_connect(
    request: Request, body: HeartRateConnectBody | None = None
) -> dict[str, Any]:
    app = _app(request)
    hr = _require_hr(app)
    body = body or HeartRateConnectBody()
    device_id = (
        body.device_id or getattr(app.settings, "hr_device_id", None) or ""
    ).strip()
    name = body.name or getattr(app.settings, "hr_device_name", None)
    if not device_id:
        try:
            found = await hr.discover(app.settings.discover_timeout_s)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if not found:
            raise HTTPException(
                status_code=404,
                detail=(
                    "no heart rate monitor found — wear the strap, wake it, "
                    "and allow Bluetooth for steadyGrind"
                ),
            )
        device_id = found[0].device_id
        name = found[0].name

    if hr.connected and hr.device_id == device_id:
        ac = getattr(app, "hr_autoconnect", None)
        if ac is not None:
            ac.resume()
        return {
            "ok": True,
            "device_id": device_id,
            "name": name or hr.device_name,
            "connected": True,
            "already_connected": True,
        }

    try:
        await hr.connect(device_id, name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=(
                f"{exc}. Allow Bluetooth for steadyGrind, wake the strap, "
                "and try again."
            ),
        ) from exc

    app.settings.hr_device_id = device_id
    app.settings.hr_device_name = hr.device_name or name
    _persist_trainer_settings(app)
    ac = getattr(app, "hr_autoconnect", None)
    if ac is not None:
        ac.resume()
    return {
        "ok": True,
        "device_id": device_id,
        "name": app.settings.hr_device_name,
        "connected": True,
        "already_connected": False,
    }


@router.post("/api/hr/disconnect")
async def hr_disconnect(request: Request) -> dict[str, Any]:
    """Drop the strap. Allowed during a ride — the workout keeps running."""
    app = _app(request)
    hr = _require_hr(app)
    was_connected = bool(hr.connected)
    device_id = hr.device_id or getattr(app.settings, "hr_device_id", None)
    name = hr.device_name or getattr(app.settings, "hr_device_name", None)
    await hr.disconnect()
    ac = getattr(app, "hr_autoconnect", None)
    if ac is not None:
        ac.pause()
    return {
        "ok": True,
        "was_connected": was_connected,
        "device_id": device_id,
        "name": name,
        "connected": False,
    }


def _require_emulator(app: Any) -> SimulatedTrainer:
    if not isinstance(app.trainer, SimulatedTrainer):
        raise HTTPException(
            status_code=404,
            detail="emulator not active — switch trainer mode to Emulator in Settings",
        )
    return app.trainer


@router.post("/api/trainer/mode")
async def trainer_mode(body: TrainerModeBody, request: Request) -> dict[str, Any]:
    """Hot-swap Real KICKR ↔ Emulator when the engine is idle.

    Completes even if the physical trainer is offline: Emulator always
    connects locally; DirCon attempts a timed connect and may return
    connected=false without failing the mode switch.
    """
    from kickr_pi.main import connect_trainer, create_trainer

    app = _app(request)
    mode = body.mode.strip().lower()
    if mode not in ("dircon", "simulated"):
        raise HTTPException(status_code=400, detail="mode must be dircon or simulated")

    live = app.engine.live
    if live.engine_state in ("running", "paused", "reconnecting", "loaded"):
        raise HTTPException(
            status_code=400,
            detail="stop the workout before switching trainer mode",
        )

    if mode == app.settings.trainer_mode and (
        (mode == "simulated" and isinstance(app.trainer, SimulatedTrainer))
        or (mode == "dircon" and not isinstance(app.trainer, SimulatedTrainer))
    ):
        connected = bool(app.trainer.connected)
        if mode == "simulated" and not connected:
            connected = await connect_trainer(app.trainer, app.settings)
        return {
            "ok": True,
            "trainer_mode": mode,
            "connected": connected,
            "emulator": isinstance(app.trainer, SimulatedTrainer),
            "unchanged": True,
        }

    old = app.trainer
    try:
        await asyncio.wait_for(old.disconnect(), timeout=3.0)
    except Exception:  # noqa: BLE001
        pass

    app.settings.trainer_mode = mode
    app.settings.allow_simulated = mode == "simulated"
    trainer = create_trainer(mode)
    # Always rebind first so the UI/engine use the new trainer even if connect fails.
    app.trainer = trainer
    await app.engine.set_trainer(trainer)
    try:
        connected = await asyncio.wait_for(
            connect_trainer(trainer, app.settings),
            timeout=max(12.0, float(app.settings.discover_timeout_s) + 8.0),
        )
    except asyncio.TimeoutError:
        connected = False
    app.repo.save_settings(persisted_settings(app.settings))
    if mode == "dircon" and connected:
        ac = getattr(app, "autoconnect", None)
        if ac is not None:
            ac.resume()
    return {
        "ok": True,
        "trainer_mode": mode,
        "connected": connected,
        "emulator": isinstance(trainer, SimulatedTrainer),
        "unchanged": False,
    }


@router.get("/api/emulator/status")
async def emulator_status(request: Request) -> dict[str, Any]:
    emu = _require_emulator(_app(request))
    return emu.status()


@router.post("/api/emulator/target")
async def emulator_target(body: EmulatorTargetBody, request: Request) -> dict[str, Any]:
    emu = _require_emulator(_app(request))
    await emu.emulator_set_target(body.watts)
    return {"ok": True, **emu.status()}


@router.post("/api/emulator/preset")
async def emulator_preset(body: EmulatorPresetBody, request: Request) -> dict[str, Any]:
    emu = _require_emulator(_app(request))
    try:
        await emu.run_preset(body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **emu.status()}


@router.post("/api/emulator/pause")
async def emulator_pause(request: Request) -> dict[str, Any]:
    emu = _require_emulator(_app(request))
    await emu.emulator_pause()
    return {"ok": True, **emu.status()}


@router.post("/api/emulator/resume")
async def emulator_resume(request: Request) -> dict[str, Any]:
    emu = _require_emulator(_app(request))
    await emu.emulator_resume()
    return {"ok": True, **emu.status()}


@router.post("/api/emulator/cadence")
async def emulator_cadence(body: EmulatorCadenceBody, request: Request) -> dict[str, Any]:
    """Desk control: set reported cadence (use 0 to simulate no pedaling)."""
    emu = _require_emulator(_app(request))
    await emu.emulator_set_cadence(body.rpm)
    return {"ok": True, **emu.status()}


@router.post("/api/emulator/follow")
async def emulator_follow(request: Request) -> dict[str, Any]:
    """Release desk hold so the workout engine drives ERG again."""
    emu = _require_emulator(_app(request))
    await emu.emulator_follow_engine()
    return {"ok": True, **emu.status()}


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    await websocket.accept()
    app = websocket.app.state
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=8)

    async def on_live(live: Any) -> None:
        payload = {
            "type": "tick",
            "data": asdict(live),
            "emulator": isinstance(app.trainer, SimulatedTrainer),
        }
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            queue.put_nowait(payload)

    app.engine.add_listener(on_live)
    await websocket.send_json({"type": "tick", "data": asdict(app.engine.live)})
    try:
        while True:
            # Also push idle ticks so UI stays fresh before a ride
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                msg = {"type": "tick", "data": asdict(app.engine.live)}
            await websocket.send_json(msg)
    except WebSocketDisconnect:
        logger.debug("websocket disconnected")
    finally:
        if on_live in app.engine._listeners:  # noqa: SLF001
            app.engine._listeners.remove(on_live)  # noqa: SLF001
