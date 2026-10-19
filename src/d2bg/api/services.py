"""The long-lived objects the API routes share, kept on ``app.state.services``."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request

from d2bg import paths
from d2bg.context import AppContext
from d2bg.gsi.recorder import Player, Recorder
from d2bg.live.engine import LiveEngine
from d2bg.matches.postgame import PostGame


@dataclass
class RefreshJob:
    running: bool = False
    steps: list[str] = field(default_factory=list)
    progress: dict[str, Any] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class Services:
    def __init__(self, ctx: AppContext, port: int) -> None:
        self.ctx = ctx
        self.port = port
        self.lock = threading.Lock()
        self.recorder = Recorder(paths.recordings_dir(), keep=ctx.settings.get().keep_recordings)
        self.postgame = PostGame(ctx)
        self.player: Player | None = None
        self.refresh = RefreshJob()
        self.engine = LiveEngine(
            ctx, on_post_game=self._post_game, on_account=self._account, on_payload=self._record
        )

    def _post_game(self, match_id: str) -> None:
        if self.ctx.settings.get().auto_post_game:
            self.postgame.start(match_id)

    def _account(self, account_id: int) -> None:
        self.ctx.settings.set_account_if_missing(account_id)

    def _record(self, payload: Mapping[str, Any], source: str) -> None:
        if source == "game" and self.ctx.settings.get().record_gsi:
            self.recorder.write(payload)

    def start_player(self, frames: list[tuple[float, dict[str, Any]]], source: str, speed: float) -> None:
        with self.lock:
            if self.player is not None:
                self.player.stop()
            self.engine.reset()

            def feed(payload: dict[str, Any]) -> None:
                self.engine.ingest(payload, source=source)

            self.player = Player(frames, feed, speed=speed)
            self.player.start()

    def stop_player(self) -> None:
        with self.lock:
            if self.player is not None:
                self.player.stop()
                self.player = None

    def close(self) -> None:
        self.stop_player()
        self.recorder.close()


def services(request: Request) -> Services:
    svc: Services = request.app.state.services
    return svc
