"""Record GSI payloads to gzip JSON lines and play them back.

One file per match (or per menu session): ``<recordings>/<YYYYmmdd-HHMMSS>_<match>.jsonl.gz``.
Each line is ``{"t": seconds since the first payload, "p": payload}`` with the auth token removed.
"""

from __future__ import annotations

import gzip
import json
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any, TextIO


def _clean(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k != "auth"}


class Recorder:
    def __init__(self, directory: Path, keep: int = 20, clock: Callable[[], float] = time.time) -> None:
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self.keep = keep
        self._clock = clock
        self._lock = threading.Lock()
        self._file: TextIO | None = None
        self._path: Path | None = None
        self._start = 0.0
        self._match: str | None = None
        self.lines = 0

    @property
    def current(self) -> Path | None:
        return self._path

    def write(self, payload: Mapping[str, Any]) -> None:
        match = str((payload.get("map") or {}).get("matchid") or "") or None
        with self._lock:
            if self._file is None or (match and match != self._match):
                self._open(match)
            assert self._file is not None
            self._file.write(
                json.dumps(
                    {"t": round(self._clock() - self._start, 3), "p": _clean(payload)}, separators=(",", ":")
                )
                + "\n"
            )
            self.lines += 1

    def _open(self, match: str | None) -> None:
        self._close()
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(self._clock()))
        self._path = self.dir / f"{stamp}_{match or 'session'}.jsonl.gz"
        self._file = gzip.open(self._path, "wt", encoding="utf-8")  # noqa: SIM115 - kept open across writes, closed in _close
        self._start = self._clock()
        self._match = match
        self.lines = 0
        self._prune()

    def _close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def close(self) -> None:
        with self._lock:
            self._close()

    def _prune(self) -> None:
        files = sorted(self.dir.glob("*.jsonl.gz"))
        for old in files[: max(len(files) - self.keep, 0)]:
            if old != self._path:
                old.unlink(missing_ok=True)


def list_recordings(directory: Path) -> list[dict[str, Any]]:
    out = []
    for f in sorted(directory.glob("*.jsonl.gz"), reverse=True):
        st = f.stat()
        out.append({"name": f.name, "bytes": st.st_size, "modified": int(st.st_mtime)})
    return out


def read(path: Path) -> Iterator[tuple[float, dict[str, Any]]]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                yield float(row["t"]), row["p"]


class Player:
    """Feeds a recording (or any timed payload list) into a callback at ``speed``x on a thread."""

    def __init__(
        self,
        frames: list[tuple[float, dict[str, Any]]],
        ingest: Callable[[dict[str, Any]], None],
        speed: float = 1.0,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.frames = frames
        self.ingest = ingest
        self.speed = max(speed, 0.01)
        self._stop = threading.Event()
        # By default the wait between frames ends as soon as stop() is called.
        self._sleep: Callable[[float], object] = sleep or self._stop.wait
        self._thread: threading.Thread | None = None
        self.position = 0

    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, name="gsi-replay", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop and wait (briefly) for the thread, so no frame lands after this returns."""
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def run(self) -> None:
        last = None
        for i, (t, payload) in enumerate(self.frames):
            if self._stop.is_set():
                return
            if last is not None and t > last:
                self._sleep((t - last) / self.speed)
                if self._stop.is_set():
                    return
            last = t
            self.position = i + 1
            self.ingest(payload)
