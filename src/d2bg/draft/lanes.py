"""Lane matchups: who goes where, and how each lane looks on paper.

Lanes are named from each team's side: Radiant's safe lane (bottom) meets Dire's off lane, both mid
lanes meet, and Radiant's off lane (top) meets Dire's safe lane.

    lane advantage = mean vs(a, e) over a in our lane, e in their lane
                   + 0.5 * (mean with within our lane - mean with within theirs)

in percentage points, positive is good for us.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from typing import Any

LANE_OF_POSITION = {1: "safe", 2: "mid", 3: "off", 4: "off", 5: "safe"}
OPPOSITE = {"safe": "off", "mid": "mid", "off": "safe"}


def _get(table: Mapping[str, Any], a: int, b: int) -> float | None:
    v = table.get(str(a), {}).get(str(b))
    return None if v is None else float(v)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def assign_positions(team: Sequence[int], shares: Mapping[int, Mapping[int, float]]) -> dict[int, int]:
    """Most likely position for each hero: the assignment with the highest product of shares."""
    team = list(team)[:5]
    if not team:
        return {}
    best: tuple[float, tuple[int, ...]] = (-1.0, ())
    for perm in itertools.permutations(range(1, 6), len(team)):
        p = 1.0
        for hero, pos in zip(team, perm, strict=True):
            p *= shares.get(hero, {}).get(pos, 0.0) + 0.01  # never let one unknown zero everything
        if p > best[0]:
            best = (p, perm)
    return dict(zip(team, best[1], strict=True))


def lanes_from_positions(positions: Mapping[int, int]) -> dict[str, list[int]]:
    lanes: dict[str, list[int]] = {"safe": [], "mid": [], "off": []}
    for hero, pos in sorted(positions.items(), key=lambda kv: kv[1]):
        lanes[LANE_OF_POSITION.get(pos, "off")].append(hero)
    return lanes


def lane_matchups(
    ours: Mapping[str, Sequence[int]], theirs: Mapping[str, Sequence[int]], bucket: Mapping[str, Any]
) -> list[dict[str, Any]]:
    out = []
    for lane in ("safe", "mid", "off"):
        a_team, b_team = list(ours.get(lane, [])), list(theirs.get(OPPOSITE[lane], []))
        vs = [v for a in a_team for b in b_team if (v := _get(bucket["vs"], a, b)) is not None]
        syn_a = [
            v for a, b in itertools.permutations(a_team, 2) if (v := _get(bucket["with"], a, b)) is not None
        ]
        syn_b = [
            v for a, b in itertools.permutations(b_team, 2) if (v := _get(bucket["with"], a, b)) is not None
        ]
        adv = _mean(vs) + 0.5 * (_mean(syn_a) - _mean(syn_b))
        out.append(
            {
                "lane": lane,
                "ours": a_team,
                "theirs": b_team,
                "advantage": round(adv, 2),
                "pairs_known": len(vs),
                "pairs_total": len(a_team) * len(b_team),
            }
        )
    return out
