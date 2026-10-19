"""GSI intake, the live state and its event stream, setup, recordings, replay and the demo."""

from __future__ import annotations

import asyncio
import hmac
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from d2bg import paths
from d2bg.api.services import Services, services
from d2bg.gsi import installer, recorder
from d2bg.gsi.demo import demo_frames

router = APIRouter()
Svc = Annotated[Services, Depends(services)]
LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}


@router.post("/gsi", include_in_schema=False)
async def gsi(request: Request, svc: Svc) -> dict[str, bool]:
    """Dota 2 posts here. Only from this machine, and only with this install's token."""
    if request.client is None or request.client.host not in LOOPBACK:
        raise HTTPException(403, "GSI is accepted from this computer only")
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "body is not JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "body is not an object")
    token = (payload.get("auth") or {}).get("token") if isinstance(payload.get("auth"), dict) else None
    if not isinstance(token, str) or not hmac.compare_digest(token, svc.ctx.settings.get().gsi_token):
        raise HTTPException(403, "bad GSI token")
    if svc.player is not None and svc.player.running:
        return {"ok": True}  # a replay owns the live view; ignore the game until it stops
    svc.engine.ingest(payload, source="game")
    return {"ok": True}


@router.get("/api/live")
def live(svc: Svc) -> dict[str, Any]:
    return svc.engine.snapshot()


@router.get("/api/live/stream")
async def live_stream(request: Request, svc: Svc, once: bool = False) -> StreamingResponse:
    """Server-Sent Events: a snapshot on every change, and at least every 2 s. ``once`` sends one and ends."""

    async def events() -> AsyncIterator[str]:
        last = -1
        idle = 0
        while not await request.is_disconnected():
            if svc.engine.version != last or idle >= 8:
                last = svc.engine.version
                idle = 0
                yield f"data: {json.dumps(svc.engine.snapshot(), separators=(',', ':'))}\n\n"
                if once:
                    return
            else:
                idle += 1
            await asyncio.sleep(0.25)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class Mark(BaseModel):
    what: Literal["roshan", "aegis", "tormentor", "clear_roshan"]
    clock: float | None = None


@router.post("/api/live/mark")
def mark(svc: Svc, body: Mark) -> dict[str, Any]:
    svc.engine.mark(body.what, body.clock)
    return svc.engine.snapshot()


@router.post("/api/live/reset")
def reset(svc: Svc) -> dict[str, bool]:
    svc.stop_player()
    svc.engine.reset()
    return {"ok": True}


# ── setup ──────────────────────────────────────────────────────────


def _dota(path: str | None) -> Path | None:
    if path:
        return Path(path)
    return installer.find_dota()


@router.get("/api/gsi/status")
def gsi_status(svc: Svc, path: str | None = None) -> dict[str, Any]:
    st = installer.status(_dota(path), svc.port, svc.ctx.settings.get().gsi_token)
    return {
        **st,
        "port": svc.port,
        "connection": svc.engine.connection(),
        "launch_option_hint": "-gamestateintegration",
    }


class InstallBody(BaseModel):
    path: str | None = None


@router.post("/api/gsi/install")
def gsi_install(svc: Svc, body: InstallBody) -> dict[str, Any]:
    dota = _dota(body.path)
    if dota is None:
        raise HTTPException(
            404, "Dota 2 not found. Enter the Dota 2 install folder (the one that contains game/dota)."
        )
    try:
        target = installer.install(dota, svc.port, svc.ctx.settings.get().gsi_token)
    except (FileNotFoundError, PermissionError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"installed": True, "path": str(target)}


@router.post("/api/gsi/remove")
def gsi_remove(svc: Svc, body: InstallBody) -> dict[str, Any]:
    dota = _dota(body.path)
    if dota is None:
        raise HTTPException(404, "Dota 2 not found")
    return {"removed": installer.remove(dota)}


# ── recordings, replay, demo ───────────────────────────────────────


@router.get("/api/recordings")
def recordings() -> list[dict[str, Any]]:
    return recorder.list_recordings(paths.recordings_dir())


class ReplayBody(BaseModel):
    name: str
    speed: float = Field(default=4.0, gt=0, le=64)


@router.post("/api/replay")
def replay(svc: Svc, body: ReplayBody) -> dict[str, Any]:
    directory = paths.recordings_dir().resolve()
    target = (directory / body.name).resolve()
    if target.parent != directory or not target.is_file():
        raise HTTPException(404, "No such recording")
    frames = list(recorder.read(target))
    svc.start_player(frames, "replay", body.speed)
    return {"frames": len(frames), "speed": body.speed}


class DemoBody(BaseModel):
    hero: str = "juggernaut"
    speed: float = Field(default=8.0, gt=0, le=64)
    minutes: int = Field(default=36, ge=1, le=90)


@router.post("/api/demo")
def demo(svc: Svc, body: DemoBody) -> dict[str, Any]:
    if svc.ctx.data.heroes.get(body.hero) is None:
        raise HTTPException(404, f"No hero {body.hero!r}")
    frames = demo_frames(svc.ctx, body.hero, minutes=body.minutes)
    svc.start_player(frames, "demo", body.speed)
    return {"frames": len(frames), "speed": body.speed}


@router.post("/api/replay/stop")
def replay_stop(svc: Svc) -> dict[str, bool]:
    svc.stop_player()
    return {"ok": True}


@router.get("/api/replay")
def replay_status(svc: Svc) -> dict[str, Any]:
    p = svc.player
    return {
        "running": bool(p and p.running),
        "position": p.position if p else 0,
        "frames": len(p.frames) if p else 0,
        "source": svc.engine.source,
    }
