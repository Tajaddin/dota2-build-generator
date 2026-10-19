"""Data refresh: fetch from OpenDota, transform, write the snapshot files and their manifest.

``d2bg data refresh`` writes into the user data folder; ``--to-snapshot`` updates the committed
``data/snapshot`` instead. Every step records its source, time, row count and API calls in
``manifest.json``, which the UI shows next to the data it produced.
"""

from __future__ import annotations

import gzip
import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from d2bg.opendota import DAY, OpenDotaClient
from d2bg.pipeline import matchups, transform

Progress = Callable[[str, int, int, str], None]

STEPS = (
    "constants",
    "hero_stats",
    "item_popularity",
    "benchmarks",
    "item_timings",
    "lane_roles",
    "pro_builds",
    "matchups",
    "draft_model",
)
# Steps that make one call per hero; the rest make a handful.
PER_HERO = {"item_popularity", "benchmarks", "item_timings", "lane_roles", "pro_builds"}

PRO_WINDOW_DAYS = 120
PRO_ROWS_PER_HERO = 600


@dataclass
class StepResult:
    step: str
    files: list[str] = field(default_factory=list)
    rows: int = 0
    calls: int = 0
    seconds: float = 0.0
    note: str = ""


def _noop(step: str, done: int, total: int, message: str) -> None:
    return None


