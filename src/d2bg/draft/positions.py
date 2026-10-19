"""Which positions (1 safe-lane carry ... 5 hard support) each hero is played in.

Primary source: pro matches on the current patch (``pro_builds.json`` positions, assigned per team by
lane and GPM, see ``pipeline.transform.assign_positions``). Heroes with fewer than ``MIN_GAMES`` pro
games fall back to public lane-role statistics, then to their listed roles.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MIN_GAMES = 15
MIN_SHARE = 0.12

# Public lane roles: 1 safe, 2 mid, 3 off, 4 jungle (supports roam). Split each lane between its core
# and support position by whether the hero is listed as a Support.
_LANE_TO_POS = {"1": (1, 5), "2": (2, 2), "3": (3, 4), "4": (4, 4)}


def shares_from_counts(counts: Mapping[str, int]) -> dict[int, float]:
    total = sum(counts.values())
    if not total:
        return {}
    return {int(p): round(n / total, 3) for p, n in sorted(counts.items())}


def hero_positions(
    pro_builds: Mapping[str, Any] | None,
    lane_roles: Mapping[str, Any] | None,
    heroes: Mapping[int, tuple[str, ...]],
) -> dict[int, dict[str, Any]]:
    """{hero_id: {"shares": {pos: share}, "source": ..., "games": n}} for every hero."""
    out: dict[int, dict[str, Any]] = {}
    for hero_id, roles in heroes.items():
        pro = ((pro_builds or {}).get("heroes", {}).get(str(hero_id)) or {}).get("positions") or {}
        if sum(pro.values()) >= MIN_GAMES:
            out[hero_id] = {"shares": shares_from_counts(pro), "source": "pro", "games": sum(pro.values())}
            continue
        lanes = (lane_roles or {}).get(str(hero_id)) or {}
        if sum(g for g, _ in lanes.values()) >= MIN_GAMES:
            support = "Support" in roles
            counts: dict[str, int] = {}
            for lane, (games, _) in lanes.items():
                core, sup = _LANE_TO_POS.get(lane, (4, 4))
                pos = sup if support else core
                counts[str(pos)] = counts.get(str(pos), 0) + int(games)
            out[hero_id] = {
                "shares": shares_from_counts(counts),
                "source": "public lanes",
                "games": sum(counts.values()),
            }
            continue
        guess: dict[str, int] = {}
        if "Carry" in roles:
            guess["1"] = 1
        if "Support" in roles:
            guess["5"] = guess["4"] = 1
        if "Initiator" in roles or "Durable" in roles:
            guess["3"] = 1
        if "Nuker" in roles and "Support" not in roles:
            guess["2"] = 1
        out[hero_id] = {
            "shares": shares_from_counts(guess or {"1": 1, "2": 1, "3": 1, "4": 1, "5": 1}),
            "source": "listed roles",
            "games": 0,
        }
    return out


def playable(positions: Mapping[int, Mapping[str, Any]], min_share: float = MIN_SHARE) -> dict[int, set[int]]:
    """Positions a hero is played in at least ``min_share`` of the time (always its top one)."""
    out: dict[int, set[int]] = {}
    for hero_id, info in positions.items():
        shares: Mapping[int, float] = info["shares"]
        keep = {p for p, s in shares.items() if s >= min_share}
        if shares and not keep:
            keep = {max(shares, key=lambda p: shares[p])}
        out[hero_id] = keep
    return out
