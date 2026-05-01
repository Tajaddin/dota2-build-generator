"""Download hero and item icons from Valve CDN."""
import os
import sys
import requests
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from logic.data_loader import DataLoader

HERO_ICON_URL = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/{hero_id}.png"
ITEM_ICON_URL = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/items/{item_id}.png"


def download_file(url: str, dest: Path):
    """Download a file if it doesn't already exist."""
    if dest.exists():
        print(f"  SKIP {dest.name} (exists)")
        return True
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                f.write(resp.content)
            print(f"  OK   {dest.name}")
            return True
        else:
            print(f"  FAIL {dest.name} ({resp.status_code})")
            return False
    except Exception as e:
        print(f"  ERR  {dest.name}: {e}")
        return False


def main():
    base = Path(__file__).parent.parent
    loader = DataLoader(str(base / "data"))

    ok_count = 0
    fail_count = 0

    # Download hero icons
    print("Downloading hero icons...")
    hero_dir = base / "assets" / "hero_icons"
    hero_dir.mkdir(parents=True, exist_ok=True)
    for hero in loader.get_all_heroes():
        url = HERO_ICON_URL.format(hero_id=hero["id"])
        if download_file(url, hero_dir / f"{hero['id']}.png"):
            ok_count += 1
        else:
            fail_count += 1

    # Download item icons
    print("\nDownloading item icons...")
    item_dir = base / "assets" / "item_icons"
    item_dir.mkdir(parents=True, exist_ok=True)
    for item_id in loader.get_all_items():
        url = ITEM_ICON_URL.format(item_id=item_id)
        if download_file(url, item_dir / f"{item_id}.png"):
            ok_count += 1
        else:
            fail_count += 1

    print(f"\nDone! {ok_count} downloaded, {fail_count} failed.")


if __name__ == "__main__":
    main()
