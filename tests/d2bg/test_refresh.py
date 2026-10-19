"""The refresh pipeline end to end against a fake OpenDota, writing a complete snapshot to a temp folder."""

from __future__ import annotations

import random
from typing import Any

import pytest

from d2bg.datastore import DataStore
from d2bg.pipeline import refresh as r

HEROES = {
    "1": {
        "id": 1,
        "name": "npc_dota_hero_antimage",
        "localized_name": "Anti-Mage",
        "roles": ["Carry"],
        "primary_attr": "agi",
        "attack_type": "Melee",
        "img": "/a.png?",
    },
    "2": {
        "id": 2,
        "name": "npc_dota_hero_axe",
        "localized_name": "Axe",
        "roles": ["Initiator"],
        "primary_attr": "str",
        "attack_type": "Melee",
        "img": "/b.png?",
    },
}
HERO_ABILITIES = {
    "npc_dota_hero_antimage": {
        "abilities": ["am_q", "am_w"],
        "talents": [{"name": "special_bonus_am", "level": 1}],
    },
    "npc_dota_hero_axe": {"abilities": ["axe_q"], "talents": []},
}
ABILITIES = {
    "am_q": {"dname": "Mana Break", "desc": "Burns mana."},
    "am_w": {"dname": "Blink", "desc": "Blinks."},
    "axe_q": {"dname": "Berserker's Call", "desc": "Taunts enemies."},
    "special_bonus_am": {"dname": "+10 Agility"},
}
ITEMS = {
    "bfury": {
        "id": 145,
        "dname": "Battle Fury",
        "cost": 4100,
        "components": ["broadsword", "quelling_blade"],
    },
    "broadsword": {"id": 3, "dname": "Broadsword", "cost": 1000},
    "quelling_blade": {"id": 11, "dname": "Quelling Blade", "cost": 100},
    "tango": {"id": 44, "dname": "Tango", "cost": 90},
}


NOW = 2_000_000_000.0  # newer than the committed snapshot, so refreshed files win


def _public_rows(n: int) -> list[dict[str, Any]]:
    rng = random.Random(1)
    out = []
    for i in range(n):
        out.append(
            {
                "match_id": 10_000 - i,
                "start_time": int(NOW) - i * 60,
                "lobby_type": 7,
                "game_mode": 22,
                "radiant_team": [1],
                "dire_team": [2],
                "radiant_win": rng.random() < 0.6,
                "avg_rank_tier": rng.choice([15, 35, 55, 75]),
            }
        )
    return out


class FakeOpenDota:
    def __init__(self) -> None:
        self.requests_made = 0

    def get(self, path: str, params: dict[str, Any] | None = None, ttl: float | None = None) -> Any:
        self.requests_made += 1
        constants = {
            "constants/heroes": HEROES,
            "constants/hero_abilities": HERO_ABILITIES,
            "constants/abilities": ABILITIES,
            "constants/items": ITEMS,
            "constants/aghs_desc": [],
            "constants/ability_ids": {"5001": "am_q", "5002": "am_w", "6000": "special_bonus_am"},
            "constants/item_ids": {"145": "bfury", "44": "tango"},
            "constants/patch": [{"name": "7.41", "date": "2026-03-24T00:00:00Z"}],
        }
        if path in constants:
            return constants[path]
        if path == "heroStats":
            return [{"id": 1, "1_pick": 10, "1_win": 6}, {"id": 2, "1_pick": 5, "1_win": 2}]
        if path.endswith("itemPopularity"):
            return {"start_game_items": {"44": 9}, "mid_game_items": {"145": 4}}
        if path == "benchmarks":
            return {"result": {"gold_per_min": [{"percentile": 0.5, "value": 500}]}}
        if path == "scenarios/itemTimings":
            return [{"item": "bfury", "time": 900, "games": "40", "wins": "22"}]
        if path == "scenarios/laneRoles":
            return [{"lane_role": 1, "time": 900, "games": "30", "wins": "15"}]
        if path == "publicMatches":
            cursor = (params or {}).get("less_than_match_id")
            rows = _public_rows(400)
            return [x for x in rows if not cursor or x["match_id"] < cursor][:100]
        raise AssertionError(path)

    def explorer(self, sql: str, ttl: float | None = None) -> list[dict[str, Any]]:
        self.requests_made += 1
        if "pm.hero_id, pm.lane_role" in sql:
            return [
                {"match_id": 1, "player_slot": s, "hero_id": h, "lane_role": lane, "gold_per_min": g}
                for s, h, lane, g in (
                    (0, 1, 1, 700),
                    (1, 2, 3, 500),
                    (2, 3, 2, 600),
                    (3, 4, 3, 200),
                    (4, 5, 1, 150),
                )
            ]
        if "pm.hero_id = 1" in sql:
            return [
                {
                    "match_id": i,
                    "player_slot": 0,
                    "radiant_win": i % 2 == 0,
                    "ability_upgrades_arr": [5001, 5002, 5001, 6000],
                    "purchase_log": [
                        {"time": -60, "key": "tango"},
                        {"time": 400, "key": "broadsword"},
                        {"time": 800, "key": "bfury"},
                    ],
                }
                for i in range(30)
            ]
        return []


def test_full_refresh_writes_a_loadable_snapshot(tmp_path):
    pytest.importorskip("sklearn")
    seen: list[str] = []
    refresher = r.Refresher(
        FakeOpenDota(),
        tmp_path,
        progress=lambda s, d, t, m: seen.append(s),  # type: ignore[arg-type]
        now=lambda: NOW,
    )
    steps = [s for s in r.STEPS if s != "draft_model"]
    results = {res.step: res for res in refresher.run(steps, max_calls=5)}
    assert set(results) == set(steps) and set(seen) >= set(steps)
    assert results["constants"].rows == 2 and results["matchups"].rows == 400
    manifest = refresher.manifest()["files"]
    assert manifest["pro_builds.json"]["matches"] == 1 and manifest["matchups.json"]["source_week"]
    pro = r.read_json(tmp_path / "pro_builds.json")["heroes"]["1"]
    assert pro["n"] == 30 and pro["positions"] == {"1": 1}
    assert [o["item"] for o in pro["items"]["order"]] == ["bfury"]
    assert pro["skills"]["talents"]["special_bonus_am"]["share"] == 1.0
    assert r.read_json(tmp_path / "item_popularity.json")["1"]["start"] == {"tango": 9}

    # The new files win over the committed snapshot when the app loads.
    store = DataStore(refreshed=tmp_path)
    assert store.status()["files"]["heroes.json"]["location"] == "refreshed"
    assert store.heroes.get("am").name == "Anti-Mage"  # type: ignore[union-attr]


def test_unknown_step_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown step"):
        r.Refresher(FakeOpenDota(), tmp_path).run(["nope"])  # type: ignore[arg-type]


def test_matches_file_roundtrip(tmp_path):
    path = tmp_path / "m.jsonl.gz"
    assert r.read_matches_gz(path) == []
    assert r.write_matches_gz(path, [{"a": 1}, {"a": 2}]) == 2
    assert r.read_matches_gz(path) == [{"a": 1}, {"a": 2}]
