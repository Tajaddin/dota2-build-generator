"""Timer rules and their evaluation against the game clock."""

from __future__ import annotations

import pytest

from d2bg.knowledge.timers import TimerRule, TimerState, evaluate, fmt, next_fixed, next_periodic, upcoming


@pytest.fixture
def rules(shared_ctx):
    return {r.id: r for r in shared_ctx.timer_rules}


def test_every_rule_cites_a_source(shared_ctx):
    assert shared_ctx.timer_patch.startswith("7.41")
    for r in shared_ctx.timer_rules:
        assert r.cite.strip(), r.id


def test_periodic_and_fixed():
    assert next_periodic(0, 240, -30) == 0
    assert next_periodic(0, 240, 0) == 240
    assert next_periodic(360, 120, 100) == 360
    assert next_periodic(360, 120, 361) == 480
    assert next_fixed([120, 240], 119) == (0, 120.0)
    assert next_fixed([120, 240], 240) is None
    assert fmt(65) == "1:05" and fmt(-5) == "-0:05"


def test_rune_schedule_matches_patch_notes(rules):
    s = TimerState()
    assert evaluate(rules["bounty_rune"], 100, s).at == 240
    assert evaluate(rules["power_rune"], 100, s).at == 360
    assert evaluate(rules["power_rune"], 400, s).at == 480
    assert evaluate(rules["water_rune"], 130, s).at == 240
    assert evaluate(rules["water_rune"], 250, s) is None
    assert evaluate(rules["wisdom_shrine"], 500, s).at == 840
    assert evaluate(rules["lotus"], 10, s).at == 180


def test_neutral_tiers(rules):
    v = evaluate(rules["neutral_tier"], 1000, TimerState())
    assert v.at == 1500 and "Tier 3" in v.detail


def test_roshan_window_and_aegis(rules):
    s = TimerState(roshan_killed_at=1200, aegis_picked_at=1203)
    v = evaluate(rules["roshan"], 1300, s)
    assert v.status == "upcoming" and v.at == 1680
    v = evaluate(rules["roshan"], 1700, s)
    assert v.status == "window" and v.at == 1860
    assert evaluate(rules["roshan"], 1900, s).status == "alive"
    assert evaluate(rules["roshan"], 10, TimerState()).status == "alive"
    assert evaluate(rules["aegis"], 1300, s).at == 1503
    assert evaluate(rules["aegis"], 1504, s) is None


def test_tormentor(rules):
    assert evaluate(rules["tormentor"], 100, TimerState()).at == 1200
    assert evaluate(rules["tormentor"], 1300, TimerState()).status == "alive"
    v = evaluate(rules["tormentor"], 1500, TimerState(tormentor_killed_at=1400))
    assert v.at == 2000


def test_day_night_uses_observed_flip(rules):
    est = evaluate(rules["day_night"], 100, TimerState())
    assert est.status == "estimated" and est.at == 300
    seen = evaluate(rules["day_night"], 100, TimerState(day_flip_at=40, daytime=False))
    assert seen.status == "upcoming" and seen.at == 340 and seen.detail.startswith("Day")


def test_upcoming_sorts_and_filters(shared_ctx):
    views = upcoming(shared_ctx.timer_rules, 100, TimerState())
    lefts = [v.seconds_left for v in views if v.seconds_left is not None]
    assert lefts == sorted(lefts)
    assert all(v.id != "stack" for v in views)  # off by default
    on = upcoming(shared_ctx.timer_rules, 100, TimerState(), {"stack": True, "bounty_rune": False})
    ids = {v.id for v in on}
    assert "stack" in ids and "bounty_rune" not in ids


def test_load_defaults():
    [r] = TimerRule.load({"rules": [{"id": "x", "label": "X", "cite": "c", "first": 0, "interval": 10}]})
    assert r.lead == 15 and r.default_on
