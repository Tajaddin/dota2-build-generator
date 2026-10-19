"""Hero-vs-hero and hero-with-hero advantage matrices per rank bucket.

Input is public match data only: OpenDota's ``/publicMatches`` (hero IDs per team, the winner and
``avg_rank_tier``), or rows in the same shape.

For each rank bucket::

    WR(h)          = (wins_h + k * 0.5)   / (games_h + k)
    WR(a | vs b)   = (wins_ab + k * WR(a)) / (n_ab + k)     opposite teams
    WR(a | with b) = (wins_ab + k * WR(a)) / (n_ab + k)     same team
    vs(a, b)       = 100 * (WR(a | vs b)   - WR(a))
    with(a, b)     = 100 * (WR(a | with b) - WR(a))

A pair seen in fewer than ``MIN_PAIR_GAMES`` games is stored as null.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from d2bg.opendota import OpenDotaClient

SCHEMA_VERSION = 1
SMOOTHING_K = 20
MIN_PAIR_GAMES = 50
RANKED_LOBBY = 7
ALL_PICK_MODES = frozenset({22})  # ranked All Pick

# avg_rank_tier // 10 -> bucket. 1 Herald ... 8 Immortal.
RANK_BUCKETS: dict[str, tuple[int, int]] = {
    "1-2": (1, 2),
    "3-4": (3, 4),
    "5-6": (5, 6),
    "7-8": (7, 8),
}
ALL_BUCKET = "all"

Match = dict[str, Any]


def _hero_list(team: Any) -> list[int]:
    """OpenDota has returned teams both as [1, 2] and as "1,2"."""
    if isinstance(team, str):
        team = [t for t in team.split(",") if t.strip()]
    return [int(h) for h in (team or []) if int(h) > 0]


def normalize_match(raw: Mapping[str, Any]) -> Match | None:
    """Reduce a /publicMatches row (or a parsed-match row) to the fields used here."""
    if "radiant_win" not in raw or raw["radiant_win"] is None:
        return None
    if "players" in raw:
        radiant = [p["hero_id"] for p in raw["players"] if p.get("hero_id") and p.get("is_radiant")]
        dire = [p["hero_id"] for p in raw["players"] if p.get("hero_id") and not p.get("is_radiant")]
    else:
        radiant = _hero_list(raw.get("radiant_team"))
        dire = _hero_list(raw.get("dire_team"))
    if not radiant or not dire:
        return None
    return {
        "match_id": raw.get("match_id"),
        "start_time": raw.get("start_time"),
        "radiant": [int(h) for h in radiant],
        "dire": [int(h) for h in dire],
        "radiant_win": bool(raw["radiant_win"]),
        "avg_rank_tier": raw.get("avg_rank_tier") or 0,
    }


def bucket_for(avg_rank_tier: int | None) -> str | None:
    """Rank bucket for a match, or None when the rank is unknown."""
    if not avg_rank_tier:
        return None
    medal = int(avg_rank_tier) // 10
    for name, (lo, hi) in RANK_BUCKETS.items():
        if lo <= medal <= hi:
            return name
    return None


def compute_bucket(
    matches: Sequence[Mapping[str, Any]], k: float = SMOOTHING_K, min_pair_games: int = MIN_PAIR_GAMES
) -> dict[str, Any]:
    """Matrices for one bucket of normalized matches.

    vs[a][b] and with[a][b] are only present for pairs seen at least once; a missing pair means the
    same as null.
    """
    hero: dict[int, list[int]] = defaultdict(lambda: [0, 0])  # [games, wins]
    vs: dict[int, dict[int, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    with_: dict[int, dict[int, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))

    for m in matches:
        sides = ((m["radiant"], m["dire"], m["radiant_win"]), (m["dire"], m["radiant"], not m["radiant_win"]))
        for team, enemy, won in sides:
            w = int(won)
            for a in team:
                hero[a][0] += 1
                hero[a][1] += w
                for b in enemy:
                    vs[a][b][0] += 1
                    vs[a][b][1] += w
                for b in team:
                    if b != a:
                        with_[a][b][0] += 1
                        with_[a][b][1] += w

    n = len(matches)
    wr = {a: (g_w[1] + k * 0.5) / (g_w[0] + k) for a, g_w in hero.items()}

    def advantage(table: dict[int, dict[int, list[int]]]) -> dict[str, dict[str, float | None]]:
        out: dict[str, dict[str, float | None]] = {}
        for a, row in table.items():
            out[str(a)] = {}
            for b, (games, wins) in sorted(row.items()):
                if games < min_pair_games:
                    out[str(a)][str(b)] = None
                else:
                    pair_wr = (wins + k * wr[a]) / (games + k)
                    out[str(a)][str(b)] = round(100 * (pair_wr - wr[a]), 4)
        return out

    return {
        "n_matches": n,
        "heroes": {
            str(a): {
                "games": games,
                "wins": wins,
                "wr": round(wr[a], 6),
                "pick_rate": round(games / n, 6) if n else 0.0,
            }
            for a, (games, wins) in sorted(hero.items())
        },
        "vs": advantage(vs),
        "with": advantage(with_),
    }


def source_week(matches: list[Match], today: date | None = None) -> str:
    """ISO week of the newest match, e.g. "2026-W42"; today's week if unknown."""
    times = [m["start_time"] for m in matches if m.get("start_time")]
    d = datetime.fromtimestamp(max(times), tz=UTC).date() if times else (today or date.today())
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def build_matrix(
    matches: Iterable[Mapping[str, Any]],
    k: float = SMOOTHING_K,
    min_pair_games: int = MIN_PAIR_GAMES,
    today: date | None = None,
) -> dict[str, Any]:
    """Full output document from normalized (or raw) matches."""
    normalized: list[Match] = []
    for m in matches:
        nm = dict(m) if "radiant" in m else normalize_match(m)
        if nm:
            normalized.append(nm)

    by_bucket: dict[str, list[Match]] = {name: [] for name in RANK_BUCKETS}
    for m in normalized:
        b = bucket_for(m["avg_rank_tier"])
        if b:
            by_bucket[b].append(m)
    by_bucket[ALL_BUCKET] = normalized

    return {
        "version": SCHEMA_VERSION,
        "source_week": source_week(normalized, today),
        "n_matches": len(normalized),
        "smoothing_k": k,
        "min_pair_games": min_pair_games,
        "rank_buckets": {name: list(r) for name, r in RANK_BUCKETS.items()},
        "buckets": {name: compute_bucket(ms, k, min_pair_games) for name, ms in by_bucket.items()},
    }


