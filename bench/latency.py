"""Measure what the README quotes: GSI handling time and draft analysis time.

Single machine, in-process and loopback HTTP. Run with:  uv run python bench/latency.py
Writes reports/latency.json and prints a summary.
"""

from __future__ import annotations

import json
import os
import platform
import random
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("D2BG_HOME", tempfile.mkdtemp(prefix="d2bg-bench-"))

import httpx
import uvicorn

from d2bg.api.app import create_app
from d2bg.context import AppContext
from d2bg.draft.service import DraftRequest, analyze
from d2bg.gsi.demo import demo_frames
from d2bg.live.engine import LiveEngine

PORT = 4747
ROOT = Path(__file__).resolve().parent.parent


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def summary(ms: list[float]) -> dict[str, float]:
    return {
        "n": len(ms),
        "p50_ms": round(pct(ms, 0.5), 3),
        "p95_ms": round(pct(ms, 0.95), 3),
        "p99_ms": round(pct(ms, 0.99), 3),
        "max_ms": round(max(ms), 3),
        "mean_ms": round(statistics.mean(ms), 3),
    }


def main() -> None:
    ctx = AppContext()
    frames = [p for hero in ("juggernaut", "lion", "invoker") for _, p in demo_frames(ctx, hero, minutes=40)]

    # 1. The live engine alone (parse, timers, next items, alerts, snapshot build).
    engine = LiveEngine(ctx)
    engine_ms = []
    for p in frames:
        t0 = time.perf_counter()
        engine.ingest(p, source="demo")
        engine_ms.append((time.perf_counter() - t0) * 1000)

    # 2. Full HTTP path: Dota's POST to /gsi on loopback, token check included.
    app = create_app(ctx, port=PORT)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    token = ctx.settings.get().gsi_token
    http_ms = []
    with httpx.Client(base_url=f"http://127.0.0.1:{PORT}") as client:
        for p in frames:
            body = {**p, "auth": {"token": token}}
            t0 = time.perf_counter()
            r = client.post("/gsi", json=body)
            http_ms.append((time.perf_counter() - t0) * 1000)
            r.raise_for_status()
    server.should_exit = True
    thread.join(timeout=5)

    # 3. Draft analysis for random drafts at every stage (0 to 5 heroes a side).
    rng = random.Random(1)
    ids = ctx.data.heroes.ids()
    draft_ms = []
    settings = ctx.settings.get()
    for i in range(300):
        picks = rng.sample(ids, 10)
        k = i % 6
        req = DraftRequest(allies=picks[:k], enemies=picks[5 : 5 + k], bans=rng.sample(ids, 4))
        req.bans = [b for b in req.bans if b not in picks]
        t0 = time.perf_counter()
        analyze(ctx, req, settings)
        draft_ms.append((time.perf_counter() - t0) * 1000)

    report = {
        "machine": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
        "payloads": len(frames),
        "engine_ingest": summary(engine_ms),
        "gsi_http_round_trip": summary(http_ms),
        "draft_analyze": summary(draft_ms),
        "measured_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    out = ROOT / "reports" / "latency.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
