"""Heroes, items, meta, builds and the draft."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from d2bg.api.services import Services, services
from d2bg.builds.guide import build_text, hero_build
from d2bg.draft import advisor
from d2bg.draft.service import DraftRequest, analyze
from d2bg.knowledge.counters import situational_items
from d2bg.knowledge.heroes import Hero
from d2bg.knowledge.similar import most_similar
from d2bg.settings import RankBucket

router = APIRouter(prefix="/api")
Svc = Annotated[Services, Depends(services)]


def _hero(svc: Services, ref: str) -> Hero:
    hero = svc.ctx.data.heroes.get(ref) or next(iter(svc.ctx.data.heroes.search(ref, 1)), None)
    if hero is None:
        raise HTTPException(404, f"No hero matches {ref!r}")
    return hero


def _meta_row(svc: Services, hero_id: int) -> dict[str, Any]:
    stats = (svc.ctx.data.load("hero_stats.json") or {}).get(str(hero_id), {})
    return stats if isinstance(stats, dict) else {}


@router.get("/heroes")
def heroes(svc: Svc) -> list[dict[str, Any]]:
    ctx = svc.ctx
    bucket = ctx.data.matchup_bucket("all")["heroes"]
    out = []
    for h in ctx.data.heroes:
        b = bucket.get(str(h.id), {})
        out.append(
            {
                **h.summary(),
                "traits": [t["trait"] for t in ctx.traits.view(h.id)],
                "positions": sorted(ctx.playable.get(h.id, set())),
                "win_rate": b.get("wr"),
                "pick_rate": b.get("pick_rate"),
            }
        )
    return out


@router.get("/heroes/search")
def search(svc: Svc, q: str, limit: int = 10) -> list[dict[str, Any]]:
    return [h.summary() for h in svc.ctx.data.heroes.search(q, limit)]


class ParseRequest(BaseModel):
    text: str


@router.post("/heroes/parse")
def parse_list(svc: Svc, body: ParseRequest) -> dict[str, Any]:
    found, unknown = svc.ctx.data.heroes.parse_list(body.text)
    return {"heroes": [h.summary() for h in found], "unknown": unknown}


@router.get("/heroes/{ref}")
def hero_detail(svc: Svc, ref: str, bucket: RankBucket | None = None) -> dict[str, Any]:
    ctx = svc.ctx
    hero = _hero(svc, ref)
    b = ctx.data.matchup_bucket(bucket or ctx.settings.get().rank_bucket)
    vs = [(int(o), float(v)) for o, v in b["vs"].get(str(hero.id), {}).items() if v is not None]
    with_ = [(int(o), float(v)) for o, v in b["with"].get(str(hero.id), {}).items() if v is not None]
    vs.sort(key=lambda t: -t[1])
    with_.sort(key=lambda t: -t[1])
    return {
        **hero.summary(),
        "stats": dict(hero.stats),
        "abilities": [
            {
                "key": a.key,
                "name": a.name,
                "desc": a.desc,
                "img": a.img,
                "cooldown": a.cooldown,
                "mana": a.mana,
                "behavior": list(a.behavior),
                "dmg_type": a.dmg_type,
                "bkb_pierce": a.bkb_pierce,
                "hidden": "Hidden" in a.behavior,
                "attrib": [{"header": h, "value": v} for h, _, v in a.attrib if h],
            }
            for a in hero.abilities
        ],
        "talents": [{"key": t.key, "name": t.name, "tier": t.level} for t in hero.talents],
        "scepter": hero.scepter,
        "shard": hero.shard,
        "traits": ctx.traits.view(hero.id),
        "positions": ctx.positions.get(hero.id),
        "bucket": bucket or ctx.settings.get().rank_bucket,
        "bucket_stats": b["heroes"].get(str(hero.id)),
        "best_against": [{"hero": o, "value": round(v, 2)} for o, v in vs[:8]],
        "worst_against": [{"hero": o, "value": round(v, 2)} for o, v in reversed(vs[-8:])],
        "best_with": [{"hero": o, "value": round(v, 2)} for o, v in with_[:8]],
        "countered_by": [{"hero": c, "edge": round(e, 2)} for c, e in advisor.counters(hero.id, b, 8)],
        "counterability": round(advisor.counterability(hero.id, b), 2),
        "similar": [
            {"hero": h, "similarity": s} for h, s in most_similar(ctx.data.matchup_bucket("all"), hero.id)
        ],
        "benchmarks": ctx.data.per_hero("benchmarks.json", hero.id),
        "lane_roles": ctx.data.per_hero("lane_roles.json", hero.id),
        "meta": _meta_row(svc, hero.id),
    }


@router.get("/heroes/{ref}/build")
def build(svc: Svc, ref: str) -> dict[str, Any]:
    return hero_build(svc.ctx, _hero(svc, ref).id)


@router.get("/heroes/{ref}/build.txt", response_class=PlainTextResponse)
def build_txt(svc: Svc, ref: str) -> str:
    return build_text(hero_build(svc.ctx, _hero(svc, ref).id))


@router.get("/items")
def items(svc: Svc) -> list[dict[str, Any]]:
    # Every item, free ones included (Observer Wards cost 0); the Items page filters for the shop.
    return [{**i.summary(), "builds_into": svc.ctx.data.items.builds_into(i.key)} for i in svc.ctx.data.items]


@router.get("/items/{key}")
def item_detail(svc: Svc, key: str) -> dict[str, Any]:
    items = svc.ctx.data.items
    item = items.get(key)
    if item is None:
        raise HTTPException(404, f"No item {key!r}")
    buyers = []
    pro = svc.ctx.data.load("pro_builds.json") or {"heroes": {}}
    for hero_id, doc in pro["heroes"].items():
        for o in doc["items"]["order"]:
            if o["item"] == item.key:
                buyers.append({"hero": int(hero_id), "share": o["share"], "median_time": o["median_time"]})
    buyers.sort(key=lambda b: -b["share"])
    return {
        **item.summary(),
        "quality": item.quality,
        "abilities": list(item.abilities),
        "attrib": list(item.attrib),
        "cooldown": item.cooldown,
        "notes": item.notes,
        "recipe_cost": items.recipe_cost(item.key),
        "components_detail": [items.get(c).summary() for c in item.components if items.get(c)],  # type: ignore[union-attr]
        "builds_into": [items.get(k).summary() for k in items.builds_into(item.key) if items.get(k)],  # type: ignore[union-attr]
        "bought_by": buyers[:20],
    }


@router.get("/meta")
def meta(
    svc: Svc,
    source: Literal["bracket", "pro", "turbo", "matrix"] = "bracket",
    bracket: Annotated[int | None, Query(ge=1, le=8)] = None,
    position: int | None = None,
    min_share: float = 0.005,
) -> dict[str, Any]:
    """Tier list rows. ``bracket`` uses /heroStats picks and wins for one medal (or all of 1-8)."""
    ctx = svc.ctx
    stats = ctx.data.load("hero_stats.json") or {}
    rows = []
    for h in ctx.data.heroes:
        st = stats.get(str(h.id), {})
        if source == "pro":
            picks, wins = st.get("pro", [0, 0, 0])[:2]
            bans = st.get("pro", [0, 0, 0])[2]
        elif source == "turbo":
            picks, wins = st.get("turbo", [0, 0])
            bans = None
        elif source == "matrix":
            b = ctx.data.matchup_bucket(ctx.settings.get().rank_bucket)["heroes"].get(str(h.id), {})
            picks, wins, bans = b.get("games", 0), b.get("wins", 0), None
        else:
            keys = [str(bracket)] if bracket else [str(i) for i in range(1, 9)]
            picks = sum(st.get("brackets", {}).get(k, [0, 0])[0] for k in keys)
            wins = sum(st.get("brackets", {}).get(k, [0, 0])[1] for k in keys)
            bans = None
        if position and position not in ctx.playable.get(h.id, set()):
            continue
        rows.append(
            {
                "hero": h.id,
                "name": h.name,
                "icon": h.icon,
                "picks": picks,
                "wins": wins,
                "bans": bans,
                "win_rate": round(wins / picks, 4) if picks else None,
                "positions": sorted(ctx.playable.get(h.id, set())),
            }
        )
    total = sum(r["picks"] for r in rows) or 1
    for r in rows:
        r["pick_share"] = round(r["picks"] / total, 4)
    rows = [r for r in rows if r["pick_share"] >= min_share and r["win_rate"] is not None]
    rows.sort(key=lambda r: -(r["win_rate"] or 0))
    for i, r in enumerate(rows):
        pct = i / max(len(rows) - 1, 1)
        r["tier"] = (
            "S" if pct < 0.1 else "A" if pct < 0.3 else "B" if pct < 0.6 else "C" if pct < 0.85 else "D"
        )
    manifest = ctx.data.status()["files"].get("hero_stats.json", {})
    return {
        "source": source,
        "bracket": bracket,
        "position": position,
        "rows": rows,
        "generated_at": manifest.get("generated_at"),
        "data_source": manifest.get("source"),
    }


@router.post("/draft")
def draft(svc: Svc, body: DraftRequest) -> dict[str, Any]:
    unknown = [
        h
        for h in [*body.allies, *body.enemies, *body.bans, *body.compare]
        if svc.ctx.data.heroes.get(h) is None
    ]
    if unknown:
        raise HTTPException(422, f"Unknown hero IDs: {unknown}")
    return analyze(svc.ctx, body, svc.ctx.settings.get())


@router.get("/situational")
def situational(svc: Svc, enemies: str, owned: str = "") -> list[dict[str, Any]]:
    ids = [int(e) for e in enemies.split(",") if e.strip().isdigit()]
    return situational_items(
        ids,
        svc.ctx.traits,
        svc.ctx.counter_rules,
        svc.ctx.data.items,
        svc.ctx.data.heroes.name,
        [o for o in owned.split(",") if o],
    )


@router.get("/timers")
def timers(svc: Svc) -> dict[str, Any]:
    return {
        "patch": svc.ctx.timer_patch,
        "rules": [
            {"id": r.id, "label": r.label, "lead": r.lead, "cite": r.cite, "default_on": r.default_on}
            for r in svc.ctx.timer_rules
        ],
    }
