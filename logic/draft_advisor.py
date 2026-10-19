"""Draft suggestions from a matchup matrix bucket. Pure functions, no I/O.

`bucket` is one entry of build_matrix()["buckets"]: {"heroes", "vs", "with"}.
Hero IDs may be passed as int or str; results use int.

    score(c) = mean over enemies e with vs(c,e) known of vs(c,e)
             + w * mean over allies a with with(c,a) known of with(c,a)
             - role_clash_penalty(c, allies)

vs(c,e) is c's win-rate advantage, in percentage points, against e.
"""
from typing import Iterable, Optional

ROLE_CLASH_PENALTY = 10.0
MIN_META_PICK_RATE = 0.01


def _ids(heroes: Optional[Iterable]) -> set[str]:
    return {str(h) for h in (heroes or [])}


def _lookup(table: dict, a, b) -> Optional[float]:
    return table.get(str(a), {}).get(str(b))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def available(bucket: dict, taken: Iterable = (), bans: Iterable = (),
              blacklist: Iterable = (), whitelist: Iterable = ()) -> list[str]:
    """Heroes that can still be suggested. A non-empty whitelist restricts to it."""
    excluded = _ids(taken) | _ids(bans) | _ids(blacklist)
    allowed = _ids(whitelist)
    return sorted((h for h in bucket["heroes"]
                   if h not in excluded and (not allowed or h in allowed)), key=int)


def _roles(hero_roles: dict, hero) -> set:
    return set(hero_roles.get(str(hero)) or hero_roles.get(int(hero)) or ())


def _max_role_assignment(heroes: list[str], hero_roles: dict) -> int:
    """Most heroes that can hold distinct roles at once (bipartite matching)."""
    holder: dict = {}  # role -> index into heroes

    def place(i: int, seen: set) -> bool:
        for r in _roles(hero_roles, heroes[i]):
            if r in seen:
                continue
            seen.add(r)
            if r not in holder or place(holder[r], seen):
                holder[r] = i
                return True
        return False

    return sum(1 for i in range(len(heroes)) if place(i, set()))


def role_clash_penalty(candidate, allies: Iterable, hero_roles: Optional[dict],
                       penalty: float = ROLE_CLASH_PENALTY) -> float:
    """`penalty` if the candidate cannot take any role the allies leave open.

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
    after = _max_role_assignment(team + [c], hero_roles)
    return penalty if after == before else 0.0


def score(candidate, bucket: dict, enemies: Iterable = (), allies: Iterable = (),
          w: float = 0.5, hero_roles: Optional[dict] = None,
          penalty: float = ROLE_CLASH_PENALTY) -> float:
    if not 0.0 <= w <= 1.0:
        raise ValueError("w must be in [0, 1]")
    enemies, allies = list(enemies), list(allies)
    vs = [v for e in enemies if (v := _lookup(bucket["vs"], candidate, e)) is not None]
    wi = [v for a in allies if (v := _lookup(bucket["with"], candidate, a)) is not None]
    return (_mean(vs) + w * _mean(wi)
            - role_clash_penalty(candidate, allies, hero_roles, penalty))


def suggest(bucket: dict, enemies: Iterable = (), allies: Iterable = (),
            bans: Iterable = (), blacklist: Iterable = (), whitelist: Iterable = (),
            w: float = 0.5, hero_roles: Optional[dict] = None, role=None,
            n: int = 10, penalty: float = ROLE_CLASH_PENALTY) -> list[tuple[int, float]]:
    """Top-n (hero, score), best first. `role` keeps only heroes that can play it."""
    enemies, allies = list(enemies), list(allies)
    pool = available(bucket, enemies + allies, bans, blacklist, whitelist)
    if role is not None and hero_roles:
        pool = [h for h in pool if role in _roles(hero_roles, h)]
    scored = [(int(c), score(c, bucket, enemies, allies, w, hero_roles, penalty))
              for c in pool]
    scored.sort(key=lambda t: (-t[1], t[0]))
    return scored[:n]


def counters(enemy, bucket: dict, n: int = 10, exclude: Iterable = ()) -> list[tuple[int, float]]:
    """The n heroes `enemy` does worst against: lowest vs(enemy, c) first.

    Returns (hero, -vs(enemy, c)), i.e. the edge c has over enemy, in
    percentage points. Unknown (null) pairs are skipped.
    """
    skip = _ids(exclude) | {str(enemy)}
    row = bucket["vs"].get(str(enemy), {})
    pairs = [(int(c), -v) for c, v in row.items() if v is not None and c not in skip]
    pairs.sort(key=lambda t: (-t[1], t[0]))
    return pairs[:n]


def hot_counters(enemies: Iterable, bucket: dict, n: int = 10,
                 exclude: Iterable = (), min_enemies: int = 2) -> list[dict]:
    """Heroes in counters(e) for at least `min_enemies` different enemies.

    Each result: {"hero", "enemies": [countered enemy ids], "advantage": summed}.
    Sorted by number of enemies countered, then summed advantage.
    """
    enemies = [str(e) for e in enemies]
    skip = _ids(exclude) | set(enemies)
    hits: dict[int, dict] = {}
    for e in enemies:
        for c, adv in counters(e, bucket, n, skip):
            h = hits.setdefault(c, {"hero": c, "enemies": [], "advantage": 0.0})
            h["enemies"].append(int(e))
            h["advantage"] += adv
    hot = [h for h in hits.values() if len(h["enemies"]) >= min_enemies]
    hot.sort(key=lambda h: (-len(h["enemies"]), -h["advantage"], h["hero"]))
    return hot


def meta(bucket: dict, n: int = 10, min_pick_rate: float = MIN_META_PICK_RATE,
         exclude: Iterable = ()) -> list[tuple[int, float]]:
    """Top-n (hero, smoothed WR) among heroes picked in >= min_pick_rate of matches."""
    skip = _ids(exclude)
    rows = [(int(h), s["wr"]) for h, s in bucket["heroes"].items()
            if s["pick_rate"] >= min_pick_rate and h not in skip]
    rows.sort(key=lambda t: (-t[1], t[0]))
    return rows[:n]
