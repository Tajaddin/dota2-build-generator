"""Match review from an OpenDota ``/matches/{id}`` document.

Every note is a comparison against data (benchmarks, pro item timings); nothing is generic advice.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from d2bg.builds.benchmarks import METRICS
from d2bg.context import AppContext
from d2bg.knowledge.timers import fmt
from d2bg.profile.analytics import rank_name

ITEM_SLOTS = ("item_0", "item_1", "item_2", "item_3", "item_4", "item_5")
BACKPACK = ("backpack_0", "backpack_1", "backpack_2")


def is_parsed(match: Mapping[str, Any]) -> bool:
    return bool(match.get("version")) or any(p.get("purchase_log") for p in match.get("players", []))


def _items(ctx: AppContext, p: Mapping[str, Any], slots: tuple[str, ...]) -> list[dict[str, Any]]:
    out = []
    for s in slots:
        item_id = int(p.get(s) or 0)
        if item_id:
            item = ctx.data.items.by_id(item_id)
            out.append(
                {
                    "key": item.key if item else str(item_id),
                    "name": item.name if item else str(item_id),
                    "img": item.img if item else None,
                }
            )
    return out


def _row(ctx: AppContext, p: Mapping[str, Any], duration_min: float) -> dict[str, Any]:
    hero_id = int(p.get("hero_id") or 0)
    hero = ctx.data.heroes.get(hero_id)
    return {
        "account_id": p.get("account_id"),
        "name": p.get("personaname") or p.get("name"),
        "rank": rank_name(p.get("rank_tier")),
        "radiant": int(p.get("player_slot", 0)) < 128,
        "hero": hero_id,
        "hero_name": hero.name if hero else str(hero_id),
        "hero_img": hero.icon if hero else None,
        "level": p.get("level"),
        "kills": p.get("kills"),
        "deaths": p.get("deaths"),
        "assists": p.get("assists"),
        "last_hits": p.get("last_hits"),
        "denies": p.get("denies"),
        "gpm": p.get("gold_per_min"),
        "xpm": p.get("xp_per_min"),
        "net_worth": p.get("net_worth") or p.get("total_gold"),
        "hero_damage": p.get("hero_damage"),
        "tower_damage": p.get("tower_damage"),
        "hero_healing": p.get("hero_healing"),
        "lane_role": p.get("lane_role"),
        "items": _items(ctx, p, ITEM_SLOTS),
        "backpack": _items(ctx, p, BACKPACK),
        "party_id": p.get("party_id"),
        "party_size": p.get("party_size"),
        "lh_10": (p.get("lh_t") or [None] * 11)[10] if len(p.get("lh_t") or []) > 10 else None,
    }


def _my_benchmarks(p: Mapping[str, Any]) -> list[dict[str, Any]]:
    bench = p.get("benchmarks") or {}
    out = []
    for key, label in METRICS.items():
        b = bench.get(key)
        if isinstance(b, Mapping) and b.get("pct") is not None:
            out.append(
                {
                    "metric": key,
                    "label": label,
                    "value": round(float(b.get("raw") or 0), 2),
                    "percentile": round(float(b["pct"]), 3),
                }
            )
    return out


def _item_timings(ctx: AppContext, p: Mapping[str, Any]) -> list[dict[str, Any]]:
    pro = ctx.data.per_hero("pro_builds.json", int(p.get("hero_id") or 0)) or {}
    medians: Mapping[str, int] = (pro.get("items") or {}).get("median_timings", {})
    first: dict[str, int] = {}
    for e in p.get("purchase_log") or []:
        key, t = e.get("key"), e.get("time")
        if key and t is not None and key not in first and key in medians:
            first[key] = int(t)
    out = []
    for key, t in sorted(first.items(), key=lambda kv: kv[1]):
        delta = t - medians[key]
        out.append(
            {
                "item": key,
                "name": ctx.data.items.name(key),
                "you": fmt(t),
                "you_seconds": t,
                "pro_median": fmt(medians[key]),
                "delta_seconds": delta,
                "delta": fmt(delta),
            }
        )
    return out


def review(ctx: AppContext, match: Mapping[str, Any], account_id: int | None) -> dict[str, Any]:
    duration = int(match.get("duration") or 0)
    minutes = max(duration / 60, 1)
    players = match.get("players") or []
    rows = [_row(ctx, p, minutes) for p in players]
    me = next((p for p in players if account_id and p.get("account_id") == account_id), None)
    notes: list[str] = []
    mine: dict[str, Any] | None = None
    if me is not None:
        my_row = _row(ctx, me, minutes)
        won = bool(match.get("radiant_win")) == my_row["radiant"]
        benchmarks = _my_benchmarks(me)
        timings = _item_timings(ctx, me)
        mine = {"row": my_row, "won": won, "benchmarks": benchmarks, "item_timings": timings}
        for b in benchmarks:
            if b["percentile"] <= 0.25:
                notes.append(
                    f"{b['label']} was at the {round(b['percentile'] * 100)}th percentile for "
                    f"{my_row['hero_name']} ({b['value']})."
                )
            elif b["percentile"] >= 0.8:
                notes.append(
                    f"{b['label']} was in the top {100 - round(b['percentile'] * 100)}% "
                    f"for {my_row['hero_name']} ({b['value']})."
                )
        late = [t for t in timings if t["delta_seconds"] >= 180]
        if late:
            worst = max(late, key=lambda t: t["delta_seconds"])
            notes.append(
                f"{worst['name']} came at {worst['you']}, {worst['delta']} after the pro median "
                f"({worst['pro_median']})."
            )
        if my_row["lh_10"] is not None:
            bench = ctx.data.per_hero("benchmarks.json", my_row["hero"]) or {}
            from d2bg.builds.benchmarks import value_at

            lhpm = value_at(0.5, bench.get("last_hits_per_min", []))
            if lhpm:
                notes.append(
                    f"Last hits at 10:00: {my_row['lh_10']} (hero median pace about {round(lhpm * 10)})."
                )
    radiant = [r for r in rows if r["radiant"]]
    dire = [r for r in rows if not r["radiant"]]

    def total(team: list[dict[str, Any]], key: str) -> int:
        return sum(int(r.get(key) or 0) for r in team)

    return {
        "match_id": match.get("match_id"),
        "start_time": match.get("start_time"),
        "duration": duration,
        "duration_text": fmt(duration),
        "radiant_win": match.get("radiant_win"),
        "score": {"radiant": match.get("radiant_score"), "dire": match.get("dire_score")},
        "game_mode": match.get("game_mode"),
        "lobby_type": match.get("lobby_type"),
        "parsed": is_parsed(match),
        "radiant": radiant,
        "dire": dire,
        "totals": {
            side: {
                "kills": total(t, "kills"),
                "net_worth": total(t, "net_worth"),
                "hero_damage": total(t, "hero_damage"),
            }
            for side, t in (("radiant", radiant), ("dire", dire))
        },
        "me": mine,
        "notes": notes,
        "gold_advantage": match.get("radiant_gold_adv") or [],
        "xp_advantage": match.get("radiant_xp_adv") or [],
    }
