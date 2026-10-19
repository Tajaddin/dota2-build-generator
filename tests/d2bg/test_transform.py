"""Pipeline transforms on small hand-checked fixtures."""

from __future__ import annotations

import pytest

from d2bg.pipeline import transform as t


def test_heroes_doc_flattens_nested_abilities_and_drops_hidden_slot():
    heroes = {
        "1": {
            "id": 1,
            "name": "npc_dota_hero_monkey_king",
            "localized_name": "Monkey King",
            "img": "/x.png?",
            "roles": ["Carry"],
        }
    }
    abil = {
        "npc_dota_hero_monkey_king": {
            "abilities": ["mk_a", ["mk_untransform", "mk_transform"], "generic_hidden"],
            "talents": [{"name": "special_bonus_1", "level": 1}],
        }
    }
    aghs = [
        {
            "hero_id": 1,
            "has_scepter": True,
            "scepter_desc": "s",
            "scepter_skill_name": "A",
            "has_shard": False,
        }
    ]
    [doc] = t.heroes_doc(heroes, abil, aghs)
    assert doc["key"] == "monkey_king"
    assert doc["abilities"] == ["mk_a", "mk_untransform", "mk_transform"]
    assert doc["img"] == "https://cdn.cloudflare.steamstatic.com/x.png"
    assert doc["scepter"] == {"skill": "A", "desc": "s"} and doc["shard"] is None


def test_hero_stats_doc_brackets_pro_turbo():
    row = {
        "id": 5,
        "1_pick": "10",
        "1_win": 6,
        "8_pick": 2,
        "8_win": 1,
        "pro_pick": 3,
        "pro_win": 2,
        "pro_ban": 9,
        "turbo_picks": 100,
        "turbo_wins": 55,
        "pub_pick": 7,
        "pub_win": 3,
    }
    doc = t.hero_stats_doc([row])["5"]
    assert doc["brackets"]["1"] == [10, 6]
    assert doc["brackets"]["4"] == [0, 0]
    assert doc["pro"] == [3, 2, 9] and doc["turbo"] == [100, 55] and doc["pub"] == [7, 3]


def test_item_popularity_maps_ids_and_sorts():
    raw = {"start_game_items": {"44": 3, "16": 9}, "late_game_items": {"999": 1}}
    doc = t.item_popularity_doc(raw, {44: "tango", 16: "branches"})
    assert list(doc["start"].items()) == [("branches", 9), ("tango", 3)]
    assert doc["late"] == {"item_999": 1}
    assert doc["mid"] == {}


def test_benchmarks_and_timings_and_lanes():
    assert t.benchmarks_doc({"result": {"gold_per_min": [{"percentile": 0.5, "value": 400}]}}) == {
        "gold_per_min": [[0.5, 400.0]]
    }
    timings = t.item_timings_doc(
        [
            {"item": "blink", "time": 900, "games": "4", "wins": "3"},
            {"item": "blink", "time": 450, "games": "2", "wins": "1"},
        ]
    )
    assert timings == {"blink": [[450, 2, 1], [900, 4, 3]]}
    lanes = t.lane_roles_doc(
        [
            {"lane_role": 1, "games": "10", "wins": "6"},
            {"lane_role": 1, "games": "5", "wins": "1"},
            {"lane_role": 3, "games": "2", "wins": "2"},
        ]
    )
    assert lanes == {"1": [15, 7], "3": [2, 2]}


def _p(hero, lane, gpm, slot=0):
    return {"hero_id": hero, "lane_role": lane, "gold_per_min": gpm, "player_slot": slot, "match_id": 1}


def test_assign_positions_by_lane_and_gpm():
    team = [_p(1, 1, 700), _p(2, 2, 650), _p(3, 3, 500), _p(4, 3, 300), _p(5, 1, 250)]
    assert t.assign_positions(team) == {1: 1, 2: 2, 3: 3, 4: 4, 5: 5}


def test_assign_positions_resolves_odd_lanes():
    # Two cores in the safe lane: the richer takes 1, the other the free core slot.
    team = [_p(1, 1, 700), _p(2, 1, 650), _p(3, 2, 600), _p(4, 4, 300), _p(5, 1, 250)]
    pos = t.assign_positions(team)
    assert pos[1] == 1 and pos[3] == 2 and pos[2] == 3
    assert {pos[4], pos[5]} == {4, 5} and pos[5] == 5


