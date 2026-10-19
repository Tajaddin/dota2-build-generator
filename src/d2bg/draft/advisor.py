"""Draft suggestions from one matchup-matrix bucket. Pure functions, no I/O.

``bucket`` is one entry of ``build_matrix()["buckets"]``: ``{"heroes", "vs", "with"}``. Hero IDs may be
passed as int or str; results use int.

    score(c) = mean over enemies e with vs(c,e) known of vs(c,e)
             + w * mean over allies a with with(c,a) known of with(c,a)
             - role_clash_penalty(c, allies)
             + pool_bonus(c)

vs(c,e) is c's win-rate advantage, in percentage points, against e.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from typing import Any

ROLE_CLASH_PENALTY = 10.0
MIN_META_PICK_RATE = 0.01
POOL_BONUS = 1.5

Bucket = Mapping[str, Any]
HeroRoles = Mapping[Any, Collection[Any]]


def _ids(heroes: Iterable[Any] | None) -> set[str]:
    return {str(h) for h in (heroes or [])}


def _lookup(table: Mapping[str, Any], a: Any, b: Any) -> float | None:
    v = table.get(str(a), {}).get(str(b))
    return None if v is None else float(v)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def available(
    bucket: Bucket,
    taken: Iterable[Any] = (),
    bans: Iterable[Any] = (),
    blacklist: Iterable[Any] = (),
    whitelist: Iterable[Any] = (),
) -> list[str]:
    """Heroes that can still be suggested. A non-empty whitelist restricts to it."""
    excluded = _ids(taken) | _ids(bans) | _ids(blacklist)
    allowed = _ids(whitelist)
    return sorted(
        (h for h in bucket["heroes"] if h not in excluded and (not allowed or h in allowed)), key=int
    )


def _roles(hero_roles: HeroRoles, hero: Any) -> set[Any]:
    return set(hero_roles.get(str(hero)) or hero_roles.get(int(hero)) or ())


def _max_role_assignment(heroes: list[str], hero_roles: HeroRoles) -> int:
    """Most heroes that can hold distinct roles at once (bipartite matching)."""
    holder: dict[Any, int] = {}  # role -> index into heroes

    def place(i: int, seen: set[Any]) -> bool:
        for r in _roles(hero_roles, heroes[i]):
            if r in seen:
                continue
            seen.add(r)
            if r not in holder or place(holder[r], seen):
                holder[r] = i
                return True
        return False

    return sum(1 for i in range(len(heroes)) if place(i, set()))


def role_clash_penalty(
    candidate: Any, allies: Iterable[Any], hero_roles: HeroRoles | None, penalty: float = ROLE_CLASH_PENALTY
) -> float:
    """``penalty`` if the candidate cannot take any role the allies leave open.

    hero_roles maps hero -> roles it can play (any labels, e.g. positions 1-5).
    A hero with no known roles never clashes.
    """
    if not hero_roles:
        return 0.0
    c = str(candidate)
    if not _roles(hero_roles, c):
        return 0.0
    team = [str(a) for a in allies]
    if not team:
        return 0.0
    before = _max_role_assignment(team, hero_roles)
    after = _max_role_assignment([*team, c], hero_roles)
    return penalty if after == before else 0.0


def score(
    candidate: Any,
    bucket: Bucket,
    enemies: Iterable[Any] = (),
    allies: Iterable[Any] = (),
    w: float = 0.5,
    hero_roles: HeroRoles | None = None,
    penalty: float = ROLE_CLASH_PENALTY,
    pool: Collection[Any] = (),
    pool_bonus: float = 0.0,
) -> float:
    if not 0.0 <= w <= 1.0:
        raise ValueError("w must be in [0, 1]")
    enemies, allies = list(enemies), list(allies)
    vs = [v for e in enemies if (v := _lookup(bucket["vs"], candidate, e)) is not None]
    wi = [v for a in allies if (v := _lookup(bucket["with"], candidate, a)) is not None]
    bonus = pool_bonus if str(candidate) in _ids(pool) else 0.0
    return _mean(vs) + w * _mean(wi) - role_clash_penalty(candidate, allies, hero_roles, penalty) + bonus


def explain(
    candidate: Any, bucket: Bucket, enemies: Iterable[Any] = (), allies: Iterable[Any] = (), n: int = 3
) -> dict[str, list[dict[str, float | int]]]:
    """The matchups behind a score: best and worst enemies, best allies."""
    vs = [
        {"hero": int(e), "value": v}
        for e in enemies
        if (v := _lookup(bucket["vs"], candidate, e)) is not None
    ]
    wi = [
        {"hero": int(a), "value": v}
        for a in allies
        if (v := _lookup(bucket["with"], candidate, a)) is not None
    ]
    vs.sort(key=lambda d: -d["value"])
    wi.sort(key=lambda d: -d["value"])
    return {
        "good_against": [d for d in vs if d["value"] > 0][:n],
        "bad_against": [d for d in reversed(vs) if d["value"] < 0][:n],
        "with": [d for d in wi if d["value"] > 0][:n],
    }


def suggest(
    bucket: Bucket,
    enemies: Iterable[Any] = (),
    allies: Iterable[Any] = (),
    bans: Iterable[Any] = (),
    blacklist: Iterable[Any] = (),
    whitelist: Iterable[Any] = (),
    w: float = 0.5,
    hero_roles: HeroRoles | None = None,
    role: Any = None,
    n: int = 10,
    penalty: float = ROLE_CLASH_PENALTY,
    pool: Collection[Any] = (),
    pool_bonus: float = 0.0,
) -> list[tuple[int, float]]:
    """Top-n (hero, score), best first. ``role`` keeps only heroes that can play it."""
    enemies, allies = list(enemies), list(allies)
    candidates = available(bucket, enemies + allies, bans, blacklist, whitelist)
    if role is not None and hero_roles:
        candidates = [h for h in candidates if role in _roles(hero_roles, h)]
    scored = [
        (int(c), score(c, bucket, enemies, allies, w, hero_roles, penalty, pool, pool_bonus))
        for c in candidates
    ]
    scored.sort(key=lambda t: (-t[1], t[0]))
    return scored[:n]


def counters(enemy: Any, bucket: Bucket, n: int = 10, exclude: Iterable[Any] = ()) -> list[tuple[int, float]]:
    """The n heroes ``enemy`` does worst against: lowest vs(enemy, c) first.

    Returns (hero, -vs(enemy, c)), i.e. the edge c has over enemy, in percentage points.
    Unknown (null) pairs are skipped.
    """
    skip = _ids(exclude) | {str(enemy)}
    row = bucket["vs"].get(str(enemy), {})
    pairs = [(int(c), -float(v)) for c, v in row.items() if v is not None and c not in skip]
    pairs.sort(key=lambda t: (-t[1], t[0]))
    return pairs[:n]


def hot_counters(
    enemies: Iterable[Any], bucket: Bucket, n: int = 10, exclude: Iterable[Any] = (), min_enemies: int = 2
) -> list[dict[str, Any]]:
    """Heroes in counters(e) for at least ``min_enemies`` different enemies.

    Each result: {"hero", "enemies": [countered enemy ids], "advantage": summed}.
    Sorted by number of enemies countered, then summed advantage.
    """
    enemy_ids = [str(e) for e in enemies]
    skip = _ids(exclude) | set(enemy_ids)
    hits: dict[int, dict[str, Any]] = {}
    for e in enemy_ids:
        for c, adv in counters(e, bucket, n, skip):
            h = hits.setdefault(c, {"hero": c, "enemies": [], "advantage": 0.0})
            h["enemies"].append(int(e))
            h["advantage"] += adv
    hot = [h for h in hits.values() if len(h["enemies"]) >= min_enemies]
    hot.sort(key=lambda h: (-len(h["enemies"]), -h["advantage"], h["hero"]))
    return hot


def meta(
    bucket: Bucket, n: int = 10, min_pick_rate: float = MIN_META_PICK_RATE, exclude: Iterable[Any] = ()
) -> list[tuple[int, float]]:
    """Top-n (hero, smoothed WR) among heroes picked in >= min_pick_rate of matches."""
    skip = _ids(exclude)
    rows = [
        (int(h), float(s["wr"]))
        for h, s in bucket["heroes"].items()
        if s["pick_rate"] >= min_pick_rate and h not in skip
    ]
    rows.sort(key=lambda t: (-t[1], t[0]))
    return rows[:n]


def ban_suggestions(
    bucket: Bucket,
    allies: Iterable[Any] = (),
    enemies: Iterable[Any] = (),
    bans: Iterable[Any] = (),
    n: int = 10,
    meta_weight: float = 0.5,
    min_pick_rate: float = MIN_META_PICK_RATE,
) -> list[dict[str, Any]]:
    """Heroes worth banning: how hard they beat our picks, plus how strong they are overall.

    threat(h) = mean over allies a of vs(h, a) + meta_weight * 100 * (WR(h) - 0.5)
    With no allies picked yet this is the meta term alone.
    """
    ally_ids = [str(a) for a in allies]
    taken = _ids(ally_ids) | _ids(enemies) | _ids(bans)
    out: list[dict[str, Any]] = []
    for h, stats in bucket["heroes"].items():
        if h in taken or float(stats.get("pick_rate", 0)) < min_pick_rate:
            continue
        beats = [(int(a), v) for a in ally_ids if (v := _lookup(bucket["vs"], h, a)) is not None]
        threat = _mean([v for _, v in beats]) + meta_weight * 100 * (float(stats["wr"]) - 0.5)
        out.append(
            {
                "hero": int(h),
                "threat": round(threat, 3),
                "wr": float(stats["wr"]),
                "beats": sorted(
                    ({"hero": a, "value": v} for a, v in beats if v > 0), key=lambda d: -d["value"]
                )[:3],
            }
        )
    out.sort(key=lambda d: (-d["threat"], d["hero"]))
    return out[:n]


def counterability(hero: Any, bucket: Bucket, n: int = 10) -> float:
    """Mean edge of the ``n`` strongest counters to ``hero``. Higher means pick it later."""
    return _mean([adv for _, adv in counters(hero, bucket, n)])
