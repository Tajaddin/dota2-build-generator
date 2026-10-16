"""Marker for tests that need the hero dataset in data/.

data/items.json, data/hero_id_map.json and data/hero_tags.json are curated
locally and not committed (see .gitignore), so a fresh clone skips these tests
instead of failing them.
"""

from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REQUIRED = ("items.json", "hero_id_map.json", "hero_tags.json")
MISSING = [name for name in REQUIRED if not (DATA_DIR / name).exists()]

requires_dataset = pytest.mark.skipif(
    bool(MISSING),
    reason=f"needs the local hero dataset in data/ (missing: {', '.join(MISSING)})",
)