def write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_matches_gz(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_matches_gz(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
            n += 1
    tmp.replace(path)
    return n


class Refresher:
    def __init__(
        self,
        client: OpenDotaClient,
        out_dir: Path,
        progress: Progress | None = None,
        now: Callable[[], float] = time.time,
        seed_dir: Path | None = None,
    ) -> None:
        self.client = client
        self.out = out_dir
        self.progress = progress or _noop
        self.now = now
        # Where the first refresh into a new folder takes its earlier public matches from.
        self.seed_dir = seed_dir
        self.out.mkdir(parents=True, exist_ok=True)

    # ── manifest ───────────────────────────────────────────────────

    def manifest(self) -> dict[str, Any]:
        path = self.out / "manifest.json"
        return read_json(path) if path.exists() else {"files": {}}

    def _record(self, file: str, source: str, rows: int, calls: int, **extra: Any) -> None:
        doc = self.manifest()
        doc["files"][file] = {
            "source": source,
            "generated_at": int(self.now()),
            "rows": rows,
            "calls": calls,
            **extra,
        }
        write_json(self.out / "manifest.json", doc)

    # ── helpers ────────────────────────────────────────────────────

    def _load(self, name: str) -> Any:
        return read_json(self.out / name)

    def _heroes(self) -> list[dict[str, Any]]:
        heroes: list[dict[str, Any]] = self._load("heroes.json")["heroes"]
        return heroes

    def _calls_since(self, start: int) -> int:
        return self.client.requests_made - start

    # ── steps ──────────────────────────────────────────────────────

    def constants(self) -> StepResult:
        res = StepResult("constants")
        c0 = self.client.requests_made
        names = (
            "heroes",
            "hero_abilities",
            "abilities",
            "items",
            "aghs_desc",
            "ability_ids",
            "item_ids",
            "patch",
        )
        raw: dict[str, Any] = {}
        for i, name in enumerate(names):
            self.progress("constants", i, len(names), name)
            raw[name] = self.client.get(f"constants/{name}", ttl=DAY)
        patches = [{"name": p["name"], "date": p["date"]} for p in raw["patch"]]
        heroes = transform.heroes_doc(raw["heroes"], raw["hero_abilities"], raw["aghs_desc"])
        write_json(self.out / "heroes.json", {"patch": patches[-1]["name"], "heroes": heroes})
        write_json(self.out / "abilities.json", transform.abilities_doc(raw["abilities"], heroes))
        write_json(self.out / "items.json", transform.items_doc(raw["items"]))
        write_json(self.out / "patches.json", patches)
        write_json(self.out / "ids.json", {"items": raw["item_ids"], "abilities": raw["ability_ids"]})
        res.calls = self._calls_since(c0)
        res.rows = len(heroes)
        counts = {
            "heroes.json": len(heroes),
            "abilities.json": len(transform.abilities_doc(raw["abilities"], heroes)),
            "items.json": len(transform.items_doc(raw["items"])),
            "patches.json": len(patches),
            "ids.json": len(raw["item_ids"]) + len(raw["ability_ids"]),
        }
        res.files = list(counts)
        for f, rows in counts.items():
            self._record(
                f, "OpenDota /constants (dotaconstants, MIT)", rows, res.calls, patch=patches[-1]["name"]
            )
        return res

    def hero_stats(self) -> StepResult:
        c0 = self.client.requests_made
        rows = self.client.get("heroStats", ttl=6 * 3600)
        doc = transform.hero_stats_doc(rows)
        write_json(self.out / "hero_stats.json", doc)
        res = StepResult("hero_stats", ["hero_stats.json"], len(doc), self._calls_since(c0))
        self._record(
            "hero_stats.json", "OpenDota /heroStats (recent public and pro matches)", res.rows, res.calls
        )
        return res

    def _per_hero(
        self, step: str, file: str, source: str, fetch: Callable[[dict[str, Any]], Any]
    ) -> StepResult:
        c0 = self.client.requests_made
        heroes = self._heroes()
        out: dict[str, Any] = {}
        for i, h in enumerate(heroes):
            self.progress(step, i, len(heroes), h["name"])
            out[str(h["id"])] = fetch(h)
        write_json(self.out / file, out)
        res = StepResult(step, [file], len(out), self._calls_since(c0))
        self._record(file, source, res.rows, res.calls)
        return res

    def item_popularity(self) -> StepResult:
        ids = {int(k): v for k, v in self._load("ids.json")["items"].items()}
        return self._per_hero(
            "item_popularity",
            "item_popularity.json",
            "OpenDota /heroes/{id}/itemPopularity (recent pro and high-rank matches)",
            lambda h: transform.item_popularity_doc(
                self.client.get(f"heroes/{h['id']}/itemPopularity", ttl=3 * DAY), ids
            ),
        )

    def benchmarks(self) -> StepResult:
        return self._per_hero(
            "benchmarks",
            "benchmarks.json",
            "OpenDota /benchmarks (percentiles per hero)",
            lambda h: transform.benchmarks_doc(
                self.client.get("benchmarks", {"hero_id": h["id"]}, ttl=7 * DAY)
            ),
        )

    def item_timings(self) -> StepResult:
        return self._per_hero(
            "item_timings",
            "item_timings.json",
            "OpenDota /scenarios/itemTimings",
            lambda h: transform.item_timings_doc(
                self.client.get("scenarios/itemTimings", {"hero_id": h["id"]}, ttl=7 * DAY)
            ),
        )

    def lane_roles(self) -> StepResult:
        return self._per_hero(
            "lane_roles",
            "lane_roles.json",
            "OpenDota /scenarios/laneRoles",
            lambda h: transform.lane_roles_doc(
                self.client.get("scenarios/laneRoles", {"hero_id": h["id"]}, ttl=7 * DAY)
            ),
        )

    def _pro_since(self) -> int:
        patches = self._load("patches.json")
        major = next((p for p in reversed(patches) if p["name"].count(".") == 1), patches[-1])
        from datetime import datetime

        patch_ts = int(datetime.fromisoformat(major["date"].replace("Z", "+00:00")).timestamp())
        window = int(self.now()) - PRO_WINDOW_DAYS * 86400
        window -= window % 86400  # whole days, so reruns on the same day reuse the cached queries
        return max(patch_ts, window)

    def pro_builds(self) -> StepResult:
        c0 = self.client.requests_made
        since = self._pro_since()
        ids = self._load("ids.json")
        items = self._load("items.json")
        heroes = self._heroes()
        # The SQL only interpolates integers computed here (a timestamp, a hero ID), and it runs on
        # OpenDota's read-only public explorer.
        team_sql = (
            "SELECT pm.match_id, pm.player_slot, pm.hero_id, pm.lane_role, pm.gold_per_min "
            "FROM player_matches pm JOIN matches m USING(match_id) "
            f"WHERE m.start_time >= {int(since)} AND pm.lane_role IS NOT NULL"
        )
        team_rows = self.client.explorer(team_sql, ttl=3 * DAY)
        positions = transform.positions_doc(team_rows)
        out: dict[str, Any] = {}
        total_rows = 0
        for i, h in enumerate(heroes):
            self.progress("pro_builds", i, len(heroes), h["name"])
            hero_sql = (
                "SELECT pm.match_id, pm.player_slot, pm.ability_upgrades_arr, pm.purchase_log, "
                "m.radiant_win FROM player_matches pm JOIN matches m USING(match_id) "
                f"WHERE m.start_time >= {int(since)} AND pm.hero_id = {int(h['id'])} "
                "AND pm.ability_upgrades_arr IS NOT NULL "
                f"ORDER BY m.start_time DESC LIMIT {PRO_ROWS_PER_HERO}"
            )
            rows = self.client.explorer(hero_sql, ttl=3 * DAY)
            total_rows += len(rows)
            out[str(h["id"])] = {
                "n": len(rows),
                "wins": sum(1 for r in rows if transform._won(r)),
                "positions": positions.get(str(h["id"]), {}),
                "skills": transform.skill_doc(rows, ids["abilities"], h["abilities"], h["talents"]),
                "items": transform.items_from_purchases(rows, items),
            }
        n_matches = len({r["match_id"] for r in team_rows})
        doc = {"since": since, "matches": n_matches, "rows": total_rows, "heroes": out}
        write_json(self.out / "pro_builds.json", doc)
        res = StepResult(
            "pro_builds",
            ["pro_builds.json"],
            total_rows,
            self._calls_since(c0),
            note=f"{n_matches} pro matches since {time.strftime('%Y-%m-%d', time.gmtime(since))}",
        )
        self._record(
            "pro_builds.json",
            "OpenDota /explorer (parsed pro matches)",
            total_rows,
            res.calls,
            matches=n_matches,
            since=since,
        )
        return res

    def matchups(self, max_calls: int = 600, days: int = 14) -> StepResult:
        c0 = self.client.requests_made
        new = matchups.collect_public_matches(self.client, max_calls=max_calls, days=days, now=self.now())
        return self._write_matchups(new, self._calls_since(c0), days)

    def _write_matchups(self, new_rows: list[dict[str, Any]], calls: int, days: int) -> StepResult:
        store = self.out / "public_matches.jsonl.gz"
        earlier = store if store.exists() or self.seed_dir is None else self.seed_dir / store.name
        merged = {int(r["match_id"]): r for r in read_matches_gz(earlier)}
        for r in new_rows:
            nm = matchups.normalize_match(r)
            if nm:
                merged[int(r["match_id"])] = nm
        newest = max((m.get("start_time") or 0 for m in merged.values()), default=0)
        keep = [m for m in merged.values() if (m.get("start_time") or 0) >= newest - days * 86400]
        keep.sort(key=lambda m: m["match_id"])
        write_matches_gz(store, keep)
        doc = matchups.compact(matchups.build_matrix(keep))
        write_json(self.out / "matchups.json", doc)
        res = StepResult("matchups", ["matchups.json", "public_matches.jsonl.gz"], len(keep), calls)
        for f in res.files:
            self._record(
                f,
                "OpenDota /publicMatches (ranked All Pick)",
                len(keep),
                calls,
                source_week=doc["source_week"],
            )
        return res

    def import_public_pages(self, page_dir: Path, days: int = 14) -> StepResult:
        rows = [r for r in matchups.read_page_dir(page_dir) if matchups.is_ranked_all_pick(r)]
        return self._write_matchups(rows, 0, days)

    def draft_model(self) -> StepResult:
        import importlib.util

        if importlib.util.find_spec("sklearn") is None:
            return StepResult(
                "draft_model", note="skipped: retraining needs the train extra (uv sync --extra train)"
            )
        from d2bg.pipeline import train_draft

        matches = read_matches_gz(self.out / "public_matches.jsonl.gz")
        heroes = [h["id"] for h in self._heroes()]
        model, report = train_draft.train(matches, heroes)
        write_json(self.out / "draft_model.json", model)
        res = StepResult(
            "draft_model",
            ["draft_model.json"],
            report["n_train"] + report["n_test"],
            0,
            note=f"held-out accuracy {report['test']['accuracy']:.3f}",
        )
        self._record(
            "draft_model.json", "Trained locally on public_matches.jsonl.gz", res.rows, 0, report=report
        )
        return res

    def run(self, steps: Iterable[str] = STEPS, **kwargs: Any) -> list[StepResult]:
        results = []
        for step in steps:
            if step not in STEPS:
                raise ValueError(f"unknown step {step!r}; choose from {', '.join(STEPS)}")
            started = time.monotonic()
            self.progress(step, 0, 1, "starting")
            fn = getattr(self, step)
            result: StepResult = fn(**kwargs) if step == "matchups" else fn()
            result.seconds = round(time.monotonic() - started, 1)
            self.progress(step, 1, 1, "done")
            results.append(result)
        return results
