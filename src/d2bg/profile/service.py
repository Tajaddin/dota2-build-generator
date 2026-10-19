"""Player profile from OpenDota's public player endpoints (the profile must expose match data)."""

from __future__ import annotations

from typing import Any

from d2bg.context import AppContext
from d2bg.knowledge.similar import similar_heroes
from d2bg.profile import analytics

MATCH_FIELDS = (
    "hero_id",
    "start_time",
    "duration",
    "kills",
    "deaths",
    "assists",
    "player_slot",
    "radiant_win",
    "game_mode",
    "lobby_type",
    "lane_role",
    "party_size",
)
HOUR = 3600.0


def fetch_matches(ctx: AppContext, account_id: int, limit: int = 300) -> list[dict[str, Any]]:
    params: dict[str, str | int | float | bool | list[str]] = {
        "limit": limit,
        "significant": 1,
        "project": list(MATCH_FIELDS),
    }
    rows = ctx.client.get(f"players/{account_id}/matches", params, ttl=0.25 * HOUR)
    return list(rows or [])


def profile(ctx: AppContext, account_id: int, limit: int = 300) -> dict[str, Any]:
    client = ctx.client
    player = client.get(f"players/{account_id}", ttl=HOUR) or {}
    matches = fetch_matches(ctx, account_id, limit)
    ranked = [m for m in matches if m.get("lobby_type") == 7]
    pool = analytics.hero_pool(matches)
    names = ctx.data.heroes
    top = [r["hero"] for r in pool if r["games"] >= 5][:5]
    suggestions = similar_heroes(ctx.data.matchup_bucket("all"), top, exclude={r["hero"] for r in pool}, n=6)
    prof = player.get("profile") or {}
    return {
        "account_id": account_id,
        "name": prof.get("personaname"),
        "avatar": prof.get("avatarfull") or prof.get("avatarmedium"),
        "profile_url": prof.get("profileurl"),
        "rank": analytics.rank_name(player.get("rank_tier"), player.get("leaderboard_rank")),
        "rank_tier": player.get("rank_tier"),
        "summary": analytics.summary(matches),
        "ranked_summary": analytics.summary(ranked),
        "streaks": analytics.streaks(matches),
        "sessions": analytics.sessions(matches)[:10],
        "by_hour": analytics.by_hour(matches),
        "hero_pool": [{**r, "name": names.name(r["hero"])} for r in pool[:40]],
        "comfort": [r["hero"] for r in pool if r["games"] >= 10 and r["wilson_lower"] >= 0.45][:8],
        "worth_adding": [
            {"hero": h, "name": names.name(h), "similar_to": [names.name(s) for s in sim]}
            for h, sim in suggestions
        ],
        "trend": analytics.rolling_win_rate(matches),
        "lanes": analytics.lane_roles(matches),
        "recent": [
            {**m, "won": analytics.won(m), "hero_name": names.name(int(m.get("hero_id") or 0))}
            for m in matches[:30]
        ],
        "matches_considered": len(matches),
        "public": bool(matches) or bool(prof),
    }


def peers(ctx: AppContext, account_id: int) -> list[dict[str, Any]]:
    rows = ctx.client.get(f"players/{account_id}/peers", {"significant": 1}, ttl=6 * HOUR) or []
    out = []
    for r in rows[:40]:
        games = int(r.get("with_games") or 0)
        wins = int(r.get("with_win") or 0)
        out.append(
            {
                "account_id": r.get("account_id"),
                "name": r.get("personaname"),
                "avatar": r.get("avatar"),
                "with_games": games,
                "with_wins": wins,
                "with_win_rate": round(wins / games, 3) if games else None,
                "against_games": r.get("against_games"),
                "last_played": r.get("last_played"),
            }
        )
    return out


def search_players(ctx: AppContext, query: str) -> list[dict[str, Any]]:
    if query.strip().isdigit():
        return [{"account_id": int(query.strip()), "name": None}]
    rows = ctx.client.get("search", {"q": query.strip()}, ttl=HOUR) or []
    return [
        {
            "account_id": r.get("account_id"),
            "name": r.get("personaname"),
            "avatar": r.get("avatarfull"),
            "last_match_time": r.get("last_match_time"),
        }
        for r in rows[:20]
    ]
