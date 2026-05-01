"""Tests for ML data snapshot generation."""

from ml.data_processor import DataProcessor


def _purchase_log(items):
    return [{"item": name, "time": ts} for ts, name in items]


def _player(hero_id: int, is_radiant: bool, won: bool, purchases):
    return {
        "hero_id": hero_id,
        "is_radiant": is_radiant,
        "win": won,
        "purchase_log": _purchase_log(purchases),
    }


def test_process_single_match_generates_rows_per_snapshot_timepoint():
    processor = DataProcessor("data")

    radiant_players = [
        _player(1, True, True, [(-10, "tango"), (620, "power_treads"), (1250, "dragon_lance"), (1810, "hurricane_pike"), (2410, "black_king_bar")]),
        _player(2, True, True, [(-10, "tango"), (650, "phase_boots"), (1300, "blink"), (1820, "black_king_bar"), (2460, "assault")]),
        _player(3, True, True, [(-10, "tango"), (700, "arcane_boots"), (1320, "force_staff"), (1860, "glimmer_cape"), (2450, "lotus_orb")]),
        _player(4, True, True, [(-10, "tango"), (610, "power_treads"), (1270, "maelstrom"), (1850, "mjollnir"), (2480, "satanic")]),
        _player(5, True, True, [(-10, "tango"), (690, "tranquil_boots"), (1290, "aether_lens"), (1830, "blink"), (2490, "aghs")]),
    ]
    dire_players = [
        _player(6, False, False, [(-10, "tango"), (640, "phase_boots"), (1260, "armlet"), (1870, "blink"), (2470, "bkb")]),
        _player(7, False, False, [(-10, "tango"), (670, "arcane_boots"), (1310, "mekansm"), (1840, "greaves"), (2440, "lotus_orb")]),
        _player(8, False, False, [(-10, "tango"), (660, "power_treads"), (1330, "desolator"), (1880, "bkb"), (2465, "satanic")]),
        _player(9, False, False, [(-10, "tango"), (680, "boots_of_speed"), (1280, "drum"), (1865, "bkb"), (2455, "shivas_guard")]),
        _player(10, False, False, [(-10, "tango"), (630, "power_treads"), (1295, "manta"), (1890, "skadi"), (2495, "butterfly")]),
    ]

    match = {
        "duration": 2600,
        "weight": 0.8,
        "players": radiant_players + dire_players,
    }

    result = processor._process_single_match(match)

    assert result["early"], "Expected early snapshots"
    assert result["mid"], "Expected mid snapshots"
    assert result["late"], "Expected late snapshots"

    hero_rows = [
        row
        for phase in ("early", "mid", "late")
        for row in result[phase]
        if row["hero_id"] == 1
    ]
    hero_times = sorted(row["game_time"] for row in hero_rows)
    assert hero_times == [600, 1200, 1800, 2400]
