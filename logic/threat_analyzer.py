"""Analyze enemy team composition and identify threats."""
import json
from pathlib import Path


class ThreatAnalyzer:
    """Analyzes enemy heroes and produces a threat profile.

    Reads hero_tags.json and counts damage types, disables, and specific
    threat categories to help the item recommender prioritize counter-items.
    """

    WARNING_THRESHOLDS = {
        "magic_threat_count": (2, "HIGH Magic Damage -- consider BKB rush"),
        "physical_threat_count": (3, "Heavy Physical Damage -- armor items recommended"),
        "disable_count": (3, "Many Disables -- BKB or Linken's critical"),
        "gap_closer_count": (2, "Multiple Gap Closers -- positioning items important"),
        "silence_count": (1, "Silence threat -- Manta or BKB for dispel"),
        "invis_count": (1, "Invisible heroes -- carry detection items"),
        "burst_count": (3, "Heavy Burst -- survivability items priority"),
        "armor_shred_count": (1, "Armor Reduction -- extra armor items helpful"),
    }

    def __init__(self, data_dir: str):
        data_path = Path(data_dir)
        tags_path = data_path / "hero_tags.json"
        if tags_path.exists():
            with open(tags_path, "r", encoding="utf-8") as f:
                self._hero_tags = json.load(f)
        else:
            self._hero_tags = {}

    def analyze_enemies(self, enemy_hero_ids: list[str]) -> dict:
        """Analyze a list of enemy hero IDs and return threat profile.

        Args:
            enemy_hero_ids: List of Valve hero IDs (e.g., ["antimage", "lion"])

        Returns:
            Dict with threat_summary, hero_details, warnings, and various counts.
        """
        threat_summary = set()
        hero_details = []
        counts = {
            "magic_threat_count": 0,
            "physical_threat_count": 0,
            "pure_threat_count": 0,
            "disable_count": 0,
            "stun_count": 0,
            "silence_count": 0,
            "hex_count": 0,
            "root_count": 0,
            "gap_closer_count": 0,
            "invis_count": 0,
            "illusion_count": 0,
            "summon_count": 0,
            "mana_burn_count": 0,
            "armor_shred_count": 0,
            "burst_count": 0,
            "global_count": 0,
            "evasion_count": 0,
            "heal_count": 0,
        }

        for hero_id in enemy_hero_ids:
            tags = self._hero_tags.get(hero_id)
            if not tags:
                continue

            detail = {
                "id": hero_id,
                "name": tags.get("name", hero_id),
                "damage_types": tags.get("damage_type", []),
                "tags": tags.get("threat_tags", []),
                "disables": tags.get("disable_tags", []),
            }
            hero_details.append(detail)

            # Count damage types
            for dmg in tags.get("damage_type", []):
                if dmg == "magic":
                    counts["magic_threat_count"] += 1
                    threat_summary.add("magic_burst")
                elif dmg == "physical":
                    counts["physical_threat_count"] += 1
                    threat_summary.add("physical_carry")
                elif dmg == "pure":
                    counts["pure_threat_count"] += 1

            # Count threat tags
            tag_to_count = {
                "gap_closer": "gap_closer_count",
                "silence": "silence_count",
                "invis": "invis_count",
                "illusion_hero": "illusion_count",
                "summon_hero": "summon_count",
                "mana_burn": "mana_burn_count",
                "armor_shred": "armor_shred_count",
                "burst": "burst_count",
                "global": "global_count",
                "evasion": "evasion_count",
                "heal": "heal_count",
            }

            for tag in tags.get("threat_tags", []):
                count_key = tag_to_count.get(tag)
                if count_key:
                    counts[count_key] += 1

                # Add to threat summary
                if tag == "gap_closer":
                    threat_summary.add("gap_closer")
                elif tag == "silence":
                    threat_summary.add("silence")
                elif tag == "invis":
                    threat_summary.add("invis_hero")
                elif tag == "illusion_hero":
                    threat_summary.add("illusion_hero")
                elif tag == "summon_hero":
                    threat_summary.add("summon_hero")
                elif tag == "mana_burn":
                    threat_summary.add("mana_burn")
                elif tag == "armor_shred":
                    threat_summary.add("armor_shred")
                elif tag in ("burst", "harass"):
                    threat_summary.add("magic_burst")
                elif tag == "evasion":
                    threat_summary.add("evasion_hero")
                elif tag == "heal":
                    threat_summary.add("heal_enemy")

            # Count disables
            disable_to_count = {
                "stun": "stun_count",
                "hex": "hex_count",
                "root": "root_count",
            }
            for dis in tags.get("disable_tags", []):
                counts["disable_count"] += 1
                count_key = disable_to_count.get(dis)
                if count_key:
                    counts[count_key] += 1
                threat_summary.add("disable_chain")

        # Generate warnings
        warnings = []
        for key, (threshold, message) in self.WARNING_THRESHOLDS.items():
            if counts.get(key, 0) >= threshold:
                warnings.append(message)

        return {
            "threat_summary": list(threat_summary),
            "hero_details": hero_details,
            "warnings": warnings,
            **counts,
        }
