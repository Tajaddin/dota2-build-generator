"""Fetch item win-rate data from OpenDota API with caching."""
import json
import time
import requests
from pathlib import Path
from typing import Optional

OPENDOTA_BASE = "https://api.opendota.com/api"
CACHE_TTL = 3600 * 6  # 6 hours


class WinrateFetcher:
    """Fetches and caches item popularity/win-rate data from OpenDota.

    Results are cached locally for 6 hours to avoid spamming the API.
    Falls back gracefully when offline — returns None and the recommender
    uses pure rule-based scoring.
    """

    def __init__(self, cache_dir: Optional[str] = None):
        if cache_dir is None:
            cache_dir = str(Path(__file__).parent.parent / "data" / "cache")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _read_cache(self, cache_file: Path) -> Optional[dict]:
        """Read cached data if it exists and isn't expired."""
        if not cache_file.exists():
            return None
        try:
            with open(cache_file, "r") as f:
                cached = json.load(f)
            if time.time() - cached.get("_timestamp", 0) < CACHE_TTL:
                return cached.get("data")
        except (json.JSONDecodeError, KeyError, OSError):
            pass
        return None

    def _write_cache(self, cache_file: Path, data):
        """Write data to cache with timestamp."""
        try:
            with open(cache_file, "w") as f:
                json.dump({"_timestamp": time.time(), "data": data}, f)
        except OSError:
            pass

    def get_item_popularity(self, hero_id: int) -> Optional[dict]:
        """Get item purchase/win data for a hero by numeric ID.

        Returns dict with 'start_game_items', 'early_game_items',
        'mid_game_items', 'late_game_items' keys, each containing
        item purchase frequency data.
        """
        cache_file = self.cache_dir / f"items_hero_{hero_id}.json"
        cached = self._read_cache(cache_file)
        if cached is not None:
            return cached

        try:
            url = f"{OPENDOTA_BASE}/heroes/{hero_id}/itemPopularity"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                self._write_cache(cache_file, data)
                return data
        except (requests.RequestException, json.JSONDecodeError):
            pass

        return None

    def get_matchup_winrates(self, hero_id: int) -> Optional[list]:
        """Get hero-vs-hero win rates.

        Returns list of dicts with 'hero_id', 'games_played', 'wins' keys.
        """
        cache_file = self.cache_dir / f"matchups_hero_{hero_id}.json"
        cached = self._read_cache(cache_file)
        if cached is not None:
            return cached

        try:
            url = f"{OPENDOTA_BASE}/heroes/{hero_id}/matchups"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                self._write_cache(cache_file, data)
                return data
        except (requests.RequestException, json.JSONDecodeError):
            pass

        return None
