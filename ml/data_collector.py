"""Collect match data from OpenDota API for training."""
import json
import os
import time
import requests
from pathlib import Path
from typing import Optional


# OpenDota API endpoints
OPENDOTA_BASE = "https://api.opendota.com/api"

# Rank tiers in OpenDota: 10=Herald, 20=Guardian, 30=Crusader, 40=Archon,
# 50=Legend, 60=Ancient, 70=Divine, 80=Immortal
RANK_WEIGHTS = {
    80: 1.0,    # Immortal
    70: 0.9,    # Divine
    60: 0.8,    # Ancient
    50: 0.6,    # Legend
    40: 0.5,    # Archon
    30: 0.4,    # Crusader
    20: 0.35,   # Guardian
    10: 0.3,    # Herald
}

# State file for daily cap (free tier e.g. 3000/day)
DAILY_STATE_FILE = ".collect_daily.json"


def _load_api_key_from_config(data_dir: Optional[str] = None) -> Optional[str]:
    """Load OpenDota API key from data/config.json if present."""
    if not data_dir:
        return None
    config_path = Path(data_dir) / "config.json"
    if not config_path.exists():
        return None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return config.get("opendota_api_key") or None
    except Exception:
        return None


def _read_daily_count(output_dir: Path) -> tuple[str, int]:
    """Return (today's date string, number of matches collected today)."""
    state_path = output_dir / DAILY_STATE_FILE
    if not state_path.exists():
        return "", 0
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("date", ""), data.get("count", 0)
    except Exception:
        return "", 0


def _write_daily_count(output_dir: Path, date_str: str, count: int):
    state_path = output_dir / DAILY_STATE_FILE
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump({"date": date_str, "count": count}, f)
    except Exception:
        pass


