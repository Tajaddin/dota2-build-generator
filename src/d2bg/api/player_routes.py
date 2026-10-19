"""His profile, other players, match reviews, settings and data refresh."""

from __future__ import annotations

import threading
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError

from d2bg import __version__, paths
from d2bg.api.services import RefreshJob, Services, services
from d2bg.matches.review import review
from d2bg.opendota import NotFoundError, OpenDotaError
from d2bg.pipeline.refresh import STEPS, Refresher
from d2bg.profile import service as profile_service

router = APIRouter(prefix="/api")
Svc = Annotated[Services, Depends(services)]


def _account(svc: Services, account_id: int | None) -> int:
    acc = account_id or svc.ctx.settings.get().account_id
    if not acc:
        raise HTTPException(400, "No account ID yet. Enter it in Settings, or play one game with GSI on.")
    return acc


def _upstream(exc: OpenDotaError) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(404, "OpenDota has no data for this yet")
    return HTTPException(502, f"OpenDota: {exc}")


@router.get("/profile")
def profile(svc: Svc, account_id: int | None = None, limit: int = 300) -> dict[str, Any]:
    try:
        return profile_service.profile(svc.ctx, _account(svc, account_id), min(max(limit, 20), 1000))
    except OpenDotaError as exc:
        raise _upstream(exc) from exc


@router.get("/profile/peers")
def peers(svc: Svc, account_id: int | None = None) -> list[dict[str, Any]]:
    try:
        return profile_service.peers(svc.ctx, _account(svc, account_id))
    except OpenDotaError as exc:
        raise _upstream(exc) from exc


@router.get("/players/search")
def player_search(svc: Svc, q: str) -> list[dict[str, Any]]:
    if len(q.strip()) < 2:
        return []
    try:
        return profile_service.search_players(svc.ctx, q)
    except OpenDotaError as exc:
        raise _upstream(exc) from exc


@router.get("/matches/{match_id}")
def match(svc: Svc, match_id: int, account_id: int | None = None) -> dict[str, Any]:
    try:
        doc = svc.ctx.client.get(f"matches/{match_id}", ttl=3600)
    except OpenDotaError as exc:
        raise _upstream(exc) from exc
    if not isinstance(doc, dict) or not doc.get("players"):
        raise HTTPException(404, "OpenDota has no data for this match yet")
    return review(svc.ctx, doc, account_id or svc.ctx.settings.get().account_id)


@router.post("/matches/{match_id}/parse")
def request_parse(svc: Svc, match_id: int) -> dict[str, Any]:
    try:
        job = svc.ctx.client.post(f"request/{match_id}")
    except OpenDotaError as exc:
        raise _upstream(exc) from exc
    return {"requested": True, "job": job}


@router.get("/postgame")
def postgame(svc: Svc) -> list[dict[str, Any]]:
    return svc.postgame.status()


# ── settings ───────────────────────────────────────────────────────


@router.get("/settings")
def get_settings(svc: Svc) -> dict[str, Any]:
    return svc.ctx.settings.get().public_view()


@router.put("/settings")
def put_settings(svc: Svc, changes: dict[str, Any]) -> dict[str, Any]:
    if changes.get("opendota_api_key") == "set":
        changes.pop("opendota_api_key")  # the masked value came back unchanged
    try:
        updated = svc.ctx.settings.update(changes)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc
    if "opendota_api_key" in changes:
        svc.ctx.reset_client()
    return updated.public_view()


@router.get("/version")
def version(svc: Svc) -> dict[str, Any]:
    return {
        "version": __version__,
        "patch": svc.ctx.data.patch,
        "timer_patch": svc.ctx.timer_patch,
        "user_dir": str(paths.user_dir()),
        "port": svc.port,
    }


# ── data ───────────────────────────────────────────────────────────


@router.get("/data/status")
def data_status(svc: Svc) -> dict[str, Any]:
    return {
        **svc.ctx.data.status(),
        "usage": svc.ctx.client.usage(),
        "refresh": asdict(svc.refresh),
        "steps": list(STEPS),
    }


class RefreshBody(BaseModel):
    steps: list[str] | None = None
    max_calls: int = 300


@router.post("/data/refresh")
def data_refresh(svc: Svc, body: RefreshBody) -> dict[str, Any]:
    steps = body.steps or [s for s in STEPS if s != "draft_model"]
    bad = [s for s in steps if s not in STEPS]
    if bad:
        raise HTTPException(422, f"unknown steps {bad}")
    with svc.lock:
        if svc.refresh.running:
            raise HTTPException(409, "A refresh is already running")
        svc.refresh = RefreshJob(running=True, steps=steps)
    job = svc.refresh

    def progress(step: str, done: int, total: int, message: str) -> None:
        job.progress = {"step": step, "done": done, "total": total, "message": message}

    def run() -> None:
        try:
            refresher = Refresher(
                svc.ctx.client, paths.refreshed_data_dir(), progress, seed_dir=paths.snapshot_dir()
            )
            for result in refresher.run(
                steps, **({"max_calls": body.max_calls} if "matchups" in steps else {})
            ):
                job.results.append(asdict(result))
            svc.ctx.reload()
        except Exception as exc:  # reported to the UI, not swallowed
            job.error = f"{type(exc).__name__}: {exc}"
        finally:
            job.running = False

    threading.Thread(target=run, name="data-refresh", daemon=True).start()
    return asdict(job)
