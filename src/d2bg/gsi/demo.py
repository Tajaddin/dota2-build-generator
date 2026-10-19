"""A synthetic match, shaped like real GSI payloads, to try the live features without Dota.

Every number in it is made up by a fixed-seed generator; the UI labels the session as a demo. It walks
through hero selection, the horn, laning, a Roshan kill and the end of the game, buying items from the
hero's pro build order and skilling from the pro skill order when that data exists.
"""

from __future__ import annotations

import json
import random
from collections.abc import Sequence
from typing import Any

from d2bg.builds.guide import build_order, next_items
from d2bg.context import AppContext

DEMO_MATCH_ID = "9000000001"
DEMO_ACCOUNT = 1


def _xp_level(xp: float) -> int:
    # Synthetic curve: about level 6 at 6:00, 12 at 15:00, 18 at 28:00, 25 at 45:00.
    level, need, total = 1, 240.0, 0.0
    while level < 30 and xp >= total + need:
        total += need
        need *= 1.085
        level += 1
    return level


def demo_frames(
    ctx: AppContext, hero_ref: str = "juggernaut", minutes: int = 36, step: int = 3, seed: int = 7
) -> list[tuple[float, dict[str, Any]]]:
    rng = random.Random(seed)
    heroes = ctx.data.heroes
    items = ctx.data.items
    hero = heroes.require(hero_ref)
    pool = [h for h in heroes.ids() if h != hero.id]
    rng.shuffle(pool)
    allies, enemies = [hero.id, *pool[:4]], pool[4:9]
    pro = ctx.data.per_hero("pro_builds.json", hero.id) or {}
    order = [o["key"] for o in build_order(ctx, hero.id) if o["key"] in items]
    if not order:
        order = ["power_treads", "bfury", "manta", "skadi", "butterfly"]
    start = (pro.get("items") or {}).get("starting") or [
        {"items": ["tango", "branches", "branches", "quelling_blade"]}
    ]
    skill_order = [row["ability"] for row in (pro.get("skills") or {}).get("by_level", [])]
    abilities = [a.key for a in hero.abilities if "Hidden" not in a.behavior][:6]
    if not skill_order:
        skill_order = [abilities[i % min(3, len(abilities))] for i in range(16)]

    frames: list[tuple[float, dict[str, Any]]] = []
    base = {"provider": {"name": "d2bg demo", "appid": 570, "version": 47}}

    def player(extra: dict[str, Any]) -> dict[str, Any]:
        return {
            "steamid": "0",
            "accountid": str(DEMO_ACCOUNT),
            "name": "Demo player",
            "activity": "playing",
            "team_name": "radiant",
            **extra,
        }

    # Hero selection, shaped like a real player's GSI (checked against his recorded ranked games):
    # the draft block stays empty, bans arrive as chat announcements, and his hero appears once picked.
    bans = pool[9:13]
    ban_events = [
        {
            "game_time": 23,
            "event_type": "generic_event",
            "data": json.dumps(
                {"type": "CHAT_MESSAGE_HERO_BANNED", "value": b, "playerid1": -1, "playerid2": -1}
            ),
        }
        for b in bans
    ]
    t = 0.0
    for k in range(10):
        frames.append(
            (
                t,
                {
                    **base,
                    "map": {
                        "matchid": DEMO_MATCH_ID,
                        "game_state": "DOTA_GAMERULES_STATE_HERO_SELECTION",
                        "clock_time": -120 + 5 * k,
                        "daytime": True,
                    },
                    "player": player({}),
                    "hero": {"id": hero.id, "name": hero.npc} if k >= 5 else {"id": 0},
                    "draft": {},
                    "events": ban_events[: k + 1],
                },
            )
        )
        t += 2.0

    gold, gold_total, xp, lh, dn = 600.0, 0.0, 0.0, 0, 0
    kills = deaths = assists = 0
    owned: list[str] = list(start[0]["items"])
    gold -= sum(items.cost(i) for i in owned)
    skill_levels = dict.fromkeys(abilities, 0)
    events: list[dict[str, Any]] = []
    radiant_score = dire_score = 0
    clock = -90
    while clock <= minutes * 60:
        phase = "DOTA_GAMERULES_STATE_PRE_GAME" if clock < 0 else "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"
        if clock > 0:
            minute = clock / 60
            gpm_now = 260 + 14 * minute + rng.uniform(-40, 40)
            income = gpm_now * step / 60
            gold += income
            gold_total += income
            xp += (300 + 8 * minute) * step / 60
            lh += int(rng.random() < 0.3 + 0.004 * minute)  # about 6 a minute early, rising slowly
            dn += 1 if rng.random() < 0.05 and minute < 12 else 0
            if rng.random() < 0.012:
                kills += 1
                radiant_score += 1
            if rng.random() < 0.006:
                deaths += 1
                dire_score += 1
                gold = max(gold - 150, 0)
            if rng.random() < 0.015:
                assists += 1
                radiant_score += 1
        level = _xp_level(xp)
        spent = sum(skill_levels.values())
        if spent < min(level, len(skill_order)) and rng.random() < 0.7:
            nxt = skill_order[spent]
            if nxt in skill_levels:
                skill_levels[nxt] += 1
        # Buy whatever the build tracker says is next, so the demo follows the same rules as the app.
        while True:
            nxt_items = next_items([{"key": k} for k in order], owned, items, n=1)
            if not nxt_items or nxt_items[0]["remaining"] > gold:
                break
            target = nxt_items[0]["item"]
            gold -= nxt_items[0]["remaining"]
            comps = items.get(target).components if items.get(target) else ()  # type: ignore[union-attr]
            for c in comps:
                if c in owned:
                    owned.remove(c)
            owned.append(target)
            if len(owned) > 9:
                owned.pop(0)
        if clock == 22 * 60:
            events.append(
                {"game_time": clock, "event_type": "roshan_killed", "team": "radiant", "killer_player_id": 0}
            )
            events.append(
                {
                    "game_time": clock + 3,
                    "event_type": "aegis_picked_up",
                    "team": "radiant",
                    "player_id": 0,
                    "snatched": False,
                }
            )
        net_worth = int(gold) + sum(items.cost(i) for i in owned)
        inventory = {
            f"slot{i}": {"name": f"item_{k}", "can_cast": False, "cooldown": 0}
            for i, k in enumerate(owned[:9])
        }
        for i in range(len(owned), 9):
            inventory[f"slot{i}"] = {"name": "empty"}
        game_minutes = max(clock / 60, 1 / 60)
        payload = {
            **base,
            "map": {
                "matchid": DEMO_MATCH_ID,
                "game_time": clock + 90,
                "clock_time": clock,
                "daytime": (max(clock, 0) // 300) % 2 == 0,
                "nightstalker_night": False,
                "radiant_score": radiant_score,
                "dire_score": dire_score,
                "game_state": phase,
                "paused": False,
                "win_team": "none",
            },
            "player": player(
                {
                    "kills": kills,
                    "deaths": deaths,
                    "assists": assists,
                    "last_hits": lh,
                    "denies": dn,
                    "gold": int(gold),
                    "gold_reliable": int(gold * 0.3),
                    "gold_unreliable": int(gold * 0.7),
                    "gpm": int(gold_total / game_minutes) if clock > 0 else 0,
                    "xpm": int(xp / game_minutes) if clock > 0 else 0,
                    "net_worth": net_worth,
                }
            ),
            "hero": {
                "id": hero.id,
                "name": hero.npc,
                "level": level,
                "xp": int(xp),
                "alive": True,
                "respawn_seconds": 0,
                "buyback_cost": 200 + int(net_worth / 13),
                "buyback_cooldown": 0,
                "health": 1000,
                "max_health": 1000,
                "mana": 400,
                "max_mana": 400,
                "aghanims_scepter": False,
                "aghanims_shard": False,
            },
            "abilities": {
                f"ability{i}": {
                    "name": a,
                    "level": skill_levels[a],
                    "can_cast": skill_levels[a] > 0,
                    "passive": False,
                    "ultimate": i == len(abilities) - 1,
                    "cooldown": 0,
                }
                for i, a in enumerate(abilities)
            },
            "items": inventory,
            "events": [e for e in events if e["game_time"] <= clock],
            "draft": {},
            # After loading the minimap shows the allies, and each enemy once "seen" (one a minute here).
            "minimap": {
                **{
                    f"o{i}": {
                        "unitname": heroes.require(h).npc,
                        "team": 2,
                        "image": "minimap_herocircle_self" if h == hero.id else "minimap_herocircle",
                    }
                    for i, h in enumerate(allies)
                },
                **{
                    f"o{10 + i}": {"unitname": heroes.require(h).npc, "team": 3, "image": "minimap_enemyicon"}
                    for i, h in enumerate(enemies)
                    if clock >= 60 * i
                },
            },
        }
        frames.append((t, payload))
        clock += step
        t += 1.0
    end = dict(frames[-1][1])
    end["map"] = {**end["map"], "game_state": "DOTA_GAMERULES_STATE_POST_GAME", "win_team": "radiant"}
    frames.append((t, end))
    return frames


def demo_draft(frames: Sequence[tuple[float, dict[str, Any]]], ctx: AppContext) -> dict[str, list[int]]:
    """The demo's teams, read back from the last minimap (for tests)."""
    ids = {h.key: h.id for h in ctx.data.heroes}
    for _, p in reversed(frames):
        mm = p.get("minimap") or {}
        if mm:
            teams: dict[str, list[int]] = {"radiant": [], "dire": []}
            for obj in mm.values():
                side = "radiant" if obj["team"] == 2 else "dire"
                teams[side].append(ids[obj["unitname"].removeprefix("npc_dota_hero_")])
            return teams
    return {"radiant": [], "dire": []}
