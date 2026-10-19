"""Where a value sits among a hero's OpenDota benchmark percentiles."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any

METRICS = {
    "gold_per_min": "GPM",
    "xp_per_min": "XPM",
    "kills_per_min": "Kills / min",
    "last_hits_per_min": "Last hits / min",
    "hero_damage_per_min": "Hero damage / min",
    "hero_healing_per_min": "Healing / min",
    "tower_damage": "Tower damage",
}


def percentile_of(value: float, points: Sequence[Sequence[float]]) -> float | None:
    """Linear interpolation over [[percentile, value], ...] sorted by percentile.

    Below the lowest point returns that percentile scaled toward 0; above the highest, that percentile.
    """
    pts = sorted((float(p), float(v)) for p, v in points)
    if not pts:
        return None
    if value <= pts[0][1]:
        return round(pts[0][0] * (value / pts[0][1]) if pts[0][1] > 0 else 0.0, 3)
    for (p0, v0), (p1, v1) in pairwise(pts):
        if v0 <= value <= v1:
            return round(p0 if v1 == v0 else p0 + (p1 - p0) * (value - v0) / (v1 - v0), 3)
    return pts[-1][0]


def value_at(percentile: float, points: Sequence[Sequence[float]]) -> float | None:
    pts = sorted((float(p), float(v)) for p, v in points)
    if not pts:
        return None
    for (p0, v0), (p1, v1) in pairwise(pts):
        if p0 <= percentile <= p1:
            return v0 if p1 == p0 else v0 + (v1 - v0) * (percentile - p0) / (p1 - p0)
    return pts[0][1] if percentile < pts[0][0] else pts[-1][1]


def compare(
    values: Mapping[str, float], bench: Mapping[str, Sequence[Sequence[float]]] | None
) -> list[dict[str, Any]]:
    out = []
    for key, label in METRICS.items():
        if key not in values or not bench or key not in bench:
            continue
        out.append(
            {
                "metric": key,
                "label": label,
                "value": round(values[key], 2),
                "percentile": percentile_of(values[key], bench[key]),
                "median": value_at(0.5, bench[key]),
            }
        )
    return out
