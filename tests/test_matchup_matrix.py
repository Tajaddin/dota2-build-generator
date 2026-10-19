"""Tests for ml/build_matchup_matrix.py on a 20-match hand-computed fixture.

Fixture (teams are 2v2 so every number can be checked by hand):

  m1-m6   tier 12-25  R [1,2] vs D [3,4]   radiant wins m1-m4
  m7-m10  tier 12-25  R [1,3] vs D [2,4]   radiant wins m7
  m11-m18 tier 51-65  R [1,4] vs D [2,3]   radiant wins all
  m19     tier 75     R [1,4] vs D [2,3]   dire wins
  m20     no rank     R [1,4] vs D [2,3]   dire wins

Bucket 1-2, k=20: hero 1 is 5/10, hero 2 7/10, hero 3 3/10, hero 4 5/10.
"""
import json

import pytest

from ml.build_matchup_matrix import (
    PublicMatchesClient,
    bucket_for,
    build_matrix,
    load_matrix,
    normalize_match,
    write_matrix,
)


def _m(i, radiant, dire, radiant_win, tier, start_time=None):
    return {"match_id": 1000 + i, "radiant_team": radiant, "dire_team": dire,
            "radiant_win": radiant_win, "avg_rank_tier": tier,
            "start_time": start_time}


def fixture_matches():
    tiers_low = [12, 15, 21, 22, 25, 13, 14, 23, 24, 11]
    tiers_mid = [51, 52, 55, 61, 62, 63, 64, 65]
    ms = []
    for i in range(6):
        ms.append(_m(i + 1, [1, 2], [3, 4], i < 4, tiers_low[i]))
    for i in range(4):
        ms.append(_m(i + 7, [1, 3], [2, 4], i == 0, tiers_low[6 + i]))
    for i in range(8):
        ms.append(_m(i + 11, [1, 4], [2, 3], True, tiers_mid[i]))
    ms.append(_m(19, [1, 4], [2, 3], False, 75))
    ms.append(_m(20, [1, 4], [2, 3], False, None))
    return ms


@pytest.fixture
def doc():
    return build_matrix(fixture_matches(), k=20, min_pair_games=5)


def test_bucket_for_uses_medal_from_rank_tier():
    assert bucket_for(15) == "1-2"
    assert bucket_for(25) == "1-2"
    assert bucket_for(35) == "3-4"
    assert bucket_for(65) == "5-6"
    assert bucket_for(80) == "7-8"
    assert bucket_for(None) is None
    assert bucket_for(0) is None


def test_bucketing_counts(doc):
    sizes = {b: v["n_matches"] for b, v in doc["buckets"].items()}
    assert sizes == {"1-2": 10, "3-4": 0, "5-6": 8, "7-8": 1, "all": 20}
    assert doc["n_matches"] == 20
    assert doc["version"] == 1


def test_base_wr_is_smoothed_toward_half(doc):
    heroes = doc["buckets"]["1-2"]["heroes"]
    assert heroes["1"]["wr"] == pytest.approx(15 / 30)   # (5 + 10) / (10 + 20)
    assert heroes["2"]["wr"] == pytest.approx(17 / 30)
    assert heroes["3"]["wr"] == pytest.approx(13 / 30)
    assert heroes["4"]["wr"] == pytest.approx(15 / 30)
    assert heroes["1"]["pick_rate"] == pytest.approx(1.0)
    # all bucket: hero 1 wins 5 + 8 of 20
    assert doc["buckets"]["all"]["heroes"]["1"]["wr"] == pytest.approx(23 / 40)


def test_pair_advantage_smoothed_toward_base_wr(doc):
    vs = doc["buckets"]["1-2"]["vs"]
    with_ = doc["buckets"]["1-2"]["with"]
    # 1 vs 3: 6 games, 4 wins. (4 + 20*0.5) / 26 - 0.5
    assert vs["1"]["3"] == pytest.approx(100 * (14 / 26 - 0.5), abs=1e-3)
    # 1 vs 4: 10 games, 5 wins -> exactly base
    assert vs["1"]["4"] == pytest.approx(0.0, abs=1e-3)
    # 3 vs 1: 6 games, 2 wins. (2 + 20*13/30) / 26 - 13/30
    assert vs["3"]["1"] == pytest.approx(100 * ((2 + 20 * 13 / 30) / 26 - 13 / 30), abs=1e-3)
    # 2 vs 4: 6 games, 4 wins
    assert vs["2"]["4"] == pytest.approx(100 * ((4 + 20 * 17 / 30) / 26 - 17 / 30), abs=1e-3)
    # 1 with 2: 6 games, 4 wins
    assert with_["1"]["2"] == pytest.approx(100 * (14 / 26 - 0.5), abs=1e-3)


