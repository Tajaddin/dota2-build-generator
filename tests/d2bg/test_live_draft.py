"""What the app can learn about the draft from a player's GSI, checked against two real games.

The fixtures are anonymised recordings of his own ranked games (2026-10-19): one full draft
(loading, hero selection, strategy time) and one game from the team showcase into the first minute.
In both, Dota sent the player an empty `draft` block; his own hero and team, the ban announcements
and, after loading, the minimap are what carry the draft.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from d2bg.gsi import recorder
from d2bg.gsi.state import parse
from d2bg.live.engine import LiveEngine

FIXTURES = Path(__file__).parent / "fixtures"


def frames(name: str) -> list[dict]:
    return [p for _, p in recorder.read(FIXTURES / name)]


def heroes(shared_ctx, *keys: str) -> set[int]:
    return {shared_ctx.data.heroes.require(k).id for k in keys}


def banned_in(payloads: list[dict]) -> set[int]:
    out = set()
    for p in payloads:
        for e in p.get("events") or []:
            if e.get("event_type") == "generic_event":
                data = json.loads(e["data"])
                if data["type"] == "CHAT_MESSAGE_HERO_BANNED":
                    out.add(int(data["value"]))
    return out


def run_until(engine: LiveEngine, payloads: list[dict], state: str | None = None) -> dict:
    for p in payloads:
        engine.ingest(p, source="game")
        if state and (p.get("map") or {}).get("game_state") == state:
            break
    return engine.snapshot()


def test_the_draft_block_is_empty_for_a_player():
    assert not any(p.get("draft") for p in frames("player_draft_ranked.jsonl.gz"))
    assert not any(p.get("draft") for p in frames("player_pre_game.jsonl.gz"))


def test_own_hero_and_team_fill_in_during_hero_selection(shared_ctx):
    payloads = frames("player_draft_ranked.jsonl.gz")
    engine = LiveEngine(shared_ctx)
    picked = next(i for i, p in enumerate(payloads) if (p.get("hero") or {}).get("id"))
    before = run_until(engine, payloads[:picked])
    assert before["phase"] == "hero_selection"
    assert before["draft"]["allies"] == [] and before["draft"]["side"] == "dire"
    after = run_until(engine, payloads[picked : picked + 1])
    assert after["phase"] == "hero_selection"
    assert after["draft"]["allies"] == [shared_ctx.data.heroes.require("life_stealer").id]
    assert after["draft"]["enemies"] == []


def test_bans_come_from_the_ban_announcements(shared_ctx):
    payloads = frames("player_draft_ranked.jsonl.gz")
    expected = banned_in(payloads)
    assert len(expected) >= 10  # a ranked draft bans heroes from both teams
    snap = run_until(LiveEngine(shared_ctx), payloads, "DOTA_GAMERULES_STATE_STRATEGY_TIME")
    assert set(snap["draft"]["bans"]) == expected


def test_draft_screen_models_are_not_taken_for_picks(shared_ctx):
    # During loading and hero selection the minimap lists showcase models (Legion Commander, Terrorblade,
    # Phantom Assassin, Windranger in both of his games) with no team. They must not become picks.
    snap = run_until(
        LiveEngine(shared_ctx), frames("player_draft_ranked.jsonl.gz"), "DOTA_GAMERULES_STATE_STRATEGY_TIME"
    )
    shown = set(snap["draft"]["allies"]) | set(snap["draft"]["enemies"])
    assert not shown & heroes(shared_ctx, "legion_commander", "terrorblade", "phantom_assassin", "windrunner")


def test_allies_and_seen_enemies_come_from_the_minimap_after_loading(shared_ctx):
    snap = run_until(LiveEngine(shared_ctx), frames("player_pre_game.jsonl.gz"))
    assert snap["phase"] == "in_game" and snap["draft"]["side"] == "dire"
    allies = heroes(shared_ctx, "silencer", "magnataur", "necrolyte", "slark", "windrunner")
    assert set(snap["draft"]["allies"]) == allies
    assert snap["draft"]["allies"][0] == shared_ctx.data.heroes.require("necrolyte").id  # him first
    assert heroes(shared_ctx, "viper", "winter_wyvern", "troll_warlord", "ogre_magi") <= set(
        snap["draft"]["enemies"]
    )
    assert not set(snap["draft"]["enemies"]) & allies
    assert snap["situational_items"]  # enemy heroes now drive counter items on the Live page


def test_snapshot_says_what_came_from_the_game(shared_ctx):
    snap = run_until(
        LiveEngine(shared_ctx), frames("player_draft_ranked.jsonl.gz"), "DOTA_GAMERULES_STATE_STRATEGY_TIME"
    )
    sources = snap["draft"]["sources"]
    assert sources["you"] and sources["bans"]
    assert "not send" in snap["draft"]["note"].lower()


def test_parser_reads_minimap_heroes_and_generic_events(shared_ctx):
    payload = next(p for p in frames("player_pre_game.jsonl.gz") if (p.get("minimap") or {}))
    state = parse(payload, 0.0, {h.key: h.id for h in shared_ctx.data.heroes})
    assert state.minimap
    unit = state.minimap[0]
    assert unit.hero_id and unit.team in (2, 3) and unit.image.startswith("minimap_")
    ban = parse(
        {
            "events": [
                {
                    "game_time": 23,
                    "event_type": "generic_event",
                    "data": '{"type":"CHAT_MESSAGE_HERO_BANNED","value":25,"playerid1":-1}',
                }
            ]
        },
        0.0,
    ).events[0]
    assert ban.subtype == "CHAT_MESSAGE_HERO_BANNED" and ban.value == 25
    broken = parse({"events": [{"event_type": "generic_event", "data": "not json"}]}, 0.0).events[0]
    assert broken.subtype is None and broken.value is None


@pytest.mark.parametrize("name", ["player_draft_ranked.jsonl.gz", "player_pre_game.jsonl.gz"])
def test_fixtures_hold_no_personal_data(name):
    text = json.dumps(frames(name))
    for field in ('"steamid": "7', "Yetim", "chat_message"):
        assert field not in text


def test_a_recording_still_being_written_reads_up_to_its_last_whole_frame(tmp_path):
    whole = (FIXTURES / "player_draft_ranked.jsonl.gz").read_bytes()
    cut = tmp_path / "live.jsonl.gz"
    cut.write_bytes(whole[: len(whole) // 2])  # like the current game's file, before it is closed
    got = list(recorder.read(cut))
    assert 0 < len(got) < len(frames("player_draft_ranked.jsonl.gz"))
