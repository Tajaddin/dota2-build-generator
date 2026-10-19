"""Pure functions that turn OpenDota responses into the snapshot files. No I/O.

Each function takes decoded JSON and returns the compact document the app loads. Keeping them pure
means every number in the snapshot can be checked by a unit test on a small fixture.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

HERO_PREFIX = "npc_dota_hero_"
CDN = "https://cdn.cloudflare.steamstatic.com"

BASE_STAT_FIELDS = (
    "base_health",
    "base_health_regen",
    "base_mana",
    "base_mana_regen",
    "base_armor",
    "base_mr",
    "base_attack_min",
    "base_attack_max",
    "base_str",
    "base_agi",
    "base_int",
    "str_gain",
    "agi_gain",
    "int_gain",
    "attack_range",
    "projectile_speed",
    "attack_rate",
    "base_attack_time",
    "attack_point",
    "move_speed",
    "turn_rate",
    "day_vision",
    "night_vision",
)

# Items that are bought for the moment, not as part of a build.
CONSUMABLES = frozenset(
    {
        "tango",
        "tango_single",
        "flask",
        "clarity",
        "enchanted_mango",
        "faerie_fire",
        "tpscroll",
        "ward_observer",
        "ward_sentry",
        "ward_dispenser",
        "dust",
        "smoke_of_deceit",
        "bottle",
        "famango",
        "great_famango",
        "greater_famango",
        "blood_grenade",
        "tome_of_knowledge",
        "cheese",
        "aegis",
        "refresher_shard",
        "roshans_banner",
        "aghanims_shard_roshan",
        "ultimate_scepter_roshan",
        "courier",
        "flying_courier",
        "madstone_bundle",
    }
)

KEEP_BASIC = frozenset({"blink"})

PHASES = {
    "start_game_items": "start",
    "early_game_items": "early",
    "mid_game_items": "mid",
    "late_game_items": "late",
}


def _img(path: str | None) -> str | None:
    if not path:
        return None
    return CDN + path.split("?")[0]


def hero_key(npc_name: str) -> str:
    return npc_name.removeprefix(HERO_PREFIX)


def _flat(values: Iterable[Any]) -> list[str]:
    """Ability lists are flat strings except for a nested list or two (Monkey King's transform)."""
    out: list[str] = []
    for v in values:
        out.extend(_flat(v) if isinstance(v, list) else [str(v)])
    return out


# ── constants ──────────────────────────────────────────────────────


def heroes_doc(
    heroes: Mapping[str, Any], hero_abilities: Mapping[str, Any], aghs: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    aghs_by_id = {a.get("hero_id"): a for a in aghs}
    out = []
    for raw in sorted(heroes.values(), key=lambda h: h["id"]):
        npc = raw["name"]
        abil = hero_abilities.get(npc, {})
        agh = aghs_by_id.get(raw["id"], {})
        out.append(
            {
                "id": raw["id"],
                "key": hero_key(npc),
                "npc": npc,
                "name": raw["localized_name"],
                "primary_attr": raw.get("primary_attr"),
                "attack_type": raw.get("attack_type"),
                "roles": raw.get("roles", []),
                "img": _img(raw.get("img")),
                "icon": _img(raw.get("icon")),
                "stats": {f: raw.get(f) for f in BASE_STAT_FIELDS},
                "abilities": [a for a in _flat(abil.get("abilities", [])) if a != "generic_hidden"],
                "talents": [{"key": t["name"], "level": t["level"]} for t in abil.get("talents", [])],
                "scepter": {"skill": agh.get("scepter_skill_name"), "desc": agh.get("scepter_desc")}
                if agh.get("has_scepter")
                else None,
                "shard": {"skill": agh.get("shard_skill_name"), "desc": agh.get("shard_desc")}
                if agh.get("has_shard")
                else None,
            }
        )
    return out


ABILITY_FIELDS = (
    "dname",
    "desc",
    "behavior",
    "dmg_type",
    "bkbpierce",
    "dispellable",
    "target_team",
    "target_type",
    "cd",
    "mc",
)


def abilities_doc(abilities: Mapping[str, Any], heroes: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    wanted: set[str] = set()
    for h in heroes:
        wanted.update(h["abilities"])
        wanted.update(t["key"] for t in h["talents"])
    out: dict[str, Any] = {}
    for key in sorted(wanted):
        raw = abilities.get(key)
        if not raw:
            continue
        entry = {f: raw[f] for f in ABILITY_FIELDS if raw.get(f) not in (None, "", [])}
        entry["img"] = _img(raw.get("img"))
        attrib = [
            {"header": a.get("header"), "key": a.get("key"), "value": a.get("value")}
            for a in raw.get("attrib", []) or []
            if not a.get("generated")
        ]
        if attrib:
            entry["attrib"] = attrib
        out[key] = entry
    return out


ITEM_FIELDS = ("id", "dname", "cost", "qual", "tier", "cd", "mc", "notes", "behavior", "created")


def items_doc(items: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, raw in sorted(items.items()):
        if not raw.get("dname") or key.startswith("recipe_"):
            continue
        entry = {f: raw[f] for f in ITEM_FIELDS if raw.get(f) not in (None, "", [])}
        entry["components"] = [c for c in raw.get("components") or [] if c]
        entry["img"] = _img(raw.get("img"))
        entry["abilities"] = [
            {"type": a.get("type"), "title": a.get("title"), "description": a.get("description")}
            for a in raw.get("abilities") or []
        ]
        entry["attrib"] = [
            a["display"].replace("{value}", str(a.get("value")))
            for a in raw.get("attrib") or []
            if a.get("display")
        ]
        out[key] = entry
    return out


def item_id_to_key(item_ids: Mapping[str, str]) -> dict[int, str]:
    return {int(k): v for k, v in item_ids.items()}


# ── /heroStats ─────────────────────────────────────────────────────


def hero_stats_doc(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for r in rows:
        brackets = {str(b): [int(r.get(f"{b}_pick") or 0), int(r.get(f"{b}_win") or 0)] for b in range(1, 9)}
        out[str(r["id"])] = {
            "brackets": brackets,
            "pub": [int(r.get("pub_pick") or 0), int(r.get("pub_win") or 0)],
            "turbo": [int(r.get("turbo_picks") or 0), int(r.get("turbo_wins") or 0)],
            "pro": [int(r.get("pro_pick") or 0), int(r.get("pro_win") or 0), int(r.get("pro_ban") or 0)],
        }
    return out


# ── per-hero endpoints ─────────────────────────────────────────────


def item_popularity_doc(raw: Mapping[str, Any], id_to_key: Mapping[int, str]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for src, phase in PHASES.items():
        counts = {id_to_key.get(int(i), f"item_{i}"): int(n) for i, n in (raw.get(src) or {}).items()}
        out[phase] = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    return out


def benchmarks_doc(raw: Mapping[str, Any]) -> dict[str, list[list[float]]]:
    result = raw.get("result") or {}
    return {
        metric: [[float(p["percentile"]), float(p["value"])] for p in points]
        for metric, points in result.items()
        if isinstance(points, list)
    }


def item_timings_doc(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[list[int]]]:
    out: dict[str, list[list[int]]] = defaultdict(list)
    for r in rows:
        out[str(r["item"])].append([int(r["time"]), int(r["games"]), int(r["wins"])])
    return {k: sorted(v) for k, v in sorted(out.items())}


def lane_roles_doc(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[int]]:
    """Games and wins per lane role (1 safe, 2 mid, 3 off, 4 jungle), summed over game lengths."""
    out: dict[str, list[int]] = {}
    for r in rows:
        acc = out.setdefault(str(r["lane_role"]), [0, 0])
        acc[0] += int(r["games"])
        acc[1] += int(r["wins"])
    return dict(sorted(out.items()))


# ── pro build corpus (/explorer) ───────────────────────────────────


def assign_positions(team: Sequence[Mapping[str, Any]]) -> dict[int, int]:
    """Position 1-5 per hero for one team of a parsed match.

    Our heuristic: the three highest-GPM players are cores, the other two supports. A mid-lane core is
    position 2, a safe-lane core 1, an off-lane core 3; then any core left takes the free core slot in
    GPM order. Supports: off lane 4, safe lane 5, then the free slot. Returns {hero_id: position}.
    """
    ranked = sorted(team, key=lambda p: -(p.get("gold_per_min") or 0))
    cores, supports = ranked[:3], ranked[3:5]
    out: dict[int, int] = {}

    def place(group: Sequence[Mapping[str, Any]], by_lane: Mapping[int, int], slots: list[int]) -> None:
        free = list(slots)
        rest = []
        for p in group:
            pos = by_lane.get(int(p.get("lane_role") or 0))
            if pos in free:
                out[int(p["hero_id"])] = pos
                free.remove(pos)
            else:
                rest.append(p)
        for p, pos in zip(rest, free, strict=False):
            out[int(p["hero_id"])] = pos

    place(cores, {2: 2, 1: 1, 3: 3}, [1, 2, 3])
    place(supports, {3: 4, 1: 5}, [4, 5])
    return out


def positions_doc(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    teams: dict[tuple[int, bool], list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        teams[(int(r["match_id"]), int(r["player_slot"]) < 128)].append(r)
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for team in teams.values():
        if len(team) != 5:
            continue
        for hero, pos in assign_positions(team).items():
            counts[str(hero)][str(pos)] += 1
    return {h: dict(sorted(c.items())) for h, c in sorted(counts.items(), key=lambda kv: int(kv[0]))}


def _won(row: Mapping[str, Any]) -> bool:
    radiant = int(row["player_slot"]) < 128
    return bool(row["radiant_win"]) == radiant


def skill_doc(
    rows: Sequence[Mapping[str, Any]],
    ability_ids: Mapping[str, str],
    hero_abilities: Sequence[str],
    talents: Sequence[Mapping[str, Any]],
    order_length: int = 10,
) -> dict[str, Any]:
    """Skill build stats for one hero from its pro rows."""
    talent_level = {t["key"]: int(t["level"]) for t in talents}
    abil_set = set(hero_abilities)
    by_level: list[Counter[str]] = []
    orders: Counter[tuple[str, ...]] = Counter()
    order_wins: Counter[tuple[str, ...]] = Counter()
    talent_picks: Counter[str] = Counter()
    tier_rows: Counter[int] = Counter()
    for r in rows:
        keys = [ability_ids.get(str(a), f"ability_{a}") for a in r.get("ability_upgrades_arr") or []]
        skills = [k for k in keys if k in abil_set]
        for i, k in enumerate(skills):
            if i >= len(by_level):
                by_level.append(Counter())
            by_level[i][k] += 1
        if len(skills) >= order_length:
            prefix = tuple(skills[:order_length])
            orders[prefix] += 1
            order_wins[prefix] += int(_won(r))
        tiers_seen: set[int] = set()
        for k in keys:
            if k in talent_level:
                talent_picks[k] += 1
                tiers_seen.add(talent_level[k])
        for t in tiers_seen:
            tier_rows[t] += 1
    return {
        "by_level": [
            {
                "pick": i + 1,
                "ability": c.most_common(1)[0][0],
                "share": round(c.most_common(1)[0][1] / sum(c.values()), 3),
                "n": sum(c.values()),
            }
            for i, c in enumerate(by_level)
        ],
        "orders": [{"order": list(o), "n": n, "wins": order_wins[o]} for o, n in orders.most_common(5)],
        "talents": {
            key: {
                "level": lvl,
                "n": talent_picks[key],
                "share": round(talent_picks[key] / tier_rows[lvl], 3) if tier_rows[lvl] else None,
            }
            for key, lvl in talent_level.items()
        },
    }


def items_from_purchases(
    rows: Sequence[Mapping[str, Any]], items: Mapping[str, Any], min_share: float = 0.12
) -> dict[str, Any]:
    """Starting items, the build order (median first-purchase times) and item win rates."""
    starts: Counter[tuple[str, ...]] = Counter()
    first_time: dict[str, list[int]] = defaultdict(list)
    wins: Counter[str] = Counter()
    n = 0
    for r in rows:
        log = r.get("purchase_log") or []
        if not log:
            continue
        n += 1
        won = _won(r)
        start = tuple(sorted(p["key"] for p in log if int(p.get("time", 0)) <= 0))
        if start:
            starts[start] += 1
        seen: dict[str, int] = {}
        for p in log:
            key, t = p.get("key"), int(p.get("time", 0))
            if not key or t <= 0 or key in seen or key in CONSUMABLES:
                continue
            info = items.get(key)
            if not info:
                continue
            if not (info.get("components") or int(info.get("cost") or 0) >= 1000):
                continue
            seen[key] = t
        for key, t in seen.items():
            first_time[key].append(t)
            wins[key] += int(won)
    order: list[dict[str, Any]] = [
        {
            "item": key,
            "share": round(len(ts) / n, 3),
            "median_time": int(statistics.median(ts)),
            "n": len(ts),
            "wins": wins[key],
        }
        for key, ts in first_time.items()
        if n and len(ts) / n >= min_share
    ]
    order.sort(key=lambda x: (x["median_time"], x["item"]))
    # Drop parts that most buyers finish into a later item of the same build (Broadsword -> Battle Fury).
    by_key = {o["item"]: o for o in order}
    finished_into: dict[str, str] = {}
    for o in order:
        for comp in items.get(o["item"], {}).get("components") or []:
            part = by_key.get(comp)
            if part and o["share"] >= 0.8 * part["share"] and o["median_time"] > part["median_time"]:
                finished_into[comp] = o["item"]
    order = [o for o in order if o["item"] not in finished_into]
    # Basic parts (no recipe of their own) that build into something are not build items either;
    # in pro logs they are mostly bought just before the game ends. Blink Dagger is the exception.
    parents = {c for info in items.values() for c in (info.get("components") or [])}
    order = [
        o
        for o in order
        if o["item"] in KEEP_BASIC or items.get(o["item"], {}).get("components") or o["item"] not in parents
    ]
    timings = {key: int(statistics.median(ts)) for key, ts in first_time.items() if len(ts) >= 5}
    return {
        "rows": n,
        "starting": [{"items": list(s), "n": c} for s, c in starts.most_common(3)],
        "order": order,
        "median_timings": dict(sorted(timings.items())),
    }