def test_positions_doc_counts_complete_teams_only():
    rows = [
        {**_p(h, lane, g), "match_id": 9, "player_slot": s}
        for h, lane, g, s in [(1, 1, 700, 0), (2, 2, 650, 1), (3, 3, 500, 2), (4, 3, 300, 3), (5, 1, 250, 4)]
    ]
    rows.append({**_p(6, 2, 500), "match_id": 9, "player_slot": 128})  # an incomplete Dire side
    doc = t.positions_doc(rows)
    assert doc["1"] == {"1": 1} and doc["5"] == {"5": 1}
    assert "6" not in doc


def _row(order, won=True, slot=0):
    return {"ability_upgrades_arr": order, "player_slot": slot, "radiant_win": won}


def test_skill_doc_counts_orders_levels_and_talents():
    ids = {"1": "a", "2": "b", "3": "c", "9": "special_bonus_x", "8": "special_bonus_y"}
    rows = [_row([1, 2, 1, 3, 1, 9]), _row([1, 2, 1, 3, 1, 8], won=False), _row([2, 1, 1, 3, 1, 9])]
    doc = t.skill_doc(
        rows,
        ids,
        ["a", "b", "c"],
        [{"key": "special_bonus_x", "level": 1}, {"key": "special_bonus_y", "level": 1}],
        order_length=5,
    )
    assert doc["by_level"][0] == {"pick": 1, "ability": "a", "share": round(2 / 3, 3), "n": 3}
    assert doc["orders"][0] == {"order": ["a", "b", "a", "c", "a"], "n": 2, "wins": 1}
    assert doc["talents"]["special_bonus_x"] == {"level": 1, "n": 2, "share": round(2 / 3, 3)}


def test_items_from_purchases_starting_order_and_medians():
    items = {
        "boots": {"cost": 500},
        "power_treads": {"cost": 1400, "components": ["boots"]},
        "bfury": {"cost": 4100, "components": ["x"]},
        "tango": {"cost": 90},
        "branches": {"cost": 50},
    }
    rows = []
    for i in range(10):
        log = [
            {"time": -80, "key": "tango"},
            {"time": -80, "key": "branches"},
            {"time": 300, "key": "boots"},
            {"time": 500 + i, "key": "power_treads"},
        ]
        if i < 5:
            log.append({"time": 900 + 10 * i, "key": "bfury"})
        rows.append({"purchase_log": log, "player_slot": 0, "radiant_win": i % 2 == 0})
    doc = t.items_from_purchases(rows, items, min_share=0.3)
    assert doc["rows"] == 10
    assert doc["starting"][0] == {"items": ["branches", "tango"], "n": 10}
    assert [o["item"] for o in doc["order"]] == ["power_treads", "bfury"]  # boots < 1000 and no parts
    assert doc["order"][0]["median_time"] == pytest.approx(504.5, abs=1)
    assert doc["order"][1]["share"] == 0.5
    assert doc["median_timings"]["bfury"] == 920


def test_build_order_drops_parts_finished_into_a_later_item():
    items = {
        "broadsword": {"cost": 1000},
        "bfury": {"cost": 4100, "components": ["broadsword", "x"]},
        "dragon_lance": {"cost": 1900, "components": ["y"]},
        "hurricane_pike": {"cost": 4500, "components": ["dragon_lance"]},
    }
    rows = []
    for i in range(10):
        log = [
            {"time": 500, "key": "broadsword"},
            {"time": 800, "key": "bfury"},
            {"time": 900, "key": "dragon_lance"},
        ]
        if i < 2:
            log.append({"time": 2000, "key": "hurricane_pike"})
        rows.append({"purchase_log": log, "player_slot": 0, "radiant_win": True})
    doc = t.items_from_purchases(rows, items, min_share=0.1)
    # Broadsword always becomes Battle Fury; Dragon Lance mostly stays a Lance.
    assert [o["item"] for o in doc["order"]] == ["bfury", "dragon_lance", "hurricane_pike"]
    assert doc["median_timings"]["broadsword"] == 500
