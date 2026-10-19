"""Build weekly hero-vs-hero and hero-with-hero advantage matrices.

Input is public match data only: OpenDota's /publicMatches endpoint (hero IDs
per team, the winner and avg_rank_tier), or a matches.jsonl written by
ml/kaggle_ingest.py or ml/data_collector.py.

For each rank bucket:

    WR(h)          = (wins_h + k * 0.5)   / (games_h + k)
    WR(a | vs b)   = (wins_ab + k * WR(a)) / (n_ab + k)     opposite teams
    WR(a | with b) = (wins_ab + k * WR(a)) / (n_ab + k)     same team
    vs(a, b)       = 100 * (WR(a | vs b)   - WR(a))
    with(a, b)     = 100 * (WR(a | with b) - WR(a))

A pair seen in fewer than MIN_PAIR_GAMES games is stored as null.

Output: data/matchups/<YYYY-MM-DD>.json

    python -m ml.build_matchup_matrix --calls 1500
    python -m ml.build_matchup_matrix --from-jsonl ml/raw_data/matches.jsonl
"""
import argparse
import json
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

import requests

OPENDOTA_BASE = "https://api.opendota.com/api"
SCHEMA_VERSION = 1
SMOOTHING_K = 20
MIN_PAIR_GAMES = 50
RANKED_LOBBY = 7
ALL_PICK_MODES = {22}  # ranked All Pick

# avg_rank_tier // 10 -> bucket. 1 Herald ... 8 Immortal. Tunable.
RANK_BUCKETS = {
    "1-2": (1, 2),
    "3-4": (3, 4),
    "5-6": (5, 6),
    "7-8": (7, 8),
}
ALL_BUCKET = "all"

ROOT = Path(__file__).resolve().parent.parent
MATCHUPS_DIR = ROOT / "data" / "matchups"
CACHE_DIR = ROOT / "data" / "cache" / "public_matches"


# ── Normalizing ────────────────────────────────────────────────────

def _hero_list(team) -> list[int]:
    """OpenDota has returned teams both as [1, 2] and as "1,2"."""
    if isinstance(team, str):
        team = [t for t in team.split(",") if t.strip()]
    return [int(h) for h in (team or []) if int(h) > 0]


def normalize_match(raw: dict) -> Optional[dict]:
    """Reduce a /publicMatches row or a matches.jsonl row to the fields we use.

    Returns None when the row has no usable teams or result.
    """
    if "radiant_win" not in raw:
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


def bucket_for(avg_rank_tier) -> Optional[str]:
    """Rank bucket for a match, or None when the rank is unknown."""
    if not avg_rank_tier:
        return None
    medal = int(avg_rank_tier) // 10
    for name, (lo, hi) in RANK_BUCKETS.items():
        if lo <= medal <= hi:
            return name
    return None


# ── Matrix computation ─────────────────────────────────────────────

def _nested():
    return defaultdict(lambda: defaultdict(lambda: [0, 0]))  # [games, wins]


def compute_bucket(matches: list[dict], k: float = SMOOTHING_K,
                   min_pair_games: int = MIN_PAIR_GAMES) -> dict:
    """Matrices for one bucket of normalized matches.

    vs[a][b] and with[a][b] are only present for pairs seen at least once;
    a missing pair means the same as null.
    """
    hero = defaultdict(lambda: [0, 0])
    vs = _nested()
    with_ = _nested()

    for m in matches:
        sides = ((m["radiant"], m["dire"], m["radiant_win"]),
                 (m["dire"], m["radiant"], not m["radiant_win"]))
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

    def advantage(table):
        out = {}
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


def source_week(matches: list[dict], today: Optional[date] = None) -> str:
    """ISO week of the newest match, e.g. "2026-W42"; today's week if unknown."""
    times = [m["start_time"] for m in matches if m.get("start_time")]
    d = (datetime.fromtimestamp(max(times), tz=timezone.utc).date()
         if times else (today or date.today()))
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def build_matrix(matches: Iterable[dict], k: float = SMOOTHING_K,
                 min_pair_games: int = MIN_PAIR_GAMES,
                 today: Optional[date] = None) -> dict:
    """Full output document from normalized (or raw) matches."""
    normalized = []
    for m in matches:
        nm = m if "radiant" in m else normalize_match(m)
        if nm:
            normalized.append(nm)

    by_bucket = {name: [] for name in RANK_BUCKETS}
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
        "buckets": {name: compute_bucket(ms, k, min_pair_games)
                    for name, ms in by_bucket.items()},
    }


