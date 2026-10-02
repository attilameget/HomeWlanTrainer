"""FastAPI routes and WebSocket live feed."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field

from kickr_pi.engine.models import manual_workout
from kickr_pi.garmin.parser import parse_garmin_workout
from kickr_pi.garmin.source import GarminAuthError
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


class TrainerModeBody(BaseModel):
    mode: str  # dircon | simulated


class EmulatorTargetBody(BaseModel):
    watts: int = Field(ge=0, le=2000)


class EmulatorPresetBody(BaseModel):
    name: str


class GarminLoginBody(BaseModel):
    email: str
    password: str
    mfa: str | None = None


def _app(request: Request) -> Any:
    return request.app.state


@router.get("/api/status")
async def status(request: Request) -> dict[str, Any]:
    app = _app(request)
    live = app.engine.live
    endpoint = getattr(app.trainer, "endpoint", None)
    src = app.workout_source
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
    }


@router.get("/api/workouts/today")
async def workouts_today(request: Request) -> list[dict[str, Any]]:
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
    """Library with today's Garmin coach/calendar bike session(s) first."""
    app = _app(request)
    src = app.workout_source
    today_items: list[Any] = []
    library_items: list[Any] = []
    if getattr(src, "authenticated", False):
        try:
            today_items = await src.todays_workouts()
            library_items = await src.library()
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
    return out


@router.get("/api/workouts/{workout_id}")
async def workout_detail(workout_id: str, request: Request) -> dict[str, Any]:
    app = _app(request)
    if workout_id == "manual":
        target = int(request.query_params.get("target_w") or 100)
        w = manual_workout(target)
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
    try:
        if cmd == "pause":
            await app.engine.pause()
        elif cmd == "resume":
            await app.engine.resume()
        elif cmd == "stop":
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
    return {"ok": True, "live": asdict(app.engine.live)}


@router.get("/api/settings")
async def get_settings(request: Request) -> dict[str, Any]:
    s = _app(request).settings
    return {
        "ftp_w": s.ftp_w,
        "trainer_mode": s.trainer_mode,
        "trainer_host": s.trainer_host,
        "trainer_port": s.trainer_port,
        "allow_simulated": bool(getattr(s, "allow_simulated", False)),
        "port": s.port,
    }


@router.put("/api/settings")
async def put_settings(body: SettingsUpdate, request: Request) -> dict[str, Any]:
    app = _app(request)
    data = body.model_dump(exclude_none=True)
    for key, value in data.items():
        setattr(app.settings, key, value)
    if app.settings.trainer_mode == "simulated":
        app.settings.allow_simulated = True
    app.repo.save_settings(
        {
            "ftp_w": app.settings.ftp_w,
            "trainer_mode": app.settings.trainer_mode,
            "trainer_host": app.settings.trainer_host,
            "trainer_port": app.settings.trainer_port,
            "allow_simulated": bool(app.settings.allow_simulated),
        }
    )
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
    app.repo.save_settings(
        {
            "ftp_w": app.settings.ftp_w,
            "trainer_mode": app.settings.trainer_mode,
            "allow_simulated": bool(getattr(app.settings, "allow_simulated", False)),
            "trainer_host": host,
            "trainer_port": port,
        }
    )
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
    return {
        "ok": True,
        "was_connected": was_connected,
        "disconnected_from": (
            {"host": endpoint[0], "port": endpoint[1]} if endpoint else None
        ),
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
    connected = await connect_trainer(trainer, app.settings)
    app.repo.save_settings(
        {
            "ftp_w": app.settings.ftp_w,
            "trainer_mode": mode,
            "allow_simulated": mode == "simulated",
            "trainer_host": app.settings.trainer_host,
            "trainer_port": app.settings.trainer_port,
        }
    )
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
        payload = {"type": "tick", "data": asdict(live)}
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