def test_pairs_below_threshold_are_null(doc):
    b = doc["buckets"]["1-2"]
    assert b["vs"]["1"]["2"] is None       # 4 games < 5
    assert b["with"]["1"]["3"] is None     # 4 games < 5
    assert "1" not in b["vs"]["1"]         # a hero never faces itself


def test_default_threshold_nulls_everything_on_small_data():
    full = build_matrix(fixture_matches())
    for bucket in full["buckets"].values():
        for table in ("vs", "with"):
            for row in bucket[table].values():
                assert all(v is None for v in row.values())


def test_normalize_accepts_string_teams_and_jsonl_rows():
    assert normalize_match({"radiant_team": "1,2", "dire_team": "3,4",
                            "radiant_win": True})["radiant"] == [1, 2]
    row = {"match_id": 5, "radiant_win": False, "avg_rank_tier": 44,
           "players": [{"hero_id": 7, "is_radiant": True},
                       {"hero_id": 8, "is_radiant": False}]}
    nm = normalize_match(row)
    assert nm["radiant"] == [7] and nm["dire"] == [8] and nm["avg_rank_tier"] == 44
    assert normalize_match({"radiant_team": [1], "dire_team": [2]}) is None
    assert normalize_match({"radiant_team": [], "dire_team": [2], "radiant_win": True}) is None


def test_source_week_from_newest_match():
    ms = fixture_matches()
    ms[0]["start_time"] = 1_792_000_000  # 2026-10-14 UTC, ISO week 42
    assert build_matrix(ms)["source_week"] == "2026-W42"


def test_write_and_load_latest(tmp_path, doc):
    from datetime import date
    write_matrix(doc, tmp_path, date(2026, 10, 9))
    p = write_matrix(doc, tmp_path, date(2026, 10, 16))
    assert p.name == "2026-10-16.json"
    loaded = load_matrix(out_dir=tmp_path)
    assert loaded["buckets"]["1-2"]["vs"]["1"]["2"] is None
    assert json.loads(p.read_text())["n_matches"] == 20


# ── Collector, with a fake HTTP layer ──────────────────────────────

class _Resp:
    def __init__(self, status, rows=None):
        self.status_code = status
        self._rows = rows

    def json(self):
        return self._rows


def _row(mid, start, lobby=7, mode=22):
    return {"match_id": mid, "start_time": start, "lobby_type": lobby,
            "game_mode": mode, "radiant_team": [1], "dire_team": [2],
            "radiant_win": True, "avg_rank_tier": 33}


def test_collector_pages_backwards_filters_and_caches(tmp_path):
    now = 2_000_000_000
    pages = {
        None: [_row(300, now), _row(299, now, lobby=0), _row(298, now)],
        298: [_row(297, now), _row(296, now, mode=1)],
        296: [_row(295, now - 20 * 86400)],  # older than the window -> stop
    }
    calls, sleeps = [], []

    def fake_get(url, params, timeout):
        cursor = params.get("less_than_match_id")
        calls.append(cursor)
        if len(calls) == 2:
            return _Resp(429)  # back off once, then retry
        return _Resp(200, pages[cursor])

    client = PublicMatchesClient(cache_dir=tmp_path, interval=0,
                                 http_get=fake_get, sleep=sleeps.append)
    rows = client.collect(max_calls=10, days=14, now=now)
    assert [r["match_id"] for r in rows] == [300, 298, 297, 295]
    assert calls == [None, 298, 298, 296]
    assert 60 in sleeps

    # Second run: older pages come from the cache, only the newest is refetched.
    calls.clear()
    client2 = PublicMatchesClient(cache_dir=tmp_path, interval=0,
                                  http_get=lambda url, params, timeout: (
                                      calls.append(params.get("less_than_match_id"))
                                      or _Resp(200, pages[params.get("less_than_match_id")])),
                                  sleep=lambda s: None)
    assert len(client2.collect(max_calls=10, days=14, now=now)) == 4
    assert calls == [None]


def test_collector_respects_max_calls(tmp_path):
    def fake_get(url, params, timeout):
        cursor = params.get("less_than_match_id") or 10_000
        return _Resp(200, [_row(cursor - 1, 2_000_000_000)])

    client = PublicMatchesClient(cache_dir=tmp_path, interval=0,
                                 http_get=fake_get, sleep=lambda s: None)
    client.collect(max_calls=3, days=14, now=2_000_000_000)
    assert client.requests_made == 3
