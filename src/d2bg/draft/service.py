"""One call that answers everything the draft page shows."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from d2bg.context import AppContext
from d2bg.draft import advisor
from d2bg.draft.composition import team_report
from d2bg.draft.lanes import assign_positions, lane_matchups, lanes_from_positions
from d2bg.knowledge.counters import situational_items
from d2bg.settings import PoolMode, RankBucket, Settings

SMALL_SAMPLE = 3000


class DraftRequest(BaseModel):
    allies: list[int] = Field(default_factory=list, max_length=5)
    enemies: list[int] = Field(default_factory=list, max_length=5)
    bans: list[int] = Field(default_factory=list, max_length=24)
    side: Literal["radiant", "dire"] | None = None
    my_position: int | None = Field(default=None, ge=1, le=5)
    rank_bucket: RankBucket | None = None
    synergy_weight: float | None = Field(default=None, ge=0, le=1)
    pool_mode: PoolMode | None = None
    hero_pool: list[int] | None = None
    blacklist: list[int] | None = None
    whitelist: list[int] | None = None
    compare: list[int] = Field(default_factory=list, max_length=3)
    n: int = Field(default=12, ge=1, le=40)


def _resolve(req: DraftRequest, s: Settings) -> dict[str, Any]:
    pool = req.hero_pool if req.hero_pool is not None else s.hero_pool
    mode = req.pool_mode or s.pool_mode
    whitelist = list(req.whitelist if req.whitelist is not None else s.whitelist)
    if mode == "only" and pool:
        whitelist = sorted(set(whitelist) & set(pool)) if whitelist else list(pool)
    return {
        "bucket": req.rank_bucket or s.rank_bucket,
        "w": req.synergy_weight if req.synergy_weight is not None else s.synergy_weight,
        "pool": pool if mode == "boost" else [],
        "pool_bonus": advisor.POOL_BONUS if mode == "boost" else 0.0,
        "blacklist": req.blacklist if req.blacklist is not None else s.blacklist,
        "whitelist": whitelist,
        "pool_mode": mode,
    }


def analyze(ctx: AppContext, req: DraftRequest, settings: Settings) -> dict[str, Any]:
    data, heroes = ctx.data, ctx.data.heroes
    opts = _resolve(req, settings)
    bucket = data.matchup_bucket(opts["bucket"])
    roles = {str(h): {str(p) for p in ps} for h, ps in ctx.playable.items()}
    allies, enemies = list(req.allies), list(req.enemies)
    taken = set(allies) | set(enemies) | set(req.bans)

    def card(hero_id: int, value: float) -> dict[str, Any]:
        return {
            "hero": hero_id,
            "score": round(value, 3),
            "positions": sorted(ctx.playable.get(hero_id, set())),
            "counterability": round(advisor.counterability(hero_id, bucket), 2),
            "why": advisor.explain(hero_id, bucket, enemies, allies),
        }

    common = {
        "bans": req.bans,
        "blacklist": opts["blacklist"],
        "whitelist": opts["whitelist"],
        "w": opts["w"],
        "hero_roles": roles,
        "pool": opts["pool"],
        "pool_bonus": opts["pool_bonus"],
    }
    overall = advisor.suggest(bucket, enemies, allies, n=req.n, **common)
    by_position = {
        str(p): [card(h, v) for h, v in advisor.suggest(bucket, enemies, allies, role=str(p), n=8, **common)]
        for p in range(1, 6)
    }

    win = None
    if ctx.win_model and (allies or enemies):
        as_radiant = ctx.win_model.predict(allies, enemies, bucket)
        as_dire = ctx.win_model.predict(enemies, allies, bucket)
        if req.side == "radiant":
            us = as_radiant["radiant"]
        elif req.side == "dire":
            us = as_dire["dire"]
        else:
            us = round((as_radiant["radiant"] + as_dire["dire"]) / 2, 4)
        detail = as_radiant if req.side != "dire" else as_dire
        win = {
            "us": us,
            "them": round(1 - us, 4),
            "side": req.side,
            "detail": detail,
            "held_out_accuracy": detail["held_out_accuracy"],
        }

    shares = {h: info["shares"] for h, info in ctx.positions.items()}
    our_pos = assign_positions(allies, shares)
    their_pos = assign_positions(enemies, shares)

    sample = int(bucket.get("n_matches", 0))
    notes = []
    if sample < SMALL_SAMPLE:
        notes.append(f"Only {sample} matches in this rank bracket; numbers are noisy.")

    return {
        "bucket": opts["bucket"],
        "sample_matches": sample,
        "source_week": data.load("matchups.json")["source_week"],
        "pool_mode": opts["pool_mode"],
        "suggestions": [card(h, v) for h, v in overall],
        "by_position": by_position,
        "counters": {
            str(e): [{"hero": c, "edge": round(a, 2)} for c, a in advisor.counters(e, bucket, 10, taken)]
            for e in enemies
        },
        "hot_counters": advisor.hot_counters(enemies, bucket, 10, taken),
        "bans": advisor.ban_suggestions(bucket, allies, enemies, req.bans, n=10),
        "meta": [{"hero": h, "wr": round(wr, 4)} for h, wr in advisor.meta(bucket, 12, exclude=taken)],
        "win": win,
        "ours": team_report([heroes.require(h) for h in allies], ctx.traits, ctx.playable),
        "theirs": team_report([heroes.require(h) for h in enemies], ctx.traits, ctx.playable),
        "positions": {"ours": our_pos, "theirs": their_pos},
        "lanes": lane_matchups(lanes_from_positions(our_pos), lanes_from_positions(their_pos), bucket)
        if allies and enemies
        else [],
        "items": situational_items(enemies, ctx.traits, ctx.counter_rules, data.items, heroes.name),
        "compare": [
            card(h, advisor.score(h, bucket, enemies, allies, opts["w"], roles))
            for h in req.compare
            if heroes.get(h)
        ],
        "notes": notes,
    }
