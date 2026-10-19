"""Loads the data files and exposes typed views of them.

Each file can come from the committed snapshot or from the user data folder (after ``d2bg data
refresh``); the newer one by its manifest timestamp wins, per file. Curated knowledge files (aliases,
counter-item rules, timer rules, trait overrides) always come from ``data/knowledge``.
"""

from __future__ import annotations

import gzip
import json
import threading
from functools import cached_property
from pathlib import Path
from typing import Any

from d2bg import paths
from d2bg.knowledge.heroes import HeroIndex
from d2bg.knowledge.items import ItemIndex

DATA_FILES = (
    "heroes.json",
    "abilities.json",
    "items.json",
    "patches.json",
    "ids.json",
    "hero_stats.json",
    "matchups.json",
    "item_popularity.json",
    "benchmarks.json",
    "item_timings.json",
    "lane_roles.json",
    "pro_builds.json",
    "draft_model.json",
    "public_matches.jsonl.gz",
)
OPTIONAL = {
    "item_popularity.json",
    "benchmarks.json",
    "item_timings.json",
    "lane_roles.json",
    "pro_builds.json",
    "draft_model.json",
    "public_matches.jsonl.gz",
}


class DataMissingError(FileNotFoundError):
    pass


def _manifest(directory: Path) -> dict[str, Any]:
    path = directory / "manifest.json"
    if not path.exists():
        return {}
    try:
        files: dict[str, Any] = json.loads(path.read_text(encoding="utf-8")).get("files", {})
        return files
    except (OSError, json.JSONDecodeError):
        return {}


class DataStore:
    def __init__(
        self, snapshot: Path | None = None, refreshed: Path | None = None, knowledge: Path | None = None
    ) -> None:
        self.snapshot = snapshot or paths.snapshot_dir()
        self.refreshed = refreshed if refreshed is not None else paths.refreshed_data_dir()
        self.knowledge = knowledge or paths.knowledge_dir()
        self._lock = threading.Lock()
        self._cache: dict[str, Any] = {}

    # ── file selection ─────────────────────────────────────────────

    def _source(self, name: str) -> tuple[Path | None, dict[str, Any]]:
        snap_meta = _manifest(self.snapshot).get(name, {})
        ref_meta = _manifest(self.refreshed).get(name, {}) if self.refreshed else {}
        snap_file, ref_file = self.snapshot / name, (self.refreshed / name if self.refreshed else None)
        if (
            ref_file
            and ref_file.exists()
            and (not snap_file.exists() or ref_meta.get("generated_at", 0) > snap_meta.get("generated_at", 0))
        ):
            return ref_file, {**ref_meta, "location": "refreshed"}
        if snap_file.exists():
            return snap_file, {**snap_meta, "location": "snapshot"}
        return None, {}

    def load(self, name: str) -> Any:
        with self._lock:
            if name in self._cache:
                return self._cache[name]
        path, _ = self._source(name)
        if path is None:
            if name in OPTIONAL:
                return None
            raise DataMissingError(f"{name} not found in {self.snapshot} or {self.refreshed}")
        if name.endswith(".gz"):
            with gzip.open(path, "rt", encoding="utf-8") as f:
                doc: Any = [json.loads(line) for line in f if line.strip()]
        else:
            doc = json.loads(path.read_text(encoding="utf-8"))
        with self._lock:
            self._cache[name] = doc
        return doc

    def knowledge_file(self, name: str) -> Any:
        key = f"knowledge/{name}"
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        doc = json.loads((self.knowledge / name).read_text(encoding="utf-8"))
        with self._lock:
            self._cache[key] = doc
        return doc

    def reload(self) -> None:
        with self._lock:
            self._cache.clear()
        for prop in ("heroes", "items"):
            self.__dict__.pop(prop, None)

    def status(self) -> dict[str, Any]:
        out = {}
        for name in DATA_FILES:
            path, meta = self._source(name)
            out[name] = {"present": path is not None, **meta}
        return {"snapshot": str(self.snapshot), "refreshed": str(self.refreshed), "files": out}

    # ── typed views ────────────────────────────────────────────────

    @cached_property
    def heroes(self) -> HeroIndex:
        return HeroIndex(
            self.load("heroes.json"), self.load("abilities.json"), self.knowledge_file("aliases.json")
        )

    @cached_property
    def items(self) -> ItemIndex:
        return ItemIndex(self.load("items.json"))

    @property
    def patch(self) -> str:
        return str(self.load("heroes.json")["patch"])

    def matchup_bucket(self, bucket: str) -> dict[str, Any]:
        doc = self.load("matchups.json")
        buckets: dict[str, dict[str, Any]] = doc["buckets"]
        return buckets.get(bucket) or buckets["all"]

    def per_hero(self, name: str, hero_id: int) -> Any:
        doc = self.load(name)
        if doc is None:
            return None
        if name == "pro_builds.json":
            return doc["heroes"].get(str(hero_id))
        return doc.get(str(hero_id))
