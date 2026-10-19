"""GSI payload parsing, the config installer and the session recorder."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from d2bg.gsi import installer, recorder
from d2bg.gsi.state import parse, unspent_skill_points

PLAYING = {
    "auth": {"token": "t"},
    "provider": {"name": "Dota 2", "appid": 570},
    "map": {
        "matchid": "8123",
        "game_time": 700,
        "clock_time": 610,
        "daytime": False,
        "radiant_score": 12,
        "dire_score": 9,
        "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS",
        "paused": False,
        "win_team": "none",
    },
    "player": {
        "steamid": "765",
        "accountid": "123456",
        "name": "me",
        "activity": "playing",
        "kills": 3,
        "deaths": 1,
        "assists": 7,
        "last_hits": 71,
        "denies": 4,
        "gold": 1234,
        "gold_reliable": 300,
        "gold_unreliable": 934,
        "gpm": 455,
        "xpm": 520,
        "team_name": "radiant",
    },
    "hero": {
        "id": 8,
        "name": "npc_dota_hero_juggernaut",
        "level": 9,
        "alive": True,
        "buyback_cost": 600,
        "buyback_cooldown": 0,
        "aghanims_scepter": False,
        "talent_1": False,
        "talent_2": True,
    },
    "abilities": {
        "ability0": {
            "name": "juggernaut_blade_fury",
            "level": 4,
            "can_cast": True,
            "passive": False,
            "ultimate": False,
            "cooldown": 0,
        },
        "ability1": {"name": "juggernaut_healing_ward", "level": 1},
        "ability2": {"name": "juggernaut_blade_dance", "level": 2},
        "ability3": {"name": "juggernaut_omni_slash", "level": 1, "ultimate": True},
    },
    "items": {
        "slot0": {"name": "item_power_treads"},
        "slot1": {"name": "empty"},
        "slot2": {"name": "item_magic_wand", "charges": 12},
        "slot6": {"name": "item_tango"},
        "stash0": {"name": "item_ogre_axe"},
        "teleport0": {"name": "item_tpscroll"},
        "neutral0": {"name": "item_trusty_shovel"},
    },
    "events": [{"game_time": 500, "event_type": "roshan_killed", "team": "dire", "killer_player_id": 7}],
}


def test_parse_playing_payload():
    s = parse(PLAYING, 1.0)
    assert s.phase == "in_game" and s.match_id == "8123" and s.clock == 610 and s.daytime is False
    assert s.team == "radiant" and s.account_id == 123456 and not s.spectating
    assert s.hero is not None and s.hero.id == 8 and s.hero.key == "juggernaut" and s.hero.level == 9
    assert s.hero.talents == [False, True]
    assert s.stats is not None and (s.stats.kills, s.stats.last_hits, s.stats.gpm) == (3, 71, 455)
    assert [i.key for i in s.inventory] == ["power_treads", "magic_wand"]
    assert s.inventory[1].charges == 12
    assert [i.key for i in s.backpack] == ["tango"] and [i.key for i in s.stash] == ["ogre_axe"]
    assert s.teleport and s.teleport.key == "tpscroll" and s.neutral and s.neutral.key == "trusty_shovel"
    assert s.owned_items == ["power_treads", "magic_wand", "tango", "ogre_axe"]
    assert [a.level for a in s.abilities] == [4, 1, 2, 1]
    assert s.events[0].type == "roshan_killed" and s.events[0].game_time == 500
    assert "auth" not in s.blocks and "map" in s.blocks
    assert unspent_skill_points(s) == 1


def test_hero_id_from_name_when_missing():
    s = parse({"hero": {"name": "npc_dota_hero_axe", "id": 0}}, 0, {"axe": 2})
    assert s.hero is not None and s.hero.id == 2


def test_parse_menu_and_garbage():
    assert parse({}, 0).phase == "menu"
    s = parse({"map": "nope", "player": [], "items": None, "events": ["x", {"event_type": 5}]}, 0)
    assert s.phase == "menu" and s.stats is None and s.events == []
    assert unspent_skill_points(s) is None


def test_parse_draft():
    payload = {
        "map": {"game_state": "DOTA_GAMERULES_STATE_HERO_SELECTION"},
        "draft": {
            "activeteam": 3,
            "activeteam_time_remaining": 12,
            "team2": {"pick0_id": 1, "pick1_id": 0, "ban0_id": 5},
            "team3": {"pick0_id": 8, "ban0_id": 0},
        },
    }
    s = parse(payload, 0)
    assert s.phase == "hero_selection"
    assert s.draft is not None
    assert (s.draft.radiant_picks, s.draft.dire_picks, s.draft.radiant_bans) == ([1], [8], [5])
    assert s.draft.active_team == "dire" and s.draft.time_remaining == 12
    assert parse({"draft": {"team2": {}, "team3": {}}}, 0).draft is None


def test_parse_spectator_payload():
    payload = {
        "map": {"game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", "clock_time": 100},
        "player": {
            "team2": {"player0": {"name": "a", "kills": 2, "net_worth": 3000}},
            "team3": {"player5": {"name": "b"}},
        },
        "hero": {
            "team2": {"player0": {"id": 1, "name": "npc_dota_hero_antimage", "level": 5}},
            "team3": {"player5": {"id": 8, "name": "npc_dota_hero_juggernaut"}},
        },
        "items": {"team2": {"player0": {"slot0": {"name": "item_bfury"}}}, "team3": {"player5": {}}},
    }
    s = parse(payload, 0)
    assert s.spectating and s.hero is None
    assert [(p.team, p.hero_id) for p in s.players] == [("radiant", 1), ("dire", 8)]
    assert s.players[0].stats.net_worth == 3000 and s.players[0].items[0].key == "bfury"


# ── installer ──────────────────────────────────────────────────────


def _fake_steam(tmp_path: Path) -> tuple[Path, Path]:
    steam = tmp_path / "Steam"
    lib = tmp_path / "Games" / "SteamLibrary"
    dota = lib / "steamapps" / "common" / "dota 2 beta"
    (dota / "game" / "dota" / "cfg").mkdir(parents=True)
    (steam / "steamapps").mkdir(parents=True)
    vdf = (
        f'"libraryfolders"\n{{\n "0"\n {{\n  "path"  "{steam}"\n }}\n "1"\n {{\n  "path"  "{lib}"\n }}\n}}\n'
    )
    (steam / "steamapps" / "libraryfolders.vdf").write_text(vdf.replace("\\", "\\\\"))
    return steam, dota


def test_render_config():
    cfg = installer.render_config(4242, "tok")
    assert '"uri"               "http://127.0.0.1:4242/gsi"' in cfg
    assert '"token"         "tok"' in cfg
    for block in ("map", "player", "hero", "abilities", "items", "draft", "events"):
        assert f'"{block}"' in cfg


def test_find_install_status_remove(tmp_path):
    steam, dota = _fake_steam(tmp_path)
    found = installer.find_dota([steam])
    assert found is not None and found.resolve() == dota.resolve()
    before = sorted(p for p in dota.rglob("*"))
    target = installer.install(dota, 4242, "tok")
    assert target.name == installer.CONFIG_NAME
    assert installer.status(dota, 4242, "tok")["current"] is True
    assert installer.status(dota, 4242, "other")["current"] is False
    after = sorted(p for p in dota.rglob("*"))
    # The only things created are the gamestate_integration folder and our file.
    assert set(after) - set(before) == {target.parent, target}
    assert installer.remove(dota) is True and not target.exists()
    assert installer.remove(dota) is False
    assert installer.status(None, 4242, "tok")["dota_found"] is False


def test_install_refuses_a_folder_that_is_not_dota(tmp_path):
    with pytest.raises(FileNotFoundError):
        installer.install(tmp_path, 4242, "tok")


# ── recorder ───────────────────────────────────────────────────────


def test_recorder_strips_auth_splits_by_match_and_prunes(tmp_path):
    now = [100.0]
    rec = recorder.Recorder(tmp_path, keep=2, clock=lambda: now[0])
    rec.write({"auth": {"token": "secret"}, "map": {"matchid": "1"}})
    now[0] += 2.5
    rec.write({"map": {"matchid": "1"}})
    first = rec.current
    now[0] += 3600
    rec.write({"map": {"matchid": "2"}})
    now[0] += 3600
    rec.write({"map": {"matchid": "3"}})
    rec.close()
    files = sorted(tmp_path.glob("*.jsonl.gz"))
    assert len(files) == 2 and first not in files
    rows = list(recorder.read(files[0]))
    assert rows[0][1] == {"map": {"matchid": "2"}}
    assert recorder.list_recordings(tmp_path)[0]["name"].endswith("_3.jsonl.gz")
    with gzip.open(files[0], "rt") as f:
        assert "secret" not in f.read()


def test_recorder_timestamps_relative(tmp_path):
    now = [10.0]
    rec = recorder.Recorder(tmp_path, clock=lambda: now[0])
    rec.write({"map": {"matchid": "9"}})
    now[0] = 12.5
    rec.write({"map": {"matchid": "9"}})
    rec.close()
    assert [t for t, _ in recorder.read(rec.current)] == [0.0, 2.5]  # type: ignore[arg-type]


def test_player_feeds_frames_in_order_with_speed():
    got, slept = [], []
    p = recorder.Player(
        [(0.0, {"n": 1}), (2.0, {"n": 2}), (2.0, {"n": 3})], got.append, speed=4, sleep=slept.append
    )
    p.run()
    assert [g["n"] for g in got] == [1, 2, 3] and slept == [0.5] and p.position == 3
    stopped = recorder.Player([(0.0, {}), (1.0, {})], got.append, sleep=lambda s: None)
    stopped.stop()
    stopped.run()
    assert stopped.position == 0


def test_payload_fixture_is_json_serialisable():
    json.dumps(PLAYING)