# ── Collecting from OpenDota ───────────────────────────────────────

class PublicMatchesClient:
    """Pages /publicMatches backwards with a fixed request interval.

    The free tier allows about 60 requests a minute, so the default interval
    is 1.05 s. Every page is cached on disk by its less_than_match_id cursor;
    a rerun reads the cache and only spends requests on new pages.
    `http_get` and `sleep` are injectable so tests never touch the network.
    """

    def __init__(self, cache_dir: Path = CACHE_DIR, interval: float = 1.05,
                 api_key: Optional[str] = None,
                 http_get: Callable = requests.get, sleep: Callable = time.sleep):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.interval = interval
        self.api_key = api_key
        self.http_get = http_get
        self.sleep = sleep
        self.requests_made = 0
        self._last_request = None

    def _cache_file(self, cursor: Optional[int]) -> Path:
        return self.cache_dir / f"lt_{cursor or 'latest'}.json"

    def page(self, cursor: Optional[int]) -> Optional[list]:
        """One page of up to 100 matches older than `cursor`."""
        cache_file = self._cache_file(cursor)
        # The newest page changes every second, so it is never read from cache.
        if cursor and cache_file.exists():
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        params = {}
        if cursor:
            params["less_than_match_id"] = cursor
        if self.api_key:
            params["api_key"] = self.api_key

        for attempt in range(4):
            if self._last_request is not None:
                wait = self.interval - (time.monotonic() - self._last_request)
                if wait > 0:
                    self.sleep(wait)
            self._last_request = time.monotonic()
            self.requests_made += 1
            try:
                resp = self.http_get(f"{OPENDOTA_BASE}/publicMatches",
                                     params=params, timeout=30)
            except requests.RequestException:
                self.sleep(5 * (attempt + 1))
                continue
            if resp.status_code == 429:
                self.sleep(60 * (attempt + 1))
                continue
            if resp.status_code != 200:
                return None
            rows = resp.json()
            if cursor:
                cache_file.write_text(json.dumps(rows), encoding="utf-8")
            return rows
        return None

    def collect(self, max_calls: int, days: int = 14,
                now: Optional[float] = None) -> list[dict]:
        """Ranked All Pick matches from the last `days`, newest first."""
        cutoff = (now or time.time()) - days * 86400
        out, cursor, pages = [], None, 0
        while pages < max_calls:
            rows = self.page(cursor)
            pages += 1
            if not rows:
                break
            for r in rows:
                if r.get("lobby_type") == RANKED_LOBBY and r.get("game_mode") in ALL_PICK_MODES:
                    out.append(r)
            cursor = min(r["match_id"] for r in rows)
            if min(r.get("start_time", now or time.time()) for r in rows) < cutoff:
                break
        return out


# ── I/O ────────────────────────────────────────────────────────────

def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def write_matrix(doc: dict, out_dir: Path = MATCHUPS_DIR,
                 day: Optional[date] = None) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{(day or date.today()).isoformat()}.json"
    path.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    return path


def load_matrix(path: Optional[Path] = None, out_dir: Path = MATCHUPS_DIR) -> dict:
    """Load a matrix file; with no path, the newest in data/matchups/."""
    if path is None:
        files = sorted(Path(out_dir).glob("????-??-??.json"))
        if not files:
            raise FileNotFoundError(f"no matchup matrix in {out_dir}")
        path = files[-1]
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from-jsonl", type=Path, help="use a matches.jsonl instead of the API")
    ap.add_argument("--calls", type=int, default=1500,
                    help="max /publicMatches pages (100 rows each, ~60/min)")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--out-dir", type=Path, default=MATCHUPS_DIR)
    args = ap.parse_args()

    if args.from_jsonl:
        raw = read_jsonl(args.from_jsonl)
    else:
        client = PublicMatchesClient(api_key=args.api_key)
        raw = client.collect(max_calls=args.calls, days=args.days)
        print(f"[matrix] {client.requests_made} requests, {len(raw)} ranked All Pick matches")

    doc = build_matrix(raw)
    path = write_matrix(doc, args.out_dir)
    sizes = {b: v["n_matches"] for b, v in doc["buckets"].items()}
    print(f"[matrix] wrote {path} ({doc['n_matches']} matches, {doc['source_week']}) {sizes}")


if __name__ == "__main__":
    main()
