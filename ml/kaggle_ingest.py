"""Ingest Kaggle OpenDota CSV dataset into training-ready matches.jsonl format."""
import ast
import csv
import json
import sys
from pathlib import Path
from collections import defaultdict

# Same rank weights as data_collector
RANK_WEIGHTS = {
    80: 1.0, 70: 0.9, 60: 0.8, 50: 0.6,
    40: 0.5, 30: 0.4, 20: 0.35, 10: 0.3,
}

csv.field_size_limit(10_000_000)


def ingest_kaggle(archive_dir: str, output_dir: str, years: list[str] = None):
    """Read Kaggle CSV files and produce matches.jsonl for training.

    Args:
        archive_dir: Path to data/archive/ containing year folders
        output_dir: Where to write matches.jsonl (e.g. ml/raw_data)
        years: List of year folders to process (e.g. ["2024", "2025", "202601"])
    """
    archive = Path(archive_dir)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    if years is None:
        # Auto-discover year folders
        years = sorted([
            d.name for d in archive.iterdir()
            if d.is_dir() and d.name[0].isdigit()
        ])

    print(f"[Kaggle] Processing folders: {years}")

    output_file = out_path / "matches.jsonl"
    existing_ids = set()
    if output_file.exists():
        with open(output_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    existing_ids.add(json.loads(line)["match_id"])
                except (json.JSONDecodeError, KeyError):
                    pass
        print(f"[Kaggle] {len(existing_ids)} matches already in output")

    total_matches = 0
    total_written = 0

    for year in years:
        year_dir = archive / year
        players_file = year_dir / "players.csv"
        meta_file = year_dir / "main_metadata.csv"

        if not players_file.exists():
            print(f"[Kaggle] Skipping {year}: no players.csv")
            continue

        # Load metadata (match_id -> duration, radiant_win)
        meta = {}
        if meta_file.exists():
            with open(meta_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        mid = int(row["match_id"])
                        meta[mid] = {
                            "duration": int(float(row.get("duration", 0))),
                            "radiant_win": row.get("radiant_win", "").strip().lower() == "true",
                        }
                    except (ValueError, KeyError):
                        pass

        # Group players by match_id
        matches = defaultdict(list)
        print(f"[Kaggle] Reading {year}/players.csv...")
        with open(players_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    mid = int(row["match_id"])
                    matches[mid].append(row)
                except (ValueError, KeyError):
                    pass

        print(f"[Kaggle] {year}: {len(matches)} matches found")

        written = 0
        with open(output_file, "a", encoding="utf-8") as out_f:
            for match_id, players in matches.items():
                if match_id in existing_ids:
                    continue
                if len(players) != 10:
                    continue

                match_meta = meta.get(match_id, {})
                duration = match_meta.get("duration", 0)
                if duration < 900:
                    continue

                radiant_win = match_meta.get("radiant_win", False)

                # Get rank info
                rank_tiers = []
                for p in players:
                    rt = p.get("rank_tier", "")
                    if rt and rt.strip():
                        try:
                            rank_tiers.append(int(float(rt)))
                        except ValueError:
                            pass

                avg_rank = int(sum(rank_tiers) / len(rank_tiers)) if rank_tiers else 0
                rank_bucket = (avg_rank // 10) * 10
                weight = RANK_WEIGHTS.get(rank_bucket, 0.3)

                player_data = []
                for p in players:
                    hero_id = 0
                    try:
                        hero_id = int(float(p.get("hero_id", 0)))
                    except ValueError:
                        pass
                    if not hero_id:
                        continue

                    slot = int(float(p.get("player_slot", 0)))
                    is_radiant = slot < 128

                    # Final items
                    items = []
                    for i in range(6):
                        item_id = 0
                        try:
                            item_id = int(float(p.get(f"item_{i}", 0)))
                        except ValueError:
                            pass
                        if item_id > 0:
                            items.append(item_id)

                    # Purchase log
                    purchase_log = []
                    raw_log = p.get("purchase_log", "")
                    if raw_log and raw_log.strip():
                        try:
                            log_list = ast.literal_eval(raw_log)
                            if isinstance(log_list, list):
                                for entry in log_list:
                                    if isinstance(entry, dict):
                                        purchase_log.append({
                                            "item": entry.get("key", ""),
                                            "time": entry.get("time", 0),
                                        })
                        except (ValueError, SyntaxError):
                            pass

                    win_val = p.get("win", "")
                    try:
                        won = float(win_val) > 0.5
                    except (ValueError, TypeError):
                        won = is_radiant == radiant_win

                    player_data.append({
                        "hero_id": hero_id,
                        "is_radiant": is_radiant,
                        "win": won,
                        "items": items,
                        "purchase_log": purchase_log,
                        "net_worth": 0,
                        "rank_tier": avg_rank,
                    })

                if len(player_data) != 10:
                    continue

                match_data = {
                    "match_id": match_id,
                    "duration": duration,
                    "radiant_win": radiant_win,
                    "avg_rank_tier": avg_rank,
                    "weight": weight,
                    "patch": 0,
                    "players": player_data,
                }

                out_f.write(json.dumps(match_data) + "\n")
                out_f.flush()
                existing_ids.add(match_id)
                written += 1

        total_matches += len(matches)
        total_written += written
        print(f"[Kaggle] {year}: wrote {written} new matches")

    print(f"\n[Kaggle] Done! {total_written} new matches written from {total_matches} total")
    print(f"[Kaggle] Total in {output_file}: {len(existing_ids)} matches")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Ingest Kaggle OpenDota dataset")
    parser.add_argument("--archive", default="data/archive", help="Path to archive directory")
    parser.add_argument("--output", default="ml/raw_data", help="Output directory")
    parser.add_argument("--years", nargs="*", default=None, help="Year folders to process")
    args = parser.parse_args()
    ingest_kaggle(args.archive, args.output, args.years)


if __name__ == "__main__":
    main()
