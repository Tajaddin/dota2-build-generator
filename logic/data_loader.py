"""Load hero/item data and synthesize fallback heroes from bundled stats."""

import json
import os
from pathlib import Path
from typing import Optional


class DataLoader:
    SUPPORT_ONLY_ITEMS = {
        "ward_observer", "ward_sentry", "dust", "smoke_of_deceit",
        "flying_courier", "tome_of_knowledge",
    }
    EXCLUDED_BUILD_ITEMS = {
        "aegis", "cheese", "courier", "flying_courier", "recipe", "recipe_",
        "ward_observer", "ward_sentry", "dust", "smoke_of_deceit",
        "tome_of_knowledge", "tpscroll",
    }
    COMPONENT_ITEMS = {
        "broadsword", "claymore", "blades_of_attack", "mithril_hammer",
        "ring_of_health", "void_stone", "platemail", "hyperstone",
        "demon_edge", "eaglesong", "eagle", "reaver", "mystic_staff", "sacred_relic",
        "ogre_axe", "blade_of_alacrity", "staff_of_wizardry", "point_booster",
        "vitality_booster", "energy_booster", "talisman_of_evasion",
        "javelin", "quarterstaff", "helm_of_iron_will", "ring_of_regen",
        "ring_of_protection", "stout_shield", "boots", "gloves",
        "belt_of_strength", "robe", "band_of_elvenskin", "cloak",
        "ring_of_tarrasque", "fluffy_hat", "diadem", "cornucopia",
        "tiara_of_selemene", "voodoo_mask", "blitz_knuckles", "crown",
        "lesser_crit", "oblivion_staff", "perseverance", "mask_of_death",
        "headdress", "buckler", "helm_of_the_dominator", "yasha", "sange",
        "kaya", "veil_of_discord",
    }
    DEFAULT_STARTING_ITEMS = {
        "agi": ["tango", "branches", "branches", "slippers", "circlet", "quelling_blade"],
        "str": ["tango", "branches", "branches", "gauntlets", "circlet", "quelling_blade"],
        "int": ["tango", "branches", "branches", "mantle", "circlet", "faerie_fire"],
        "uni": ["tango", "branches", "branches", "circlet", "circlet", "faerie_fire"],
        "all": ["tango", "branches", "branches", "circlet", "circlet", "faerie_fire"],
    }
    DEFAULT_MID_ITEMS = {
        "agi": ["power_treads", "magic_wand", "dragon_lance", "black_king_bar", "manta", "blink"],
        "str": ["phase_boots", "magic_wand", "blink", "black_king_bar", "shivas_guard", "heart"],
        "int": ["arcane_boots", "magic_wand", "black_king_bar", "ultimate_scepter", "lotus_orb", "blink"],
        "uni": ["power_treads", "magic_wand", "blink", "black_king_bar", "ultimate_scepter", "lotus_orb"],
        "all": ["power_treads", "magic_wand", "blink", "black_king_bar", "ultimate_scepter", "lotus_orb"],
    }
    DEFAULT_LATE_ITEMS = {
        "agi": ["boots_of_travel", "black_king_bar", "butterfly", "skadi", "satanic", "abyssal_blade"],
        "str": ["boots_of_travel", "black_king_bar", "heart", "shivas_guard", "lotus_orb", "assault"],
        "int": ["boots_of_travel", "black_king_bar", "ultimate_scepter", "lotus_orb", "shivas_guard", "scythe_of_vyse"],
        "uni": ["boots_of_travel", "black_king_bar", "heart", "ultimate_scepter", "lotus_orb", "shivas_guard"],
        "all": ["boots_of_travel", "black_king_bar", "ultimate_scepter", "lotus_orb", "shivas_guard", "heart"],
    }

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        self.data_dir = Path(data_dir)
        self._heroes: dict = {}
        self._items: dict = {}
        self._hero_tags: dict = {}
        self._trained_builds: dict = {}
        self._matchups: dict = {}
        self._hero_stats_by_valve: dict = {}
        self._hero_stats_by_internal: dict = {}
        self._valve_to_internal: dict = {}
        self._internal_to_valve: dict = {}
        self._load_all()

    def _load_all(self):
        """Load local assets, then fill missing heroes from bundled stats."""
        self._items = self._load_json(self.data_dir / "items.json", {})

        hero_map = self._load_json(self.data_dir / "hero_id_map.json", {})
        self._valve_to_internal = hero_map.get("valve_to_internal", {})
        self._internal_to_valve = hero_map.get("internal_to_valve", {})

        self._hero_tags = self._load_json(self.data_dir / "hero_tags.json", {})
        trained = self._load_json(self.data_dir / "opendota" / "trained_data.json", {})
        self._trained_builds = trained.get("builds", {})
        self._matchups = self._load_json(self.data_dir / "opendota" / "matchups.json", {})

        hero_stats = self._load_json(self.data_dir / "opendota" / "hero_stats.json", [])
        if isinstance(hero_stats, list):
            for row in hero_stats:
                npc_name = row.get("npc_name", "")
                if not npc_name:
                    continue
                valve_id = npc_name.replace("npc_dota_hero_", "")
                internal_id = self._to_internal_id(valve_id)
                self._hero_stats_by_valve[valve_id] = row
                self._hero_stats_by_internal[internal_id] = row

        heroes_dir = self.data_dir / "heroes"
        if heroes_dir.exists():
            for hero_file in heroes_dir.glob("*.json"):
                hero_data = self._load_json(hero_file, None)
                if hero_data:
                    self._heroes[hero_data["id"]] = hero_data

        self._synthesize_missing_heroes()

    def _load_json(self, path: Path, default):
        if not path.exists():
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _to_internal_id(self, hero_id: str) -> str:
        return self._valve_to_internal.get(hero_id, hero_id)

    def _to_valve_id(self, hero_id: str) -> str:
        return self._internal_to_valve.get(hero_id, hero_id)

    def _synthesize_missing_heroes(self):
        valve_ids = set(self._hero_tags.keys())
        valve_ids.update(self._hero_stats_by_valve.keys())
        valve_ids.update(self._trained_builds.keys())

        for valve_id in sorted(valve_ids):
            internal_id = self._to_internal_id(valve_id)
            if internal_id in self._heroes:
                continue
            hero = self._build_synthetic_hero(internal_id, valve_id)
            if hero:
                self._heroes[internal_id] = hero

    def _build_synthetic_hero(self, internal_id: str, valve_id: str) -> Optional[dict]:
        tags = self._hero_tags.get(valve_id) or self._hero_tags.get(internal_id) or {}
        stats = self._hero_stats_by_internal.get(internal_id) or self._hero_stats_by_valve.get(valve_id) or {}
        builds = self._trained_builds.get(valve_id) or self._trained_builds.get(internal_id) or {}

        hero_name = tags.get("name") or stats.get("name")
        if not hero_name:
            return None

        primary_attr = stats.get("primary_attr", "all")
        roles = self._build_roles(tags, stats)
        good_against, counters = self._build_matchups(valve_id)
        build = self._build_synthetic_meta_build(hero_name, primary_attr, builds)

        return {
            "id": internal_id,
            "name": hero_name,
            "primary_attr": primary_attr,
            "roles": roles,
            "counters": counters,
            "good_against": good_against,
            "builds": {
                "opendota_meta": build,
            },
            "auto_generated": True,
        }

    def _build_roles(self, tags: dict, stats: dict) -> list[str]:
        roles = []
        seen = set()
        role_map = {
            "carry": "Carry",
            "mid": "Mid",
            "offlane": "Offlane",
            "support": "Support",
            "hard_support": "Support",
        }

        for role in tags.get("role_tags", []):
            normalized = role_map.get(str(role).lower(), str(role).replace("_", " ").title())
            if normalized not in seen:
                seen.add(normalized)
                roles.append(normalized)

        for role in stats.get("roles", []):
            normalized = str(role).replace("_", " ").title()
            if normalized == "Hard Support":
                normalized = "Support"
            if normalized not in seen:
                seen.add(normalized)
                roles.append(normalized)

        return roles or ["Carry"]

    def _hero_display_name(self, hero_id: str) -> str:
        internal_id = self._to_internal_id(hero_id)
        if internal_id in self._heroes:
            return self._heroes[internal_id]["name"]
        tags = self._hero_tags.get(hero_id) or self._hero_tags.get(internal_id) or {}
        stats = self._hero_stats_by_internal.get(internal_id) or self._hero_stats_by_valve.get(hero_id) or {}
        return tags.get("name") or stats.get("name") or internal_id.replace("_", " ").title()

    def _build_matchups(self, valve_id: str) -> tuple[list[str], list[str]]:
        matchups = self._matchups.get(valve_id, {})
        if not isinstance(matchups, dict):
            return [], []

        samples = [
            (enemy_id, data)
            for enemy_id, data in matchups.items()
            if isinstance(data, dict) and data.get("games", 0) >= 40
        ]

        good = sorted(samples, key=lambda x: x[1].get("advantage", 0), reverse=True)
        bad = sorted(samples, key=lambda x: x[1].get("advantage", 0))

        good_against = [
            self._hero_display_name(enemy_id)
            for enemy_id, data in good
            if data.get("advantage", 0) > 0
        ][:3]
        counters = [
            self._hero_display_name(enemy_id)
            for enemy_id, data in bad
            if data.get("advantage", 0) < 0
        ][:3]
        return good_against, counters

    def _build_synthetic_meta_build(self, hero_name: str, hero_attr: str, builds: dict) -> dict:
        early = self._phase_from_popularity(builds.get("early_game", []), "early", hero_attr)
        mid = self._phase_from_popularity(builds.get("mid_game", []), "mid", hero_attr)
        late = self._phase_from_popularity(builds.get("late_game", []), "late", hero_attr)

        return {
            "label": "OpenDota Meta",
            "description": "Auto-generated from bundled OpenDota item trends. Use the live overlay for draft-aware adjustments.",
            "early_game": early,
            "mid_game": mid,
            "late_game": late,
            "skill_build": {
                "order": [],
                "notes": "No curated skill build is bundled for this hero yet.",
            },
            "strategy": (
                f"Auto-generated build for {hero_name} based on the bundled OpenDota popularity data. "
                "Use this as a stable default and prefer the live overlay when draft data is available."
            ),
        }

    def _phase_from_popularity(self, entries: list[dict], phase: str, hero_attr: str) -> list[dict]:
        selected = []
        seen = set()
        for entry in entries:
            item_id = entry.get("item", "")
            if not self._item_allowed_for_phase(item_id, phase):
                continue
            if phase != "early" and item_id in seen:
                continue
            selected.append({
                "item": item_id,
                "note": f"{entry.get('popularity', 0):.1f}% build rate",
            })
            seen.add(item_id)
            if len(selected) >= 6:
                break

        defaults = {
            "early": self.DEFAULT_STARTING_ITEMS,
            "mid": self.DEFAULT_MID_ITEMS,
            "late": self.DEFAULT_LATE_ITEMS,
        }[phase].get(hero_attr, self.DEFAULT_LATE_ITEMS["all"] if phase == "late" else self.DEFAULT_MID_ITEMS["all"])

        if phase == "early":
            defaults = self.DEFAULT_STARTING_ITEMS.get(hero_attr, self.DEFAULT_STARTING_ITEMS["all"])

        for item_id in defaults:
            if len(selected) >= 6:
                break
            if phase != "early" and item_id in seen:
                continue
            if not self._item_allowed_for_phase(item_id, phase):
                continue
            selected.append({"item": item_id, "note": "fallback"})
            seen.add(item_id)

        return selected[:6]

    def _item_allowed_for_phase(self, item_id: str, phase: str) -> bool:
        if not item_id:
            return False
        if item_id in self.SUPPORT_ONLY_ITEMS:
            return False
        if item_id in self.EXCLUDED_BUILD_ITEMS:
            return False
        if item_id.startswith("recipe_"):
            return False

        item_data = self._items.get(item_id, {})
        category = item_data.get("category", "")

        if phase in {"mid", "late"} and item_id in self.COMPONENT_ITEMS:
            return False
        if phase == "late" and category == "consumable":
            return False

        return True

    def get_all_heroes(self) -> list[dict]:
        """Return list of all hero dicts sorted by name."""
        return sorted(self._heroes.values(), key=lambda h: h["name"])

    def get_hero(self, hero_id: str) -> Optional[dict]:
        """Return a single hero's full data by ID."""
        return self._heroes.get(hero_id)

    def get_heroes_by_role(self, role: str) -> list[dict]:
        """Return heroes that have the given role."""
        return sorted(
            [h for h in self._heroes.values() if role in h.get("roles", [])],
            key=lambda h: h["name"]
        )

    def get_all_items(self) -> dict:
        """Return the full items dictionary."""
        return self._items

    def get_item(self, item_id: str) -> Optional[dict]:
        """Return a single item's data by ID."""
        return self._items.get(item_id)
