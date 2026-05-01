"""Fetch comprehensive item and matchup data from OpenDota API.

Downloads:
1. Item constants (numeric ID to name mapping)
2. Hero stats (all heroes with their IDs)
3. Item popularity per hero (what items are actually built in each game phase)
4. Matchup win rates (how each hero performs against every other hero)

This data powers the "immortal-level" recommendation engine by using
real statistical data instead of just heuristic rules.

Usage:
    python scripts/fetch_opendota.py

Rate limiting: OpenDota allows 60 requests/min without API key.
Full fetch takes ~5 minutes for all 124 heroes.
"""

import json
import time
import sys
import os
import requests
from pathlib import Path

OPENDOTA_BASE = "https://api.opendota.com/api"
REQUEST_DELAY = 1.1  # seconds between requests (stay under 60/min)

# Output directory
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
OPENDOTA_DIR = DATA_DIR / "opendota"


def fetch_json(url: str, retries: int = 3) -> dict:
    """Fetch JSON from URL with retries and rate limiting."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=20)
            if resp.status_code == 429:
                print(f"  Rate limited, waiting 30s...")
                time.sleep(30)
                continue
            if resp.status_code == 200:
                return resp.json()
            else:
                print(f"  HTTP {resp.status_code} for {url}")
                time.sleep(5)
        except requests.RequestException as e:
            print(f"  Request error: {e}")
            time.sleep(5)
    return None


def fetch_item_constants():
    """Fetch OpenDota item constants and build ID-to-name mapping."""
    print("[1/4] Fetching item constants...")
    data = fetch_json(f"{OPENDOTA_BASE}/constants/items")
    if not data:
        print("  FAILED to fetch item constants!")
        return {}

    # Build numeric ID -> item_key mapping
    id_to_name = {}
    item_details = {}
    for item_key, item_data in data.items():
        if isinstance(item_data, dict) and "id" in item_data:
            item_id = item_data["id"]
            id_to_name[str(item_id)] = item_key
            item_details[item_key] = {
                "id": item_id,
                "dname": item_data.get("dname", item_key),
                "cost": item_data.get("cost", 0),
                "components": item_data.get("components", None),
                "tier": item_data.get("tier"),
            }

    result = {"id_to_name": id_to_name, "items": item_details}

    out_path = OPENDOTA_DIR / "item_constants.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"  Saved {len(id_to_name)} items to {out_path}")
    time.sleep(REQUEST_DELAY)
    return result


def fetch_hero_list():
    """Fetch all heroes with their IDs."""
    print("[2/4] Fetching hero list...")
    data = fetch_json(f"{OPENDOTA_BASE}/heroStats")
    if not data:
        print("  FAILED to fetch hero stats!")
        return []

    heroes = []
    for h in data:
        hero = {
            "id": h["id"],
            "name": h.get("localized_name", ""),
            "npc_name": h.get("name", ""),  # e.g., "npc_dota_hero_antimage"
            "primary_attr": h.get("primary_attr", ""),
            "attack_type": h.get("attack_type", ""),
            "roles": h.get("roles", []),
            "pro_pick": h.get("pro_pick", 0),
            "pro_win": h.get("pro_win", 0),
            # Win rates by bracket (1=Herald to 8=Immortal)
            "bracket_wins": {
                str(i): h.get(f"{i}_win", 0)
                for i in range(1, 9)
            },
            "bracket_picks": {
                str(i): h.get(f"{i}_pick", 0)
                for i in range(1, 9)
            },
        }
        heroes.append(hero)

    out_path = OPENDOTA_DIR / "hero_stats.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(heroes, f, indent=2)

    print(f"  Saved {len(heroes)} heroes to {out_path}")
    time.sleep(REQUEST_DELAY)
    return heroes


def fetch_item_popularity(heroes: list, item_constants: dict):
    """Fetch item popularity for every hero."""
    print(f"[3/4] Fetching item popularity for {len(heroes)} heroes...")
    id_to_name = item_constants.get("id_to_name", {})

    # Load our items database to know which are "final" items
    our_items_path = DATA_DIR / "items.json"
    if our_items_path.exists():
        with open(our_items_path, "r") as f:
            our_items = json.load(f)
        our_item_names = set(our_items.keys())
    else:
        our_item_names = set()

    # Also consider items from item_tags.json
    item_tags_path = DATA_DIR / "item_tags.json"
    if item_tags_path.exists():
        with open(item_tags_path, "r") as f:
            item_tags = json.load(f)
        our_item_names.update(item_tags.keys())

    all_popularity = {}
    total = len(heroes)

    for i, hero in enumerate(heroes):
        hero_id = hero["id"]
        npc = hero["npc_name"].replace("npc_dota_hero_", "")
        sys.stdout.write(f"\r  [{i+1}/{total}] {npc:25s}")
        sys.stdout.flush()

        data = fetch_json(f"{OPENDOTA_BASE}/heroes/{hero_id}/itemPopularity")
        if not data:
            time.sleep(REQUEST_DELAY)
            continue

        hero_items = {}
        for phase, items_dict in data.items():
            if not isinstance(items_dict, dict):
                continue

            # Convert numeric IDs to names, filter to known final items
            phase_items = []
            total_count = sum(items_dict.values())

            for item_id_str, count in items_dict.items():
                item_name = id_to_name.get(item_id_str)
                if not item_name:
                    continue

                # Remove "item_" prefix if present
                clean_name = item_name.replace("item_", "")

                # Calculate popularity percentage
                pct = (count / total_count * 100) if total_count > 0 else 0

                phase_items.append({
                    "item": clean_name,
                    "count": count,
                    "pct": round(pct, 1),
                })

            # Sort by count descending
            phase_items.sort(key=lambda x: x["count"], reverse=True)
            hero_items[phase] = phase_items

        all_popularity[npc] = hero_items
        time.sleep(REQUEST_DELAY)

    print(f"\n  Saved popularity data for {len(all_popularity)} heroes")

    out_path = OPENDOTA_DIR / "item_popularity.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_popularity, f, indent=2)

    return all_popularity


def fetch_matchups(heroes: list):
    """Fetch matchup win rates for every hero."""
    print(f"[4/4] Fetching matchup data for {len(heroes)} heroes...")

    # Build hero_id -> npc_name mapping
    id_to_npc = {}
    for h in heroes:
        npc = h["npc_name"].replace("npc_dota_hero_", "")
        id_to_npc[h["id"]] = npc

    all_matchups = {}
    total = len(heroes)

    for i, hero in enumerate(heroes):
        hero_id = hero["id"]
        npc = hero["npc_name"].replace("npc_dota_hero_", "")
        sys.stdout.write(f"\r  [{i+1}/{total}] {npc:25s}")
        sys.stdout.flush()

        data = fetch_json(f"{OPENDOTA_BASE}/heroes/{hero_id}/matchups")
        if not data:
            time.sleep(REQUEST_DELAY)
            continue

        matchups = {}
        for m in data:
            enemy_id = m.get("hero_id")
            games = m.get("games_played", 0)
            wins = m.get("wins", 0)
            if games < 10:  # Skip very low sample sizes
                continue

            enemy_npc = id_to_npc.get(enemy_id, str(enemy_id))
            win_rate = (wins / games) if games > 0 else 0.5
            # Store as advantage (>0.5 = good matchup, <0.5 = bad matchup)
            matchups[enemy_npc] = {
                "games": games,
                "wins": wins,
                "win_rate": round(win_rate, 4),
                "advantage": round(win_rate - 0.5, 4),  # positive = good for us
            }

        all_matchups[npc] = matchups
        time.sleep(REQUEST_DELAY)

    print(f"\n  Saved matchup data for {len(all_matchups)} heroes")

    out_path = OPENDOTA_DIR / "matchups.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_matchups, f, indent=2)

    return all_matchups


def build_training_data(item_pop: dict, matchups: dict, item_constants: dict):
    """Build the final optimized training data used by the recommender.

    Creates a compact format that maps:
    hero -> phase -> ranked list of items with scores
    hero -> bad_matchups -> items that help in those matchups
    """
    print("\n[BUILD] Creating optimized recommendation data...")

    # Load our item database
    our_items = set()
    items_path = DATA_DIR / "items.json"
    if items_path.exists():
        with open(items_path, "r") as f:
            our_items = set(json.load(f).keys())

    item_tags_path = DATA_DIR / "item_tags.json"
    if item_tags_path.exists():
        with open(item_tags_path, "r") as f:
            our_items.update(json.load(f).keys())

    # Phase mapping from OpenDota to our phases
    phase_map = {
        "start_game_items": "early_game",
        "early_game_items": "early_game",
        "mid_game_items": "mid_game",
        "late_game_items": "late_game",
    }

    trained_builds = {}

    for hero_npc, phases in item_pop.items():
        hero_data = {"early_game": [], "mid_game": [], "late_game": []}

        for opendota_phase, items_list in phases.items():
            our_phase = phase_map.get(opendota_phase)
            if not our_phase:
                continue

            for item_entry in items_list:
                item_name = item_entry["item"]
                pct = item_entry["pct"]

                # Only include items we recognize as final/buildable items
                if item_name in our_items:
                    # Avoid duplicates in same phase
                    existing = {x["item"] for x in hero_data[our_phase]}
                    if item_name not in existing:
                        hero_data[our_phase].append({
                            "item": item_name,
                            "popularity": pct,
                        })

        # Sort each phase by popularity
        for phase in hero_data:
            hero_data[phase].sort(key=lambda x: x["popularity"], reverse=True)
            # Keep top 15 per phase (more than 6 so the matcher has options)
            hero_data[phase] = hero_data[phase][:15]

        trained_builds[hero_npc] = hero_data

    # Add matchup-specific item adjustments
    # For each hero, find their worst matchups and what items help
    matchup_items = {}
    for hero_npc, hero_matchups in matchups.items():
        # Find worst matchups (lowest win rate)
        worst = sorted(
            hero_matchups.items(),
            key=lambda x: x[1]["advantage"]
        )[:10]  # Bottom 10 matchups

        matchup_items[hero_npc] = {
            "worst_matchups": [
                {"enemy": enemy, "advantage": data["advantage"], "games": data["games"]}
                for enemy, data in worst
            ],
        }

    result = {
        "builds": trained_builds,
        "matchup_data": matchup_items,
        "meta": {
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "hero_count": len(trained_builds),
            "source": "OpenDota API (api.opendota.com)",
        }
    }

    out_path = OPENDOTA_DIR / "trained_data.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"  Trained data: {len(trained_builds)} heroes with builds")
    print(f"  Matchup data: {len(matchup_items)} heroes with matchup info")
    print(f"  Saved to {out_path}")

    return result


def main():
    # Create output directory
    OPENDOTA_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  DOTA 2 BUILD GENERATOR - DATA TRAINING PIPELINE")
    print("  Fetching real statistical data from OpenDota API")
    print("=" * 60)
    print()

    start_time = time.time()

    # Step 1: Item constants
    item_constants = fetch_item_constants()
    if not item_constants:
        print("FATAL: Could not fetch item constants. Aborting.")
        sys.exit(1)

    # Step 2: Hero list
    heroes = fetch_hero_list()
    if not heroes:
        print("FATAL: Could not fetch hero list. Aborting.")
        sys.exit(1)

    # Step 3: Item popularity for all heroes
    item_pop = fetch_item_popularity(heroes, item_constants)

    # Step 4: Matchup data for all heroes
    matchup_data = fetch_matchups(heroes)

    # Step 5: Build optimized training data
    trained = build_training_data(item_pop, matchup_data, item_constants)

    elapsed = time.time() - start_time
    print()
    print("=" * 60)
    print(f"  TRAINING COMPLETE in {elapsed/60:.1f} minutes")
    print(f"  Heroes: {trained['meta']['hero_count']}")
    print(f"  Data saved to: {OPENDOTA_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
