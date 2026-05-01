"""Analyze enemy items for threats specific to your hero."""
import json
from pathlib import Path


class ItemThreatAnalyzer:
    """Scans enemy players' items and generates danger alerts for your hero.

    Uses data-driven rules from item_threats.json to match enemy items
    against hero-specific vulnerability tags.
    """

    def __init__(self, data_dir: str):
        data_path = Path(data_dir)
        threats_path = data_path / "item_threats.json"
        if threats_path.exists():
            with open(threats_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._rules = data.get("rules", [])
            self._hero_tags = data.get("hero_vulnerability_tags", {})
        else:
            self._rules = []
            self._hero_tags = {}

        # Load items.json for display names
        items_path = data_path / "items.json"
        if items_path.exists():
            with open(items_path, "r", encoding="utf-8") as f:
                self._items = json.load(f)
        else:
            self._items = {}

    def check_dangers(self, my_hero: str, enemy_players: list[dict]) -> list[dict]:
        """Check enemy items for threats to my hero.

        Args:
            my_hero: Internal hero ID (e.g., "drow_ranger")
            enemy_players: List of dicts with "hero", "hero_name", "items" keys

        Returns:
            List of alert dicts: {"message": str, "severity": str, "item": str, "heroes": [str]}
        """
        my_tags = set(self._hero_tags.get(my_hero, []))
        if not my_tags:
            return []

        alerts = []
        # Track aggregated items (like BKB count)
        aggregate_counts = {}  # rule_index -> [hero_names]

        for rule_idx, rule in enumerate(self._rules):
            target_item = rule["item"]
            trigger_tags = set(rule.get("triggers_for", {}).get("tags", []))

            # Check if this rule applies to my hero
            if not trigger_tags.intersection(my_tags):
                continue

            # Find enemies who have this item
            holders = []
            for enemy in enemy_players:
                if target_item in enemy.get("items", []):
                    holders.append(enemy.get("hero_name", enemy.get("hero", "Unknown")))

            if not holders:
                continue

            if rule.get("aggregate"):
                aggregate_counts[rule_idx] = holders
            else:
                for hero_name in holders:
                    alerts.append({
                        "message": f"{hero_name} has {self._item_display_name(target_item)} - {rule['message']}",
                        "severity": rule.get("severity", "medium"),
                        "item": target_item,
                        "heroes": [hero_name],
                    })

        # Process aggregated alerts
        for rule_idx, holders in aggregate_counts.items():
            rule = self._rules[rule_idx]
            threshold = rule.get("aggregate_threshold", 2)
            item_name = self._item_display_name(rule["item"])
            if len(holders) >= threshold:
                msg = rule.get("aggregate_message", rule["message"])
                msg = msg.replace("{count}", str(len(holders)))
                alerts.append({
                    "message": msg,
                    "severity": rule.get("severity", "medium"),
                    "item": rule["item"],
                    "heroes": holders,
                })
            else:
                # Below threshold, show individual alerts
                for hero_name in holders:
                    alerts.append({
                        "message": f"{hero_name} has {item_name} - {rule['message']}",
                        "severity": rule.get("severity", "medium"),
                        "item": rule["item"],
                        "heroes": [hero_name],
                    })

        # Sort: high severity first
        severity_order = {"high": 0, "medium": 1, "low": 2}
        alerts.sort(key=lambda a: severity_order.get(a["severity"], 2))

        return alerts

    def _item_display_name(self, item_id: str) -> str:
        """Get display name for an item ID."""
        info = self._items.get(item_id, {})
        return info.get("name", item_id.replace("_", " ").title())
