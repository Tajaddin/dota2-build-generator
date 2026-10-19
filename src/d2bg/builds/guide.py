"""A hero's build: skills, talents, starting items, build order with pro timings, and phase popularity."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from d2bg.context import AppContext
from d2bg.knowledge.heroes import Hero
from d2bg.knowledge.items import ItemIndex
from d2bg.knowledge.timers import fmt

TALENT_LEVELS = {1: 10, 2: 15, 3: 20, 4: 25}
MIN_ROWS = 20  # fewer pro games than this: say so next to the build


def _item(items: ItemIndex, key: str) -> dict[str, Any]:
    item = items.get(key)
    return {
        "key": key,
        "name": items.name(key),
        "img": item.img if item else None,
        "cost": item.cost if item else None,
    }


def skill_section(hero: Hero, pro: Mapping[str, Any] | None) -> dict[str, Any]:
    abilities = {a.key: a for a in hero.abilities}
    if not pro:
        return {"by_level": [], "orders": [], "talents": [], "rows": 0}
    skills = pro["skills"]

    def ab(key: str) -> dict[str, Any]:
        a = abilities.get(key)
        return {"key": key, "name": a.name if a else key, "img": a.img if a else None}

    talents = []
    for t in hero.talents:
        stat = skills["talents"].get(t.key, {})
        talents.append(
            {
                "key": t.key,
                "name": t.name,
                "tier": t.level,
                "level": TALENT_LEVELS.get(t.level),
                "share": stat.get("share"),
                "n": stat.get("n", 0),
            }
        )
    talents.sort(key=lambda t: (-(t["level"] or 0), -(t["share"] or 0)))
    return {
        "rows": pro["n"],
        "by_level": [
            {**ab(row["ability"]), "pick": row["pick"], "share": row["share"], "n": row["n"]}
            for row in skills["by_level"]
        ],
        "orders": [
            {
                "order": [ab(k) for k in o["order"]],
                "n": o["n"],
                "win_rate": round(o["wins"] / o["n"], 3) if o["n"] else None,
            }
            for o in skills["orders"]
        ],
        "talents": talents,
    }


def item_section(
    items: ItemIndex,
    pro: Mapping[str, Any] | None,
    popularity: Mapping[str, Mapping[str, int]] | None,
    timings: Mapping[str, Sequence[Sequence[int]]] | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"starting": [], "order": [], "phases": {}, "timing_win_rates": {}}
    if pro:
        p = pro["items"]
        out["starting"] = [
            {"items": [_item(items, k) for k in s["items"]], "n": s["n"]} for s in p["starting"]
        ]
        out["order"] = [
            {
                **_item(items, o["item"]),
                "share": o["share"],
                "median_time": o["median_time"],
                "median": fmt(o["median_time"]),
                "n": o["n"],
                "win_rate": round(o["wins"] / o["n"], 3) if o["n"] else None,
            }
            for o in p["order"]
        ]
        out["rows"] = p["rows"]
    for phase, counts in (popularity or {}).items():
        total = sum(counts.values()) or 1
        out["phases"][phase] = [
            {**_item(items, k), "count": n, "share": round(n / total, 3)}
            for k, n in list(counts.items())[:10]
            if k in items
        ]
    for key, rows in (timings or {}).items():
        if key not in items:
            continue
        games = sum(r[1] for r in rows)
        if games < 30:
            continue
        out["timing_win_rates"][key] = {
            **_item(items, key),
            "games": games,
            "buckets": [
                {
                    "until": r[0],
                    "label": f"<{fmt(r[0])}",
                    "games": r[1],
                    "win_rate": round(r[2] / r[1], 3) if r[1] else None,
                }
                for r in rows
            ],
        }
    return out


def hero_build(ctx: AppContext, hero_id: int) -> dict[str, Any]:
    data = ctx.data
    hero = data.heroes.require(hero_id)
    pro = data.per_hero("pro_builds.json", hero.id)
    pro_doc = data.load("pro_builds.json") or {}
    skills = skill_section(hero, pro)
    items = item_section(
        data.items,
        pro,
        data.per_hero("item_popularity.json", hero.id),
        data.per_hero("item_timings.json", hero.id),
    )
    notes = []
    if not pro or pro["n"] < MIN_ROWS:
        notes.append(
            f"Only {pro['n'] if pro else 0} pro games on this hero since the patch; "
            "the skill and item order may not be representative."
        )
    return {
        "hero": hero.summary(),
        "positions": ctx.positions.get(hero.id),
        "skills": skills,
        "items": items,
        "pro": {
            "games": pro["n"] if pro else 0,
            "win_rate": round(pro["wins"] / pro["n"], 3) if pro and pro["n"] else None,
            "since": pro_doc.get("since"),
            "matches": pro_doc.get("matches"),
        },
        "notes": notes,
    }


def build_order(ctx: AppContext, hero_id: int) -> list[dict[str, Any]]:
    """The item order to follow: pro first-purchase order, else the popularity of finished items by phase."""
    pro = ctx.data.per_hero("pro_builds.json", hero_id) or {}
    order = [
        {"key": o["item"], "median_time": o["median_time"]} for o in (pro.get("items") or {}).get("order", [])
    ]
    if order:
        return order
    items = ctx.data.items
    out: list[dict[str, Any]] = []
    for phase in ("early", "mid", "late"):
        counts = (ctx.data.per_hero("item_popularity.json", hero_id) or {}).get(phase, {})
        for key in counts:
            item = items.get(key)
            if item and (item.components or item.cost >= 1000) and key not in {o["key"] for o in out}:
                out.append({"key": key, "median_time": None})
            if sum(1 for o in out if o["key"] in counts) >= 3:
                break
    return out


def is_boots_upgrade(key: str, items: ItemIndex) -> bool:
    """Boots built from Boots of Speed: Phase, Treads, Arcane, Tranquil, Travel..."""
    item = items.get(key)
    return item is not None and "boots" in item.components


def next_items(
    order: Iterable[Mapping[str, Any]], owned: Iterable[str], items: ItemIndex, n: int = 3
) -> list[dict[str, Any]]:
    """The next items in the build that he does not own yet, with gold still needed for each."""
    have = list(owned)
    have_set = set(have)
    owns_boots = any(is_boots_upgrade(h, items) for h in have_set)
    out = []
    for o in order:
        key = o["key"] if "key" in o else o["item"]
        if key in have_set:
            continue
        # Skip an item already folded into something he owns (e.g. Yasha once Manta is built).
        if any(key in (items.get(h).components if items.get(h) else ()) for h in have_set):  # type: ignore[union-attr]
            continue
        # One pair of boots: once he has Phase Boots, Power Treads is an alternative, not a next item.
        if owns_boots and is_boots_upgrade(key, items) and not key.startswith("travel_boots"):
            continue
        out.append(items.owned_progress(key, have))
        if len(out) >= n:
            break
    return out


def build_text(build: Mapping[str, Any]) -> str:
    """Plain text to paste into chat or notes."""
    lines = [f"{build['hero']['name']} build (pro games: {build['pro']['games']})"]
    if build["items"]["starting"]:
        lines.append("Start: " + ", ".join(i["name"] for i in build["items"]["starting"][0]["items"]))
    if build["items"]["order"]:
        lines.append("Items: " + " > ".join(f"{i['name']} ({i['median']})" for i in build["items"]["order"]))
    if build["skills"]["orders"]:
        lines.append("Skills: " + " ".join(a["name"] for a in build["skills"]["orders"][0]["order"]))
    picks: dict[int, Mapping[str, Any]] = {}
    for t in build["skills"]["talents"]:
        if t["share"] is not None and (t["level"] not in picks or t["share"] > picks[t["level"]]["share"]):
            picks[t["level"]] = t
    if picks:
        lines.append("Talents: " + "; ".join(f"{lvl}: {t['name']}" for lvl, t in sorted(picks.items())))
    return "\n".join(lines)