def compact(doc: dict[str, Any], digits: int = 2) -> dict[str, Any]:
    """Round advantages for the committed snapshot; nulls stay null."""
    out = {k: v for k, v in doc.items() if k != "buckets"}
    out["buckets"] = {}
    for name, b in doc["buckets"].items():
        out["buckets"][name] = {
            "n_matches": b["n_matches"],
            "heroes": b["heroes"],
            **{
                table: {
                    a: {c: (None if v is None else round(v, digits)) for c, v in row.items()}
                    for a, row in b[table].items()
                }
                for table in ("vs", "with")
            },
        }
    return out


# ── Collecting ─────────────────────────────────────────────────────


def is_ranked_all_pick(row: Mapping[str, Any]) -> bool:
    return row.get("lobby_type") == RANKED_LOBBY and row.get("game_mode") in ALL_PICK_MODES


def collect_public_matches(
    client: OpenDotaClient, max_calls: int, days: int = 14, now: float | None = None
) -> list[dict[str, Any]]:
    """Ranked All Pick rows from the last ``days``, paging /publicMatches backwards.

    Older pages never change, so they are cached for a long time; the newest page is always fresh.
    """
    now = now or time.time()
    cutoff = now - days * 86400
    out: list[dict[str, Any]] = []
    cursor: int | None = None
    for _ in range(max_calls):
        params = {"less_than_match_id": cursor} if cursor else {}
        rows = client.get("publicMatches", params, ttl=365 * 86400 if cursor else 0)
        if not rows:
            break
        out.extend(r for r in rows if is_ranked_all_pick(r))
        cursor = min(int(r["match_id"]) for r in rows)
        if min(r.get("start_time") or now for r in rows) < cutoff:
            break
    return out


def read_page_dir(path: Path) -> list[dict[str, Any]]:
    """Rows from a folder of saved /publicMatches pages (``lt_<cursor>.json``)."""
    rows: dict[int, dict[str, Any]] = {}
    for file in sorted(path.glob("*.json")):
        try:
            page = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for r in page if isinstance(page, list) else []:
            rows[int(r["match_id"])] = r
    return [rows[k] for k in sorted(rows, reverse=True)]
