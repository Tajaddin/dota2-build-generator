"""Tests for d2bg.draft.advisor on tiny hand-written matrices."""

import pytest

from d2bg.draft.advisor import (
    counters,
    hot_counters,
    meta,
    role_clash_penalty,
    score,
    suggest,
)
from d2bg.pipeline.matchups import build_matrix
from tests.d2bg.test_matchups import fixture_matches

BUCKET = {
    "heroes": {
        "1": {"wr": 0.52, "pick_rate": 0.2},
        "2": {"wr": 0.55, "pick_rate": 0.005},  # below 1%: never meta
        "3": {"wr": 0.51, "pick_rate": 0.3},
        "4": {"wr": 0.49, "pick_rate": 0.1},
        "5": {"wr": 0.53, "pick_rate": 0.01},  # exactly 1%: allowed
        "6": {"wr": 0.50, "pick_rate": 0.05},
    },
    "vs": {
        "1": {"4": 2.0, "5": -1.0, "6": None},
        "2": {"4": -3.0, "5": 4.0, "6": 1.0},
        "3": {"4": 1.0, "5": 1.0},
        "4": {"1": -2.0, "2": 3.0, "3": -1.0, "6": -0.5},
        "5": {"1": 1.0, "2": -4.0, "3": -1.0, "6": 2.0},
    },
    "with": {
        "1": {"2": 2.0},
        "2": {"1": 6.0, "3": None},
        "3": {"1": -2.0},
    },
}

ROLES = {
    1: {"carry"},
    2: {"carry"},
    3: {"carry", "mid"},
    4: {"support"},
    5: {"support", "offlane"},
    6: set(),
}


def test_score_is_mean_vs_enemies():
    assert score(1, BUCKET, enemies=[4, 5]) == pytest.approx(0.5)
    assert score(3, BUCKET, enemies=[4, 5]) == pytest.approx(1.0)
    assert score(6, BUCKET, enemies=[4, 5]) == pytest.approx(0.0)  # no data


def test_score_skips_null_pairs_in_the_mean():
    assert score(1, BUCKET, enemies=[4, 6]) == pytest.approx(2.0)  # not (2 + 0) / 2
    assert score(1, BUCKET, enemies=[6]) == pytest.approx(0.0)


def test_score_adds_weighted_synergy():
    assert score(2, BUCKET, enemies=[4, 5], allies=[1], w=0.5) == pytest.approx(0.5 + 3.0)
    assert score(2, BUCKET, enemies=[4, 5], allies=[1], w=0.0) == pytest.approx(0.5)
    assert score(3, BUCKET, enemies=[4, 5], allies=[1], w=1.0) == pytest.approx(1.0 - 2.0)
    with pytest.raises(ValueError):
        score(1, BUCKET, enemies=[4], w=1.5)


def test_role_clash_when_only_role_is_taken():
    assert role_clash_penalty(2, [1], ROLES) == 10.0  # both carry-only
    assert role_clash_penalty(3, [1], ROLES) == 0.0  # 3 can go mid
    assert role_clash_penalty(1, [3], ROLES) == 0.0  # 3 moves to mid
    assert role_clash_penalty(2, [1, 3], ROLES) == 10.0  # carry and mid both taken
    assert role_clash_penalty(3, [1, 2], ROLES) == 0.0  # adds mid to a team that clashes already
    assert role_clash_penalty(6, [1], ROLES) == 0.0  # unknown roles never clash
    assert role_clash_penalty(2, [], ROLES) == 0.0
    assert role_clash_penalty(2, [1], None) == 0.0


def test_suggest_respects_bans_blacklist_and_ranks():
    out = suggest(BUCKET, enemies=[4], allies=[1], bans=[5], blacklist=[6], w=0.5, hero_roles=ROLES)
    # 2: -3 + 0.5*6 - 10 (clash with carry 1);  3: 1 + 0.5*(-2)
    assert out == [(3, pytest.approx(0.0)), (2, pytest.approx(-10.0))]


def test_suggest_whitelist_and_role_filter():
    assert [h for h, _ in suggest(BUCKET, enemies=[4], whitelist=[2, 3])] == [3, 2]
    assert [h for h, _ in suggest(BUCKET, hero_roles=ROLES, role="support")] == [4, 5]
    assert [h for h, _ in suggest(BUCKET, enemies=[4], n=1)] == [1]


def test_counters_are_heroes_enemy_does_worst_against():
    assert counters(4, BUCKET) == [(1, 2.0), (3, 1.0), (6, 0.5), (2, -3.0)]
    assert counters(4, BUCKET, n=2) == [(1, 2.0), (3, 1.0)]
    assert counters(5, BUCKET, exclude=[2]) == [(3, 1.0), (1, -1.0), (6, -2.0)]
    assert counters(99, BUCKET) == []


def test_hot_counters_need_two_enemies():
    hot = hot_counters([4, 5], BUCKET, n=3)
    assert [(h["hero"], sorted(h["enemies"]), h["advantage"]) for h in hot] == [
        (3, [4, 5], pytest.approx(2.0)),
        (1, [4, 5], pytest.approx(1.0)),
    ]


def test_hot_counters_skip_banned_heroes():
    hot = hot_counters([4, 5], BUCKET, n=3, exclude=[3])
    assert [h["hero"] for h in hot] == [1, 2, 6]  # 1 and 2 tie at 1.0 -> id order
    assert all(h["hero"] != 3 for h in hot)


def test_meta_filters_by_pick_rate():
    assert meta(BUCKET, n=3) == [(5, 0.53), (1, 0.52), (3, 0.51)]
    assert meta(BUCKET, n=2, exclude=[5]) == [(1, 0.52), (3, 0.51)]


def test_end_to_end_on_built_matrix():
    bucket = build_matrix(fixture_matches(), k=20, min_pair_games=5)["buckets"]["1-2"]
    out = suggest(bucket, enemies=[3])
    # vs(2,3): 10 games, 7 wins; vs(1,3): 6 games, 4 wins; vs(4,3): 4 games -> null
    assert [h for h, _ in out] == [2, 1, 4]
    assert out[0][1] == pytest.approx(100 * ((7 + 20 * 17 / 30) / 30 - 17 / 30), abs=1e-3)
    assert out[1][1] == pytest.approx(100 * (14 / 26 - 0.5), abs=1e-3)
    assert out[2][1] == 0.0
