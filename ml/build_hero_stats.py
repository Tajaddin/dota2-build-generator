"""Extract per-hero item build statistics from raw match data.

Builds two things:
1. hero_item_stats.json — per-hero final item frequencies and win rates
2. hero_build_orders.json — per-hero common build progressions

Uses FINAL INVENTORIES (not purchase log components) to determine what
completed items each hero actually builds. Uses purchase log timestamps
to determine build order (early/mid/late phasing).
"""
import json
import sys
from collections import defaultdict
from pathlib import Path


# Items under this cost are components/consumables, skip for final build stats
COMPONENT_COST_THRESHOLD = 1000

# Phase time boundaries (seconds)
EARLY_END = 900     # 15 min
MID_END = 1800      # 30 min


def load_item_map(data_dir: Path) -> dict:
    """Load numeric item ID -> item name mapping."""
    path = data_dir / "opendota_item_ids.json"
    if path.exists():
        return json.load(open(path))
    return {}


def load_items_json(data_dir: Path) -> dict:
    """Load items.json for cost/name data."""
    path = data_dir / "items.json"
    if path.exists():
        return json.load(open(path))
    return {}


def extract_hero_stats(matches_path: str, data_dir: str, output_dir: str,
                       min_games: int = 30):
    data = Path(data_dir)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    hero_id_map = json.load(open(data / "hero_id_map.json"))
    hero_id_to_name = hero_id_map.get("hero_id_to_name", {})
    valve_to_internal = hero_id_map.get("valve_to_internal", {})
    item_id_map = load_item_map(data)
    items_json = load_items_json(data)

    def resolve_item_name(item_id):
        """Convert numeric item ID to string name."""
        name = item_id_map.get(str(item_id), "")
        return name if name else ""

    def get_item_cost(item_name):
        return items_json.get(item_name, {}).get("cost", 0)

    def is_real_item(item_name):
        """Is this a completed/meaningful item (not a cheap component)?"""
        if not item_name or item_name.startswith("recipe_"):
            return False
        cost = get_item_cost(item_name)
        return cost >= COMPONENT_COST_THRESHOLD

    def hero_name(hid):
        valve = hero_id_to_name.get(str(hid), "")
        internal = valve_to_internal.get(valve, valve)
        return internal if internal else valve

    # Tracking structures
    # hero -> item -> {"wins": int, "total": int}
    final_items = defaultdict(lambda: defaultdict(lambda: {"wins": 0, "total": 0}))
    # hero -> phase -> item -> {"wins": int, "total": int}
    phase_items = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {"wins": 0, "total": 0})))
    # hero -> total games
    hero_games = defaultdict(int)

    match_count = 0
    with open(matches_path) as f:
        for line in f:
            match = json.loads(line)
            duration = match.get("duration", 0)
            if duration < 900:  # Skip very short games
                continue

            match_count += 1

            for player in match.get("players", []):
                hid = player.get("hero_id")
                if not hid:
                    continue
                hname = hero_name(hid)
                if not hname or hname.startswith("unknown"):
                    continue

                won = player.get("win", False)
                hero_games[hname] += 1

                # --- FINAL INVENTORY ITEMS ---
                inventory = player.get("items", [])
                for item_id in inventory:
                    if not item_id:
                        continue
                    iname = resolve_item_name(item_id)
                    if not iname or not is_real_item(iname):
                        continue
                    final_items[hname][iname]["total"] += 1
                    if won:
                        final_items[hname][iname]["wins"] += 1

                # --- PURCHASE LOG PHASED ITEMS ---
                purchase_log = player.get("purchase_log") or []
                seen_in_phase = {"early": set(), "mid": set(), "late": set()}

                for entry in purchase_log:
                    iname = entry.get("item", "")
                    t = entry.get("time", 0)

                    if not iname or not is_real_item(iname):
                        continue

                    if t <= EARLY_END:
                        phase = "early"
                    elif t <= MID_END:
                        phase = "mid"
                    else:
                        phase = "late"

                    # Only count first purchase per item per phase
                    if iname not in seen_in_phase[phase]:
                        seen_in_phase[phase].add(iname)
                        phase_items[hname][phase][iname]["total"] += 1
                        if won:
                            phase_items[hname][phase][iname]["wins"] += 1

            if match_count % 10000 == 0:
                print(f"  Processed {match_count:,} matches...")

    print(f"  Total: {match_count:,} matches, {len(hero_games)} heroes")

    # --- BUILD hero_item_stats.json ---
    result = {}
    for hname in sorted(hero_games.keys()):
        total = hero_games[hname]
        if total < min_games:
            continue

        hero_data = {"games": total}

        # Final items (what the hero ends the game with)
        finals = []
        for iname, stats in final_items[hname].items():
            if stats["total"] < 5:
                continue
            rate = stats["total"] / total
            wr = stats["wins"] / stats["total"] if stats["total"] > 0 else 0.5
            finals.append({
                "item": iname,
                "rate": round(rate, 4),
                "win_rate": round(wr, 4),
                "count": stats["total"],
            })
        finals.sort(key=lambda x: x["rate"], reverse=True)
        hero_data["final_items"] = finals[:20]

        # Phase-specific items (from purchase timestamps)
        for phase in ["early", "mid", "late"]:
            pitems = []
            for iname, stats in phase_items[hname].get(phase, {}).items():
                if stats["total"] < 5:
                    continue
                rate = stats["total"] / total
                wr = stats["wins"] / stats["total"] if stats["total"] > 0 else 0.5
                pitems.append({
                    "item": iname,
                    "rate": round(rate, 4),
                    "win_rate": round(wr, 4),
                    "count": stats["total"],
                })
            # Sort by: win_rate * rate (items that are both common AND winning)
            pitems.sort(key=lambda x: x["win_rate"] * x["rate"], reverse=True)
            hero_data[phase] = pitems[:15]

        result[hname] = hero_data

    # Save
    stats_path = out / "hero_item_stats.json"
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"\nSaved {len(result)} heroes to {stats_path}")

    # Print samples
    for sample in ["life_stealer", "shadow_fiend", "drow_ranger", "phantom_assassin"]:
        if sample not in result:
            # Try valve name
            for hname, hdata in result.items():
                if sample in hname or hname in sample:
                    sample = hname
                    break
        if sample not in result:
            print(f"\n{sample}: not found")
            continue
        hdata = result[sample]
        print(f"\n=== {sample} ({hdata['games']} games) ===")
        finals_str = ", ".join(
            f"{i['item']}({i['rate']:.0%})" for i in hdata["final_items"][:6]
        )
        print(f"  Final items: {finals_str}")
        for phase in ["early", "mid", "late"]:
            top = hdata.get(phase, [])[:5]
            phase_str = ", ".join(
                f"{i['item']}({i['rate']:.0%},wr{i['win_rate']:.0%})" for i in top
            )
            print(f"  {phase}: {phase_str}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Extract per-hero item statistics")
    parser.add_argument("--matches", default="ml/raw_data/matches.jsonl")
    parser.add_argument("--data", default="data")
    parser.add_argument("--output", default="models")
    args = parser.parse_args()

    print("Extracting hero item statistics from match data...")
    extract_hero_stats(args.matches, args.data, args.output)
