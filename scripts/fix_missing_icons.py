"""Fix missing icons by downloading with correct Valve CDN names."""
import requests
from pathlib import Path

BASE_HERO = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/{}.png"
BASE_ITEM = "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/items/{}.png"

base = Path(__file__).parent.parent

# Hero name mappings (our_id -> valve_cdn_id)
HERO_FIXES = {
    "anti_mage": "antimage",
    "lifestealer": "life_stealer",
    "queen_of_pain": "queenofpain",
    "shadow_fiend": "nevermore",
    "wraith_king": "skeleton_king",
    "zeus": "zuus",
}

# Item name mappings (our_id -> valve_cdn_id)
ITEM_FIXES = {
    "healing_salve": "flask",
    "boots_of_travel": "travel_boots",
    "boots_of_travel_2": "travel_boots_2",
    "daedalus": "greater_crit",
    "shadow_blade": "invis_sword",
    "linken_sphere": "sphere",
    "euls": "cyclone",
    "gleipnir": "gungir",
    "mask_of_death": "lifesteal",
    "scythe_of_vyse": "sheepstick",
}

def download(url, dest):
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                f.write(r.content)
            print(f"  OK   {dest.name} <- {url.split('/')[-1]}")
            return True
        else:
            print(f"  FAIL {dest.name} ({r.status_code}) <- {url}")
            return False
    except Exception as e:
        print(f"  ERR  {dest.name}: {e}")
        return False

print("Fixing hero icons...")
for our_id, cdn_id in HERO_FIXES.items():
    dest = base / "assets" / "hero_icons" / f"{our_id}.png"
    if not dest.exists():
        download(BASE_HERO.format(cdn_id), dest)
    else:
        print(f"  SKIP {our_id}.png (exists)")

print("\nFixing item icons...")
for our_id, cdn_id in ITEM_FIXES.items():
    dest = base / "assets" / "item_icons" / f"{our_id}.png"
    if not dest.exists():
        download(BASE_ITEM.format(cdn_id), dest)
    else:
        print(f"  SKIP {our_id}.png (exists)")

# Check for remaining missing items that might be newer
still_missing = ["parasma", "khanda", "perseverance", "ward_observer_placeholder"]
print("\nStill missing (newer items without CDN icons):")
for item_id in still_missing:
    dest = base / "assets" / "item_icons" / f"{item_id}.png"
    if not dest.exists():
        print(f"  MISSING {item_id}.png (no known CDN name)")

print("\nDone!")
