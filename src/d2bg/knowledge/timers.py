"""Game timers from the per-patch rule file and the live game clock. Pure functions.

All times are the in-game clock (``map.clock_time`` in GSI), in seconds; 0 is the horn.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TimerRule:
    id: str
    label: str
    lead: int
    cite: str
    first: int | None = None
    interval: int | None = None
    times: tuple[int, ...] = ()
    names: tuple[str, ...] = ()
    respawn: int | None = None
    respawn_min: int | None = None
    respawn_max: int | None = None
    duration: int | None = None
    period: int | None = None
    default_on: bool = True

    @classmethod
    def load(cls, doc: Mapping[str, Any]) -> list[TimerRule]:
        out = []
        for r in doc["rules"]:
            out.append(
                cls(
                    id=r["id"],
                    label=r["label"],
                    lead=int(r.get("lead", 15)),
                    cite=r["cite"],
                    first=r.get("first"),
                    interval=r.get("interval"),
                    times=tuple(r.get("times", ())),
                    names=tuple(r.get("names", ())),
                    respawn=r.get("respawn"),
                    respawn_min=r.get("respawn_min"),
                    respawn_max=r.get("respawn_max"),
                    duration=r.get("duration"),
                    period=r.get("period"),
                    default_on=bool(r.get("default_on", True)),
                )
            )
        return out


@dataclass
class TimerState:
    """Events the timers depend on, set from GSI events or a click in the UI."""

    roshan_killed_at: float | None = None
    aegis_picked_at: float | None = None
    tormentor_killed_at: float | None = None
    daytime: bool | None = None
    day_flip_at: float | None = None
    notes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TimerView:
    id: str
    label: str
    at: float | None  # clock time of the next event; None when there is nothing to count down
    seconds_left: float | None
    lead: int
    status: str  # "upcoming", "window", "alive", "active", "estimated"
    detail: str
    cite: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "at": self.at,
            "seconds_left": self.seconds_left,
            "lead": self.lead,
            "status": self.status,
            "detail": self.detail,
            "cite": self.cite,
        }


def next_periodic(first: int, interval: int, clock: float) -> float:
    """First spawn strictly after ``clock``."""
    if clock < first:
        return float(first)
    k = math.floor((clock - first) / interval) + 1
    return float(first + k * interval)


def next_fixed(times: Iterable[int], clock: float) -> tuple[int, float] | None:
    for i, t in enumerate(times):
        if t > clock:
            return i, float(t)
    return None


def fmt(seconds: float) -> str:
    sign = "-" if seconds < 0 else ""
    s = int(abs(seconds))
    return f"{sign}{s // 60}:{s % 60:02d}"


def evaluate(rule: TimerRule, clock: float, state: TimerState) -> TimerView | None:
    def view(at: float | None, status: str, detail: str) -> TimerView:
        left = None if at is None else round(at - clock, 1)
        return TimerView(rule.id, rule.label, at, left, rule.lead, status, detail, rule.cite)

    if rule.id == "roshan":
        if state.roshan_killed_at is None or rule.respawn_min is None or rule.respawn_max is None:
            return view(None, "alive", "Alive (no kill seen)")
        lo = state.roshan_killed_at + rule.respawn_min
        hi = state.roshan_killed_at + rule.respawn_max
        if clock < lo:
            return view(lo, "upcoming", f"May respawn {fmt(lo)}, certainly by {fmt(hi)}")
        if clock < hi:
            return view(hi, "window", f"May be up now; certainly up by {fmt(hi)}")
        return view(None, "alive", f"Up since {fmt(hi)} at the latest")
    if rule.id == "aegis":
        if state.aegis_picked_at is None or rule.duration is None:
            return None
        end = state.aegis_picked_at + rule.duration
        return None if clock >= end else view(end, "active", f"Expires at {fmt(end)}")
    if rule.id == "tormentor":
        first = float(rule.first or 0)
        if state.tormentor_killed_at is not None and rule.respawn:
            back = state.tormentor_killed_at + rule.respawn
            if clock < back:
                return view(back, "upcoming", f"Respawns at {fmt(back)}")
            return view(None, "alive", "Up")
        if clock < first:
            return view(first, "upcoming", f"First spawn at {fmt(first)}")
        return view(None, "alive", "Up (no kill seen)")
    if rule.id == "day_night":
        period = rule.period or 300
        anchor = state.day_flip_at if state.day_flip_at is not None else 0.0
        estimated = state.day_flip_at is None
        nxt = anchor + period * (math.floor((clock - anchor) / period) + 1)
        is_day = state.daytime if state.daytime is not None else (math.floor(clock / period) % 2 == 0)
        detail = ("Night" if is_day else "Day") + f" at {fmt(nxt)}"
        return view(nxt, "estimated" if estimated else "upcoming", detail)
    if rule.times:
        hit = next_fixed(rule.times, clock)
        if hit is None:
            return None
        i, at = hit
        name = rule.names[i] if i < len(rule.names) else rule.label
        return view(at, "upcoming", f"{name} at {fmt(at)}")
    if rule.first is not None and rule.interval:
        at = next_periodic(rule.first, rule.interval, clock)
        return view(at, "upcoming", f"Next at {fmt(at)}")
    return None


def upcoming(
    rules: Iterable[TimerRule], clock: float, state: TimerState, enabled: Mapping[str, bool] | None = None
) -> list[TimerView]:
    """Every enabled timer, soonest first; ones with no countdown go last."""
    views = []
    for rule in rules:
        on = (enabled or {}).get(rule.id, rule.default_on)
        if not on:
            continue
        v = evaluate(rule, clock, state)
        if v is not None:
            views.append(v)
    views.sort(key=lambda v: (v.seconds_left is None, v.seconds_left or 0.0, v.id))
    return views
