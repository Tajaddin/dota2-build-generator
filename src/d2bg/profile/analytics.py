"""Pure analytics over a player's match list (OpenDota ``/players/{id}/matches`` rows)."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

MEDALS = {
    1: "Herald",
    2: "Guardian",
    3: "Crusader",
    4: "Archon",
    5: "Legend",
    6: "Ancient",
    7: "Divine",
    8: "Immortal",
}
SESSION_GAP = 2 * 3600


def won(m: Mapping[str, Any]) -> bool:
    return bool(m.get("radiant_win")) == (int(m.get("player_slot", 0)) < 128)


def rank_name(rank_tier: int | None, leaderboard: int | None = None) -> str | None:
    if not rank_tier:
        return None
    medal, stars = divmod(int(rank_tier), 10)
    name = MEDALS.get(medal, "Unknown")
    if medal == 8:
        return f"Immortal #{leaderboard}" if leaderboard else "Immortal"
    return f"{name} {stars}" if stars else name


def wilson_lower(wins: int, games: int, z: float = 1.96) -> float:
    """Lower bound of the 95% Wilson interval for a win rate; 0 with no games."""
    if games == 0:
        return 0.0
    p = wins / games
    denom = 1 + z * z / games
    centre = p + z * z / (2 * games)
    margin = z * math.sqrt(p * (1 - p) / games + z * z / (4 * games * games))
    return (centre - margin) / denom


def streaks(matches: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Current and longest streaks. ``matches`` newest first."""
    current, kind = 0, None
    for m in matches:
        w = won(m)
        if kind is None:
            kind = w
        if w != kind:
            break
        current += 1
    longest_win = longest_loss = run = 0
    prev = None
    for m in reversed(matches):
        w = won(m)
        run = run + 1 if w == prev else 1
        prev = w
        if w:
            longest_win = max(longest_win, run)
        else:
            longest_loss = max(longest_loss, run)
    return {
        "current": current,
        "current_kind": "win" if kind else ("loss" if kind is not None else None),
        "longest_win": longest_win,
        "longest_loss": longest_loss,
    }


def sessions(matches: Sequence[Mapping[str, Any]], gap: int = SESSION_GAP) -> list[dict[str, Any]]:
    """Group matches played less than ``gap`` seconds apart. Newest session first."""
    ordered = sorted(matches, key=lambda m: m.get("start_time", 0))
    out: list[dict[str, Any]] = []
    for m in ordered:
        start, end = int(m.get("start_time", 0)), int(m.get("start_time", 0)) + int(m.get("duration", 0))
        if out and start - out[-1]["end"] <= gap:
            s = out[-1]
            s["end"] = max(s["end"], end)
        else:
            s = {"start": start, "end": end, "games": 0, "wins": 0, "results": []}
            out.append(s)
        s["games"] += 1
        s["wins"] += int(won(m))
        s["results"].append("W" if won(m) else "L")
    return list(reversed(out))


def by_hour(matches: Iterable[Mapping[str, Any]], tz: Any = None) -> list[dict[str, Any]]:
    acc: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for m in matches:
        hour = datetime.fromtimestamp(int(m.get("start_time", 0)), tz=tz).hour
        acc[hour][0] += 1
        acc[hour][1] += int(won(m))
    return [
        {"hour": h, "games": g, "wins": w, "win_rate": round(w / g, 3)} for h, (g, w) in sorted(acc.items())
    ]


def hero_pool(matches: Iterable[Mapping[str, Any]], min_games: int = 1) -> list[dict[str, Any]]:
    acc: dict[int, dict[str, Any]] = {}
    for m in matches:
        h = int(m.get("hero_id") or 0)
        if not h:
            continue
        row = acc.setdefault(h, {"hero": h, "games": 0, "wins": 0, "last_played": 0, "kda": [0, 0, 0]})
        row["games"] += 1
        row["wins"] += int(won(m))
        row["last_played"] = max(row["last_played"], int(m.get("start_time", 0)))
        for i, k in enumerate(("kills", "deaths", "assists")):
            row["kda"][i] += int(m.get(k) or 0)
    out = []
    for row in acc.values():
        if row["games"] < min_games:
            continue
        g = row["games"]
        k, d, a = row.pop("kda")
        out.append(
            {
                **row,
                "win_rate": round(row["wins"] / g, 3),
                "wilson_lower": round(wilson_lower(row["wins"], g), 3),
                "kda": round((k + a) / max(d, 1), 2),
            }
        )
    out.sort(key=lambda r: (-r["games"], -r["wilson_lower"]))
    return out


def rolling_win_rate(matches: Sequence[Mapping[str, Any]], window: int = 20) -> list[dict[str, Any]]:
    """Win rate over the previous ``window`` games, oldest first."""
    ordered = sorted(matches, key=lambda m: m.get("start_time", 0))
    out = []
    wins: list[int] = []
    for m in ordered:
        wins.append(int(won(m)))
        if len(wins) > window:
            wins.pop(0)
        if len(wins) == window:
            out.append({"start_time": m.get("start_time"), "win_rate": round(sum(wins) / window, 3)})
    return out


def lane_roles(matches: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    names = {1: "safe", 2: "mid", 3: "off", 4: "jungle"}
    out: dict[str, int] = defaultdict(int)
    for m in matches:
        lr = m.get("lane_role")
        if lr in names:
            out[names[lr]] += 1
    return dict(out)


def summary(matches: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    games = len(matches)
    wins = sum(1 for m in matches if won(m))
    recent = matches[:20]
    return {
        "games": games,
        "wins": wins,
        "win_rate": round(wins / games, 3) if games else None,
        "recent_20": {"games": len(recent), "wins": sum(1 for m in recent if won(m))},
        "avg_kda": round(
            sum(
                (int(m.get("kills") or 0) + int(m.get("assists") or 0)) / max(int(m.get("deaths") or 0), 1)
                for m in matches
            )
            / games,
            2,
        )
        if games
        else None,
        "avg_duration_min": round(sum(int(m.get("duration") or 0) for m in matches) / games / 60, 1)
        if games
        else None,
    }
