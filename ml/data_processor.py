"""Process raw match data into training snapshots."""
import json
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional


# Item ID to name mapping (loaded from Dota 2 item data)
# OpenDota uses numeric item IDs; we need a mapping file
SNAPSHOT_TIMES = [0, 600, 1200, 1800, 2400]  # 0, 10, 20, 30, 40 minutes in seconds


class DataProcessor:
    """Converts raw match data into training-ready snapshots."""

    def __init__(self, data_dir: str, item_id_map: Optional[dict] = None):
        self.data_dir = Path(data_dir)
        self.item_id_map = item_id_map or {}

    def process_matches(self, input_path: str, output_dir: str):
        """Process raw matches.jsonl into training snapshots.

        Creates one Parquet file per snapshot type (draft, early, mid, late).
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        snapshots = {"draft": [], "early": [], "mid": [], "late": []}
        match_count = 0

        with open(input_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    match = json.loads(line)
                except json.JSONDecodeError:
                    continue

                match_snapshots = self._process_single_match(match)
                for phase, rows in match_snapshots.items():
                    snapshots[phase].extend(rows)

                match_count += 1
                if match_count % 1000 == 0:
                    print(f"[Processor] Processed {match_count} matches, "
                          f"snapshots: {', '.join(f'{k}={len(v)}' for k, v in snapshots.items())}")

        # Save as Parquet
        for phase, rows in snapshots.items():
            if not rows:
                continue
            df = pd.DataFrame(rows)
            out_file = output_path / f"snapshots_{phase}.parquet"
            df.to_parquet(out_file, index=False)
            print(f"[Processor] Saved {len(df)} {phase} snapshots to {out_file}")

        print(f"[Processor] Done! {match_count} matches -> "
              f"{sum(len(v) for v in snapshots.values())} total snapshots")

    def _process_single_match(self, match: dict) -> dict:
        """Extract training snapshots from a single match."""
        result = {"draft": [], "early": [], "mid": [], "late": []}
        players = match.get("players", [])
        if len(players) != 10:
            return result

        weight = match.get("weight", 0.5)
        duration = match.get("duration", 0)

        # Separate teams
        radiant = [p for p in players if p.get("is_radiant")]
        dire = [p for p in players if not p.get("is_radiant")]
        if len(radiant) != 5 or len(dire) != 5:
            return result

        # Extract hero IDs for both teams
        radiant_heroes = [p["hero_id"] for p in radiant]
        dire_heroes = [p["hero_id"] for p in dire]

        # Build purchase timelines for each player
        for player in players:
            is_radiant = player.get("is_radiant", False)
            won = player.get("win", False)
            hero_id = player["hero_id"]
            purchase_log = player.get("purchase_log", [])

            # My team and enemy team
            if is_radiant:
                allies = radiant_heroes
                enemies = dire_heroes
                ally_players = radiant
                enemy_players = dire
            else:
                allies = dire_heroes
                enemies = radiant_heroes
                ally_players = dire
                enemy_players = radiant

            # Draft snapshot (no items yet)
            base_row = {
                "hero_id": hero_id,
                "ally_heroes": allies,
                "enemy_heroes": enemies,
                "won": won,
                "weight": weight,
            }

            if purchase_log:
                # Draft snapshot: predict starting items
                starting_items = [e["item"] for e in purchase_log if e["time"] <= 0]
                if starting_items:
                    row = {**base_row, "label_items": starting_items,
                           "game_time": 0, "my_items": [], "ally_items": [[] for _ in range(5)],
                           "enemy_items": [[] for _ in range(5)]}
                    result["draft"].append(row)

                # Time-based snapshots
                phase_map = {600: "early", 1200: "mid", 1800: "mid", 2400: "late"}
                for snap_time, phase in phase_map.items():
                    if duration < snap_time:
                        continue

                    # Items this player has at snap_time
                    my_items_at_time = [e["item"] for e in purchase_log if e["time"] <= snap_time]

                    # Items all allies have at snap_time
                    ally_items = []
                    for ap in ally_players:
                        ap_items = [e["item"] for e in (ap.get("purchase_log") or [])
                                    if e["time"] <= snap_time]
                        ally_items.append(ap_items[-6:] if len(ap_items) > 6 else ap_items)

                    # Items all enemies have at snap_time
                    enemy_items = []
                    for ep in enemy_players:
                        ep_items = [e["item"] for e in (ep.get("purchase_log") or [])
                                    if e["time"] <= snap_time]
                        enemy_items.append(ep_items[-6:] if len(ep_items) > 6 else ep_items)

                    # Label: next items purchased after this specific snapshot.
                    next_items = [
                        e["item"]
                        for e in purchase_log
                        if e["time"] > snap_time and e["time"] <= snap_time + 600
                    ]
                    if next_items:
                        row_weight = weight if won else weight * 0.35  # Losers add variety, lower weight
                        row = {
                            **base_row,
                            "game_time": snap_time,
                            "my_items": my_items_at_time[-6:],
                            "ally_items": ally_items,
                            "enemy_items": enemy_items,
                            "label_items": next_items[:3],  # Next 1-3 items
                            "weight": row_weight,
                        }
                        result[phase].append(row)

        return result


def main():
    """CLI entry point for data processing."""
    import argparse
    parser = argparse.ArgumentParser(description="Process match data into training snapshots")
    parser.add_argument("--input", default="ml/raw_data/matches.jsonl", help="Input matches file")
    parser.add_argument("--output", default="ml/processed", help="Output directory")
    args = parser.parse_args()

    processor = DataProcessor("data")
    processor.process_matches(args.input, args.output)


if __name__ == "__main__":
    main()
