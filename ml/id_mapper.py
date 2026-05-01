"""Map between OpenDota numeric item IDs and internal string IDs."""
import json
import requests
from pathlib import Path
from typing import Optional


class IDMapper:
    """Bidirectional mapping between numeric IDs and string IDs for heroes and items."""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self._item_id_to_name = {}   # numeric -> string (e.g., 1 -> "blink")
        self._item_name_to_id = {}   # string -> numeric
        self._hero_id_to_name = {}   # numeric -> internal (e.g., 1 -> "anti_mage")
        self._hero_name_to_id = {}   # internal -> numeric
        self._load()

    def _load(self):
        """Load mappings from data files and/or fetch from API."""
        # Hero mapping from hero_id_map.json
        hero_map_path = self.data_dir / "hero_id_map.json"
        if hero_map_path.exists():
            with open(hero_map_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # hero_id_to_name maps numeric string -> valve name
            id_to_valve = data.get("hero_id_to_name", {})
            valve_to_internal = data.get("valve_to_internal", {})
            for num_id, valve_name in id_to_valve.items():
                internal = valve_to_internal.get(valve_name, valve_name)
                self._hero_id_to_name[int(num_id)] = internal
                self._hero_name_to_id[internal] = int(num_id)
                # Also register valve name so both "nevermore" and
                # "shadow_fiend" map to the same numeric ID
                if valve_name != internal:
                    self._hero_name_to_id[valve_name] = int(num_id)

        # Item mapping - try cached file first, then fetch from API
        item_map_path = self.data_dir / "opendota_item_ids.json"
        if item_map_path.exists():
            with open(item_map_path, "r", encoding="utf-8") as f:
                self._item_id_to_name = {int(k): v for k, v in json.load(f).items()}
        else:
            self._fetch_item_ids(item_map_path)

        self._item_name_to_id = {v: k for k, v in self._item_id_to_name.items()}

    def _fetch_item_ids(self, save_path: Path):
        """Fetch item ID mapping from OpenDota constants API."""
        print("[IDMapper] Fetching item IDs from OpenDota...")
        try:
            resp = requests.get("https://api.opendota.com/api/constants/items", timeout=30)
            resp.raise_for_status()
            items = resp.json()

            mapping = {}
            for item_name, item_data in items.items():
                item_id = item_data.get("id")
                if item_id:
                    mapping[item_id] = item_name
                    # Strip "item_" prefix if present
                    clean_name = item_name
                    if clean_name.startswith("item_"):
                        clean_name = clean_name[5:]
                    self._item_id_to_name[item_id] = clean_name

            # Save for future use
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump({str(k): v for k, v in self._item_id_to_name.items()}, f, indent=2)
            print(f"[IDMapper] Saved {len(mapping)} item IDs to {save_path}")

        except Exception as e:
            print(f"[IDMapper] Failed to fetch item IDs: {e}")

    def item_id_to_name(self, item_id: int) -> str:
        return self._item_id_to_name.get(item_id, f"unknown_{item_id}")

    def item_name_to_id(self, name: str) -> int:
        return self._item_name_to_id.get(name, 0)

    def hero_id_to_name(self, hero_id: int) -> str:
        return self._hero_id_to_name.get(hero_id, f"unknown_{hero_id}")

    def hero_name_to_id(self, name: str) -> int:
        return self._hero_name_to_id.get(name, 0)

    @property
    def num_heroes(self) -> int:
        return len(self._hero_id_to_name)

    @property
    def num_items(self) -> int:
        return len(self._item_id_to_name)

    @property
    def max_hero_id(self) -> int:
        return max(self._hero_id_to_name.keys()) if self._hero_id_to_name else 0

    @property
    def max_item_id(self) -> int:
        return max(self._item_id_to_name.keys()) if self._item_id_to_name else 0
