"""FastAPI routes and WebSocket live feed."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from kickr_pi.engine.models import demo_workout
from kickr_pi.garmin.parser import parse_garmin_workout

logger = logging.getLogger(__name__)
router = APIRouter()


class StartSessionBody(BaseModel):
    workout_id: str = "demo-1"


class CommandBody(BaseModel):
    command: str


class SettingsUpdate(BaseModel):
    ftp_w: int | None = None
    trainer_mode: str | None = None
    trainer_host: str | None = None
    trainer_port: int | None = None


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
    return {
        "engine": asdict(live),
        "trainer_mode": app.settings.trainer_mode,
        "garmin_authenticated": app.workout_source.authenticated,
    }


@router.get("/api/workouts/today")
async def workouts_today(request: Request) -> list[dict[str, Any]]:
    app = _app(request)
    items = await app.workout_source.todays_workouts()
    return [asdict(i) for i in items]


@router.get("/api/workouts")
async def workouts_library(request: Request) -> list[dict[str, Any]]:
    app = _app(request)
    items = await app.workout_source.library()
    return [asdict(i) for i in items]


@router.get("/api/workouts/{workout_id}")
async def workout_detail(workout_id: str, request: Request) -> dict[str, Any]:
    app = _app(request)
    if workout_id == "demo-1":
        w = demo_workout(app.settings.ftp_w)
    else:
        raw = await app.workout_source.get_workout(workout_id)
        w = parse_garmin_workout(raw, ftp_w=app.settings.ftp_w)
    return {
        "id": w.id,
        "name": w.name,
        "sport": w.sport,
        "total_s": w.total_s,
        "stages": [asdict(s) for s in w.stages],
    }


@router.post("/api/session")
async def start_session(body: StartSessionBody, request: Request) -> dict[str, Any]:
    app = _app(request)
    detail = await workout_detail(body.workout_id, request)
    workout = parse_garmin_workout(detail, ftp_w=app.settings.ftp_w)
    try:
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
        else:
            raise HTTPException(status_code=400, detail=f"unknown command: {cmd}")
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "live": asdict(app.engine.live)}


@router.get("/api/settings")
async def get_settings(request: Request) -> dict[str, Any]:
    s = _app(request).settings
    return {
        "ftp_w": s.ftp_w,
        "trainer_mode": s.trainer_mode,
        "trainer_host": s.trainer_host,
        "trainer_port": s.trainer_port,
        "port": s.port,
    }


@router.put("/api/settings")
async def put_settings(body: SettingsUpdate, request: Request) -> dict[str, Any]:
    app = _app(request)
    data = body.model_dump(exclude_none=True)
    for key, value in data.items():
        setattr(app.settings, key, value)
    app.repo.save_settings(
        {
            "ftp_w": app.settings.ftp_w,
            "trainer_mode": app.settings.trainer_mode,
            "trainer_host": app.settings.trainer_host,
            "trainer_port": app.settings.trainer_port,
        }
    )
    return await get_settings(request)


@router.post("/api/garmin/login")
async def garmin_login(body: GarminLoginBody, request: Request) -> dict[str, Any]:
    app = _app(request)
    try:
        await app.workout_source.login(body.email, body.password, body.mfa)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "authenticated": app.workout_source.authenticated}


@router.post("/api/trainer/discover")
async def trainer_discover(request: Request) -> dict[str, Any]:
    app = _app(request)
    trainers = await app.trainer.discover(app.settings.discover_timeout_s)
    return {
        "trainers": [
            {
                "name": t.name,
                "host": t.host,
                "port": t.port,
                "serial": t.serial,
            }
            for t in trainers
        ]
    }


@router.post("/api/trainer/connect")
async def trainer_connect(request: Request) -> dict[str, Any]:
    app = _app(request)
    host = app.settings.trainer_host
    port = app.settings.trainer_port
    if not host:
        found = await app.trainer.discover(app.settings.discover_timeout_s)
        if not found:
            raise HTTPException(status_code=404, detail="no trainer found")
        host, port = found[0].host, found[0].port
        app.settings.trainer_host = host
        app.settings.trainer_port = port
    try:
        await app.trainer.connect(host, port)
        await app.trainer.request_control()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "host": host, "port": port}


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
