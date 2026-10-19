"""Draft model (inference and a small training run), positions, profile analytics, post-game polling."""

from __future__ import annotations

import random

import pytest

from d2bg.draft.lanes import assign_positions, lane_matchups, lanes_from_positions
from d2bg.draft.model import WinModel
from d2bg.draft.positions import hero_positions, playable, shares_from_counts
from d2bg.matches.postgame import PostGame
from d2bg.opendota import NotFoundError
from d2bg.pipeline import train_draft
from d2bg.profile import analytics as a


def test_committed_model_beats_the_baseline(data):
    doc = data.load("draft_model.json")
    report = doc["report"]
    assert report["n_test"] > 1000
    assert report["test"]["accuracy"] > report["test_baseline_radiant_rate"]["accuracy"]
    assert report["test"]["log_loss"] < report["test_baseline_radiant_rate"]["log_loss"]
    assert 0.5 < report["test"]["auc"] < 1


def test_inference_is_a_probability_with_contributions(data):
    model = WinModel(data.load("draft_model.json"))
    bucket = data.matchup_bucket("all")
    out = model.predict([1, 2, 3, 4, 5], [6, 7, 8, 9, 10], bucket)
    assert 0 < out["radiant"] < 1 and out["radiant"] + out["dire"] == pytest.approx(1)
    assert len(out["contributions"]) == 10 and out["complete"]
    swapped = model.predict([6, 7, 8, 9, 10], [1, 2, 3, 4, 5], bucket)
    # Swapping sides only moves the intercept's Radiant edge, not who is favoured by much.
    assert (out["radiant"] - 0.5) * (swapped["dire"] - 0.5) >= 0 or abs(
        out["radiant"] - swapped["dire"]
    ) < 0.1
    empty = model.predict([], [], bucket)
    assert empty["features"]["counter"]["value"] == 0


def test_training_learns_a_planted_signal():
    rng = random.Random(3)
    heroes = list(range(1, 31))
    matches = []
    for i in range(1500):
        picks = rng.sample(heroes, 10)
        radiant, dire = picks[:5], picks[5:]
        p = 0.5 + (0.3 if 1 in radiant else -0.3 if 1 in dire else 0.0)
        matches.append(
            {
                "match_id": i,
                "radiant": radiant,
                "dire": dire,
                "radiant_win": rng.random() < p,
                "avg_rank_tier": 45,
                "start_time": i,
            }
        )
    model, report = train_draft.train(matches, heroes, min_pair_games=5)
    assert model["hero_weights"]["1"] == max(model["hero_weights"].values())
    assert report["test"]["accuracy"] > 0.55
    with pytest.raises(ValueError):
        train_draft.train(matches[:50], heroes)


def test_positions_sources_and_lanes():
    pro = {"heroes": {"1": {"positions": {"1": 30, "3": 2}}}}
    lanes = {"2": {"1": [10, 5], "3": [10, 5]}}
    pos = hero_positions(pro, lanes, {1: ("Carry",), 2: ("Support",), 3: ("Carry", "Initiator")})
    assert pos[1]["source"] == "pro" and pos[1]["shares"][1] == pytest.approx(0.938, abs=1e-3)
    assert pos[2]["source"] == "public lanes" and set(pos[2]["shares"]) == {4, 5}
    assert pos[3]["source"] == "listed roles"
    assert playable(pos)[1] == {1}
    assert shares_from_counts({}) == {}

    shares = {1: {1: 0.9}, 2: {2: 0.9}, 3: {3: 0.9}, 4: {4: 0.9}, 5: {5: 0.9}}
    assert assign_positions([5, 4, 3, 2, 1], shares) == {1: 1, 2: 2, 3: 3, 4: 4, 5: 5}
    ours = lanes_from_positions({1: 1, 5: 5, 2: 2, 3: 3, 4: 4})
    assert ours == {"safe": [1, 5], "mid": [2], "off": [3, 4]}
    bucket = {"vs": {"1": {"3": 2.0}, "5": {"3": 0.0}}, "with": {}}
    res = lane_matchups(ours, {"off": [3], "mid": [], "safe": []}, bucket)
    assert res[0]["lane"] == "safe" and res[0]["advantage"] == 1.0 and res[0]["pairs_known"] == 2


def _m(won: bool, start: int, hero: int = 1, slot: int = 0, **kw):
    return {
        "radiant_win": won == (slot < 128),
        "player_slot": slot,
        "start_time": start,
        "duration": 1800,
        "hero_id": hero,
        "kills": 4,
        "deaths": 2,
        "assists": 6,
        **kw,
    }


def test_profile_analytics():
    assert (
        a.rank_name(53) == "Legend 3"
        and a.rank_name(80, 120) == "Immortal #120"
        and a.rank_name(None) is None
    )
    assert a.wilson_lower(0, 0) == 0 and 0 < a.wilson_lower(6, 10) < 0.6
    ms = [
        _m(True, 10_000),
        _m(True, 9_000),
        _m(False, 8_000),
        _m(False, 7_000),
        _m(False, 6_000),
    ]  # newest first
    st = a.streaks(ms)
    assert st["current"] == 2 and st["current_kind"] == "win" and st["longest_loss"] == 3
    sessions = a.sessions([_m(True, 0), _m(False, 2000), _m(True, 100_000)])
    assert [s["games"] for s in sessions] == [1, 2] and sessions[1]["results"] == ["W", "L"]
    pool = a.hero_pool([_m(True, 1, hero=5), _m(False, 2, hero=5), _m(True, 3, hero=6, slot=130)])
    assert pool[0]["hero"] == 5 and pool[0]["games"] == 2 and pool[0]["win_rate"] == 0.5
    assert len(a.rolling_win_rate([_m(True, i) for i in range(25)], window=20)) == 6
    assert a.lane_roles([_m(True, 1, lane_role=2), _m(True, 1, lane_role=2), _m(True, 1)]) == {"mid": 2}
    assert a.summary([])["win_rate"] is None
    assert sum(r["games"] for r in a.by_hour(ms)) == 5


class FlakyClient:
    def __init__(self, misses: int) -> None:
        self.misses = misses
        self.posts: list[str] = []

    def get(self, path, params=None, ttl=None):
        if self.misses:
            self.misses -= 1
            raise NotFoundError(path)
        return {"players": [{}], "duration": 2000}

    def post(self, path, params=None):
        self.posts.append(path)
        return {}


def test_postgame_polls_until_ready_and_requests_parse(ctx):
    ctx._client = FlakyClient(misses=2)
    ctx.settings.update({"request_parse": True})
    pg = PostGame(ctx, sleep=lambda s: None, delays=(1, 1, 1, 1))
    pg.jobs["7"] = {
        "match_id": "7",
        "status": "waiting",
        "attempts": 0,
        "parse_requested": False,
        "error": None,
    }
    pg._run("7")
    job = pg.status()[0]
    assert job["status"] == "ready" and job["attempts"] == 3 and job["parse_requested"]
    assert ctx._client.posts == ["request/7"]


def test_postgame_gives_up(ctx):
    ctx._client = FlakyClient(misses=99)
    pg = PostGame(ctx, sleep=lambda s: None, delays=(1, 1))
    pg.jobs["8"] = {
        "match_id": "8",
        "status": "waiting",
        "attempts": 0,
        "parse_requested": False,
        "error": None,
    }
    pg._run("8")
    assert pg.status()[0]["status"] == "gave_up"
