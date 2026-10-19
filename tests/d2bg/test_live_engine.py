"""The live engine, driven by the synthetic demo match and by hand-made payloads."""

from __future__ import annotations

import pytest

from d2bg.gsi.demo import DEMO_MATCH_ID, demo_draft, demo_frames
from d2bg.live.engine import LiveEngine


@pytest.fixture
def frames(shared_ctx):
    return demo_frames(shared_ctx, "juggernaut", minutes=30)


def run(engine: LiveEngine, frames, until: float | None = None, source: str = "demo"):
    for _, payload in frames:
        clock = (payload.get("map") or {}).get("clock_time")
        if until is not None and clock is not None and clock > until:
            break
        engine.ingest(payload, source=source)


def test_demo_is_deterministic(shared_ctx):
    a = demo_frames(shared_ctx, "juggernaut", minutes=5)
    b = demo_frames(shared_ctx, "juggernaut", minutes=5)
    assert a == b
    assert demo_draft(a)["radiant"][0] == shared_ctx.data.heroes.require("juggernaut").id


def test_draft_phase_fills_both_teams(shared_ctx, frames):
    engine = LiveEngine(shared_ctx)
    run(engine, frames[:10])
    snap = engine.snapshot()
    assert snap["phase"] == "hero_selection" and snap["match_id"] == DEMO_MATCH_ID
    full = demo_draft(frames)
    assert snap["draft"]["allies"] == full["radiant"] and snap["draft"]["enemies"] == full["dire"]
    assert snap["situational_items"] is not None and snap["enemy_threats"]


def test_in_game_state_timers_items_and_benchmarks(shared_ctx, frames):
    engine = LiveEngine(shared_ctx)
    run(engine, frames, until=10 * 60)
    snap = engine.snapshot()
    assert snap["phase"] == "in_game" and snap["clock"] == 600 and snap["demo"] is True
    assert snap["hero"]["name"] == "Juggernaut"
    assert snap["stats"]["net_worth"] > snap["stats"]["gold"]
    ids = {t["id"] for t in snap["timers"]}
    assert {"bounty_rune", "power_rune", "wisdom_shrine", "neutral_tier", "roshan"} <= ids
    nxt = snap["next_items"]
    assert nxt and all(0 <= i["remaining"] <= i["cost"] for i in nxt)
    assert {b["metric"] for b in snap["benchmarks"]} >= {"gold_per_min", "last_hits_per_min"}
    assert snap["lh_target"]["at_10"] > 0
    assert len(snap["series"]) >= 15
    kinds = {a["kind"] for a in snap["alerts"]}
    assert "timer" in kinds


def test_roshan_event_starts_the_window_and_alerts(shared_ctx, frames):
    engine = LiveEngine(shared_ctx)
    run(engine, frames, until=23 * 60)
    snap = engine.snapshot()
    rosh = next(t for t in snap["timers"] if t["id"] == "roshan")
    assert rosh["status"] == "upcoming" and rosh["at"] == 22 * 60 + 480
    aegis = next(t for t in snap["timers"] if t["id"] == "aegis")
    assert aegis["at"] == 22 * 60 + 3 + 300
    assert any("Roshan killed" in a["text"] for a in snap["alerts"])
    assert [e["type"] for e in snap["events"]][:2] == ["roshan_killed", "aegis_picked_up"]


def test_post_game_callback_only_for_real_games(shared_ctx, frames):
    seen: list[str] = []
    engine = LiveEngine(shared_ctx, on_post_game=seen.append)
    run(engine, frames)  # demo
    assert engine.snapshot()["phase"] == "post_game" and seen == []
    engine2 = LiveEngine(shared_ctx, on_post_game=seen.append)
    run(engine2, frames[-3:], source="game")
    assert seen == [DEMO_MATCH_ID]


def test_mark_and_reset(shared_ctx, frames):
    engine = LiveEngine(shared_ctx)
    run(engine, frames, until=15 * 60)
    engine.mark("tormentor", 14 * 60)
    tor = next(t for t in engine.snapshot()["timers"] if t["id"] == "tormentor")
    assert tor["at"] == 24 * 60
    engine.mark("roshan")
    assert next(t for t in engine.snapshot()["timers"] if t["id"] == "roshan")["status"] == "upcoming"
    with pytest.raises(ValueError):
        engine.mark("nonsense")
    engine.reset()
    assert engine.snapshot()["phase"] == "waiting"


def test_account_callback_and_connection(shared_ctx):
    accounts: list[int] = []
    t = [100.0]
    engine = LiveEngine(shared_ctx, clock=lambda: t[0], on_account=accounts.append)
    engine.ingest({"player": {"accountid": "42"}, "map": {"game_state": "DOTA_GAMERULES_STATE_PRE_GAME"}})
    assert accounts == [42]
    assert engine.connection()["connected"] is True
    t[0] += 120
    assert engine.connection()["connected"] is False


def test_match_change_resets_memory(shared_ctx):
    engine = LiveEngine(shared_ctx)
    engine.ingest(
        {"map": {"matchid": "1", "clock_time": 100, "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"}}
    )
    engine.mark("roshan", 50)
    engine.ingest(
        {"map": {"matchid": "2", "clock_time": 10, "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"}}
    )
    assert engine.timers.roshan_killed_at is None and engine.match_id == "2"


def test_spectator_players_and_item_alerts(shared_ctx):
    engine = LiveEngine(shared_ctx)

    def payload(items):
        return {
            "map": {"matchid": "5", "clock_time": 900, "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"},
            "player": {"team2": {"player0": {"name": "a"}}, "team3": {"player5": {"name": "b"}}},
            "hero": {"team2": {"player0": {"id": 1}}, "team3": {"player5": {"id": 8}}},
            "items": {"team2": {"player0": {}}, "team3": {"player5": items}},
        }

    engine.ingest(payload({}), source="game")
    engine.ingest(payload({"slot0": {"name": "item_black_king_bar"}}), source="game")
    snap = engine.snapshot()
    assert snap["spectating"] and len(snap["players"]) == 2
    assert any("Black King Bar" in a["text"] for a in snap["alerts"])
    assert snap["draft"]["allies"] == [1] and snap["draft"]["enemies"] == [8]
