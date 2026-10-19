"""After a match ends, wait for OpenDota to have it, then keep the review ready for the UI.

OpenDota usually has a match a few minutes after it ends. This polls with growing gaps (1, 2, 3, 5,
8 ... minutes, at most 10 tries) so it never spends more than a handful of requests per match.
A replay parse request (``POST /request/{id}``) is sent only if he switched it on in Settings.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from d2bg.context import AppContext
from d2bg.opendota import NotFoundError, OpenDotaError

DELAYS = (60, 120, 180, 300, 480, 600, 900, 900, 1200, 1800)


class PostGame:
    def __init__(
        self, ctx: AppContext, sleep: Callable[[float], None] = time.sleep, delays: tuple[int, ...] = DELAYS
    ) -> None:
        self.ctx = ctx
        self._sleep = sleep
        self.delays = delays
        self._lock = threading.Lock()
        self.jobs: dict[str, dict[str, Any]] = {}

    def status(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(v) for v in self.jobs.values()]

    def start(self, match_id: str) -> None:
        with self._lock:
            if match_id in self.jobs:
                return
            self.jobs[match_id] = {
                "match_id": match_id,
                "status": "waiting",
                "attempts": 0,
                "parse_requested": False,
                "error": None,
            }
        threading.Thread(target=self._run, args=(match_id,), name=f"postgame-{match_id}", daemon=True).start()

    def _set(self, match_id: str, **changes: Any) -> None:
        with self._lock:
            self.jobs[match_id].update(changes)

    def _run(self, match_id: str) -> None:
        settings = self.ctx.settings.get()
        for i, delay in enumerate(self.delays):
            self._sleep(delay)
            self._set(match_id, attempts=i + 1)
            try:
                match = self.ctx.client.get(f"matches/{match_id}", ttl=0)
            except NotFoundError:
                continue
            except OpenDotaError as exc:
                self._set(match_id, error=str(exc))
                continue
            if isinstance(match, dict) and match.get("players") and match.get("duration"):
                if settings.request_parse and not match.get("version"):
                    try:
                        self.ctx.client.post(f"request/{match_id}")
                        self._set(match_id, parse_requested=True)
                    except OpenDotaError as exc:
                        self._set(match_id, error=f"parse request failed: {exc}")
                self._set(match_id, status="ready", error=None)
                return
        self._set(match_id, status="gave_up")