class OpenDotaCollector:
    """Fetches public match data from OpenDota API."""

    def __init__(self, output_dir: str, api_key: Optional[str] = None,
                 data_dir: Optional[str] = None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = api_key or _load_api_key_from_config(data_dir)
        if self.api_key:
            print("[Collector] Using OpenDota API key from config (higher rate limit)")
        self._request_count = 0

    def _get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """Make rate-limited GET request to OpenDota."""
        if params is None:
            params = {}
        if self.api_key:
            params["api_key"] = self.api_key

        url = f"{OPENDOTA_BASE}{endpoint}"
        self._request_count += 1

        # Rate limit: 60 requests/min without key, 1200/min with key
        if not self.api_key and self._request_count % 55 == 0:
            print(f"[Collector] Rate limit pause (request #{self._request_count})...")
            time.sleep(65)

        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                print("[Collector] Rate limited, waiting 60s...")
                time.sleep(60)
                resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[Collector] Error fetching {endpoint}: {e}")
            return None

    def fetch_public_matches(self, count: int = 1000) -> list[dict]:
        """Fetch recent public match IDs from the /publicMatches endpoint.

        Returns list of minimal match data with match_id, avg_rank_tier, etc.
        """
        all_matches = []
        less_than_match_id = None

        while len(all_matches) < count:
            params = {"mmr_ascending": "false"}
            if less_than_match_id:
                params["less_than_match_id"] = less_than_match_id

            batch = self._get("/publicMatches", params)
            if not batch:
                break

            all_matches.extend(batch)
            less_than_match_id = batch[-1]["match_id"]
            print(f"[Collector] Fetched {len(all_matches)}/{count} match IDs...")

            if len(batch) < 100:
                break

        return all_matches[:count]

    def fetch_match_details(self, match_id: int) -> Optional[dict]:
        """Fetch full match details including player items and purchase log."""
        return self._get(f"/matches/{match_id}")

    def collect_matches(self, target_count: int = 1000, resume: bool = True,
                        max_per_day: Optional[int] = None):
        """Collect match data and save to disk.

        Fetches match IDs first, then downloads full details for each.
        Supports resuming interrupted collection.

        Args:
            target_count: Total matches to have in file (stops when reached).
            resume: If True, skip already-collected match IDs.
            max_per_day: If set (e.g. 3000), only collect up to this many new
                matches per calendar day (free-tier friendly). State in .collect_daily.json.
        """
        collected_file = self.output_dir / "matches.jsonl"
        today = time.strftime("%Y-%m-%d")

        # Daily cap: how many we're allowed to add today
        if max_per_day is not None:
            state_date, state_count = _read_daily_count(self.output_dir)
            if state_date == today and state_count >= max_per_day:
                print(f"[Collector] Daily cap reached ({state_count}/{max_per_day}). "
                      "Run again tomorrow or omit --max-per-day.")
                return
            daily_remaining = max_per_day - (state_count if state_date == today else 0)
        else:
            daily_remaining = None

        # Resume from previous run
        collected_ids = set()
        if resume and collected_file.exists():
            with open(collected_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        m = json.loads(line)
                        collected_ids.add(m["match_id"])
                    except (json.JSONDecodeError, KeyError):
                        pass
            print(f"[Collector] Resuming: {len(collected_ids)} matches already collected")

        want_more = target_count - len(collected_ids)
        if want_more <= 0:
            print(f"[Collector] Already have {len(collected_ids)} matches (target {target_count}). Done.")
            return
        if daily_remaining is not None and want_more > daily_remaining:
            want_more = daily_remaining
            print(f"[Collector] Capping at {daily_remaining} new matches today (--max-per-day)")

        # Fetch match IDs
        print(f"[Collector] Fetching up to {want_more} new match details...")
        match_list = self.fetch_public_matches(want_more * 2)  # Extra for filtering

        # Filter to ranked matches with rank info
        ranked = [m for m in match_list
                  if m.get("avg_rank_tier") and m.get("avg_rank_tier") >= 10
                  and m["match_id"] not in collected_ids]
        print(f"[Collector] {len(ranked)} ranked matches to fetch details for")

        # Fetch full match details
        success = 0
        with open(collected_file, "a", encoding="utf-8") as f:
            for i, match_info in enumerate(ranked):
                if success >= want_more:
                    break

                match_id = match_info["match_id"]
                details = self.fetch_match_details(match_id)
                if not details or not details.get("players"):
                    continue

                # Extract relevant fields
                match_data = self._extract_match_data(details, match_info)
                if match_data:
                    f.write(json.dumps(match_data) + "\n")
                    f.flush()
                    success += 1
                    if max_per_day is not None:
                        state_date, state_count = _read_daily_count(self.output_dir)
                        new_count = (state_count + 1) if state_date == today else 1
                        _write_daily_count(self.output_dir, today, new_count)

                if (i + 1) % 10 == 0:
                    total = len(collected_ids) + success
                    print(f"[Collector] Progress: {total}/{target_count} matches collected")

        total = len(collected_ids) + success
        print(f"[Collector] Done! {total} total matches collected")

    def _extract_match_data(self, details: dict, match_info: dict) -> Optional[dict]:
        """Extract training-relevant data from a full match details response."""
        players = details.get("players", [])
        if len(players) != 10:
            return None

        duration = details.get("duration", 0)
        if duration < 900:  # Skip matches shorter than 15 min
            return None

        radiant_win = details.get("radiant_win", False)
        avg_rank = match_info.get("avg_rank_tier", 0)
        rank_bucket = (avg_rank // 10) * 10  # Round to nearest tier
        weight = RANK_WEIGHTS.get(rank_bucket, 0.3)

        player_data = []
        for p in players:
            hero_id = p.get("hero_id")
            if not hero_id:
                continue

            # Extract item slots (final inventory)
            items = []
            for slot in range(6):
                item_id = p.get(f"item_{slot}")
                if item_id and item_id > 0:
                    items.append(item_id)

            # Extract purchase log (item name + time)
            purchase_log = []
            for entry in (p.get("purchase_log") or []):
                purchase_log.append({
                    "item": entry.get("key", ""),
                    "time": entry.get("time", 0),
                })

            player_data.append({
                "hero_id": hero_id,
                "is_radiant": p.get("isRadiant", False),
                "win": (p.get("isRadiant", False) == radiant_win),
                "items": items,
                "purchase_log": purchase_log,
                "net_worth": p.get("net_worth", 0),
                "rank_tier": p.get("rank_tier", avg_rank),
            })

        if len(player_data) != 10:
            return None

        return {
            "match_id": details["match_id"],
            "duration": duration,
            "radiant_win": radiant_win,
            "avg_rank_tier": avg_rank,
            "weight": weight,
            "patch": details.get("patch", 0),
            "players": player_data,
        }


def main():
    """CLI entry point for data collection."""
    import argparse
    parser = argparse.ArgumentParser(description="Collect Dota 2 match data from OpenDota")
    parser.add_argument("--count", type=int, default=1000, help="Number of matches to collect")
    parser.add_argument("--output", default="ml/raw_data", help="Output directory")
    parser.add_argument("--api-key", default=None, help="OpenDota API key (optional, increases rate limit)")
    parser.add_argument("--data-dir", default="data", help="Directory containing config.json for opendota_api_key")
    parser.add_argument("--max-per-day", type=int, default=None,
                        help="Max new matches per day (e.g. 3000 for free tier). Run daily to accumulate.")
    args = parser.parse_args()

    collector = OpenDotaCollector(args.output, api_key=args.api_key, data_dir=args.data_dir)
    collector.collect_matches(target_count=args.count, max_per_day=args.max_per_day)


if __name__ == "__main__":
    main()
