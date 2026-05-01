"""Validate all hero and item data for correctness."""
import json
import sys
from pathlib import Path


def validate():
    data_dir = Path(__file__).parent.parent / "data"
    errors = []
    warnings = []

    # Load items
    items_path = data_dir / "items.json"
    if not items_path.exists():
        print("ERROR: items.json not found!")
        sys.exit(1)

    with open(items_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    print(f"Loaded {len(items)} items from items.json")

    # Validate each hero
    heroes_dir = data_dir / "heroes"
    if not heroes_dir.exists():
        print("ERROR: heroes/ directory not found!")
        sys.exit(1)

    hero_ids = set()
    hero_count = 0
    build_count = 0

    for hero_file in sorted(heroes_dir.glob("*.json")):
        with open(hero_file, "r", encoding="utf-8") as f:
            try:
                hero = json.load(f)
            except json.JSONDecodeError as e:
                errors.append(f"{hero_file.name}: Invalid JSON - {e}")
                continue

        hid = hero.get("id", "MISSING")
        name = hero.get("name", "MISSING")
        hero_count += 1

        # Required top-level fields
        for field in ["id", "name", "primary_attr", "roles", "counters", "good_against", "builds"]:
            if field not in hero:
                errors.append(f"{hid}: missing top-level field '{field}'")

        # Check primary_attr value
        if hero.get("primary_attr") not in ("agi", "str", "int", "uni"):
            errors.append(f"{hid}: primary_attr must be agi/str/int/uni, got '{hero.get('primary_attr')}'")

        # Duplicate check
        if hid in hero_ids:
            errors.append(f"{hid}: duplicate hero ID")
        hero_ids.add(hid)

        # Check filename matches id
        expected_filename = f"{hid}.json"
        if hero_file.name != expected_filename:
            warnings.append(f"{hid}: filename is '{hero_file.name}' but expected '{expected_filename}'")

        # Validate builds
        builds = hero.get("builds", {})
        if len(builds) < 2:
            errors.append(f"{hid}: expected at least 2 builds, got {len(builds)}")

        for build_key, build in builds.items():
            prefix = f"{hid}/{build_key}"
            build_count += 1

            # Required build fields
            for field in ["label", "early_game", "mid_game", "late_game", "skill_build", "strategy"]:
                if field not in build:
                    errors.append(f"{prefix}: missing field '{field}'")

            # Validate item phases
            for phase in ["early_game", "mid_game", "late_game"]:
                phase_items = build.get(phase, [])
                if len(phase_items) != 6:
                    errors.append(f"{prefix}/{phase}: expected 6 items, got {len(phase_items)}")

                for idx, item_entry in enumerate(phase_items):
                    if not isinstance(item_entry, dict):
                        errors.append(f"{prefix}/{phase}[{idx}]: expected dict, got {type(item_entry).__name__}")
                        continue

                    item_id = item_entry.get("item", "")
                    if not item_id:
                        errors.append(f"{prefix}/{phase}[{idx}]: empty item ID")
                    elif item_id not in items:
                        errors.append(f"{prefix}/{phase}[{idx}]: unknown item '{item_id}'")

            # Validate skill build
            skill = build.get("skill_build", {})
            if isinstance(skill, dict):
                order = skill.get("order", [])
                if len(order) != 20:
                    errors.append(f"{prefix}/skill_build: expected 20 entries, got {len(order)}")
                for idx, s in enumerate(order):
                    if s not in ("Q", "W", "E", "R", "T"):
                        errors.append(f"{prefix}/skill_build[{idx}]: invalid skill '{s}'")
            else:
                errors.append(f"{prefix}/skill_build: expected dict with 'order' and 'notes'")

    # Summary
    print(f"\nValidated {hero_count} heroes with {build_count} total builds")

    if warnings:
        print(f"\n{len(warnings)} WARNINGS:")
        for w in warnings:
            print(f"  ! {w}")

    if errors:
        print(f"\n{len(errors)} ERRORS:")
        for e in errors:
            print(f"  X {e}")
        sys.exit(1)
    else:
        print("\nALL VALID!")


if __name__ == "__main__":
    validate()
