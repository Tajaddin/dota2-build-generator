"""Import match data from an external JSONL file (no API calls).

Use this to add bulk data from:
- Kaggle / other Dota 2 datasets (convert to our format first)
- OpenDota bulk dumps or saved API responses
- Any JSONL where each line is one match (our format or OpenDota format)

Our expected format per line (same as data_collector output):
  {"match_id": int, "duration": int, "radiant_win": bool, "players": [
    {"hero_id": int, "is_radiant": bool, "win": bool, "purchase_log": [{"item": str, "time": int}, ...]},
    ...
  ]}

OpenDota format is also accepted: "isRadiant", "purchase_log":[{"key": str, "time": int}];
we convert to our field names.
"""
import json
import sys
from pathlib import Path


def _convert_opendota_player(p: dict, radiant_win: bool) -> dict:
    """Convert one OpenDota API player dict to our format."""
    is_radiant = p.get("isRadiant", p.get("is_radiant", False))
    win = (is_radiant == radiant_win) if "win" not in p else p["win"]
    purchase_log = []
    for e in (p.get("purchase_log") or []):
        purchase_log.append({
            "item": e.get("key", e.get("item", "")),
            "time": e.get("time", 0),
        })
    items = []
    for slot in range(6):
        item_id = p.get(f"item_{slot}")
        if item_id and item_id > 0:
            items.append(item_id)
    return {
        "hero_id": p.get("hero_id"),
        "is_radiant": is_radiant,
        "win": win,
        "items": items,
        "purchase_log": purchase_log,
        "net_worth": p.get("net_worth", 0),
        "rank_tier": p.get("rank_tier", 0),
    }


def _normalize_match(obj: dict) -> dict | None:
    """Normalize to our format; accept our format or OpenDota API format."""
    players = obj.get("players", [])
    if len(players) != 10:
        return None
    radiant_win = obj.get("radiant_win", obj.get("radiant_win", False))
    # Already our format?
    if players and "purchase_log" in players[0] and isinstance(players[0]["purchase_log"], list):
        first_pl = players[0]["purchase_log"]
        if first_pl and "item" in first_pl[0]:
            return obj
    # OpenDota format: isRadiant, purchase_log with "key"
    converted = []
    for p in players:
        if not p.get("hero_id"):
            return None
        converted.append(_convert_opendota_player(p, radiant_win))
    return {
        "match_id": obj.get("match_id"),
        "duration": obj.get("duration", 0),
        "radiant_win": radiant_win,
        "avg_rank_tier": obj.get("avg_rank_tier", 0),
        "weight": obj.get("weight", 0.5),
        "patch": obj.get("patch", 0),
        "players": converted,
    }


def import_from_file(file_path: str, output_dir: str = "ml/raw_data", skip_existing: bool = True) -> int:
    """Append matches from a JSONL file to output_dir/matches.jsonl.

    Returns number of new matches appended.
    """
    path = Path(file_path)
    if not path.exists():
        print(f"[Import] File not found: {path}")
        return 0

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "matches.jsonl"

    existing_ids = set()
    if skip_existing and out_file.exists():
        with open(out_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    m = json.loads(line)
                    existing_ids.add(m.get("match_id"))
                except (json.JSONDecodeError, KeyError):
                    pass
        print(f"[Import] Found {len(existing_ids)} existing match IDs in {out_file}")

    added = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            mid = obj.get("match_id")
            if mid is not None and skip_existing and mid in existing_ids:
                continue
            norm = _normalize_match(obj)
            if not norm or len(norm.get("players", [])) != 10:
                continue
            with open(out_file, "a", encoding="utf-8") as out:
                out.write(json.dumps(norm) + "\n")
            added += 1
            if mid is not None:
                existing_ids.add(mid)
            if added % 500 == 0:
                print(f"[Import] Appended {added} matches...")

    print(f"[Import] Done. Appended {added} new matches to {out_file}")
    return added


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Import matches from a JSONL file into ml/raw_data/matches.jsonl (no API calls)"
    )
    parser.add_argument("file", help="Path to JSONL file (each line = one match, our or OpenDota format)")
    parser.add_argument("--output-dir", default="ml/raw_data", help="Directory for matches.jsonl")
    parser.add_argument("--no-skip", action="store_true", help="Do not skip match_ids already in output (will duplicate)")
    args = parser.parse_args()
    import_from_file(args.file, args.output_dir, skip_existing=not args.no_skip)


if __name__ == "__main__":
    main()
