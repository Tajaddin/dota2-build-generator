"""The HTTP API end to end with FastAPI's TestClient. OpenDota is mocked with respx."""

from __future__ import annotations

import json
import time

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from d2bg import paths
from d2bg.api.app import create_app
from tests.d2bg.test_gsi import PLAYING, _fake_steam

BASE = "https://api.opendota.com/api"


@pytest.fixture
def app(ctx, tmp_path):
    return create_app(ctx, port=4242, static_dir=tmp_path / "no-ui")


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def _gsi(ctx, **overrides):
    return {**PLAYING, **overrides, "auth": {"token": ctx.settings.get().gsi_token}}


def test_health_version_and_ui_placeholder(client):
    assert client.get("/health").json()["ok"] is True
    v = client.get("/api/version").json()
    assert v["patch"].startswith("7.") and v["timer_patch"].startswith("7.41")
    page = client.get("/draft")
    assert page.status_code == 200 and "not built" in page.text
    assert client.get("/api/nope").status_code == 404


def test_spa_serves_built_files(ctx, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "a.js").write_text("js")
    with TestClient(create_app(ctx, static_dir=dist)) as c:
        assert c.get("/").text == "<html>app</html>"
        assert c.get("/live/anything").text == "<html>app</html>"
        assert c.get("/assets/a.js").text == "js"
        assert c.get("/../pyproject.toml").text == "<html>app</html>"


def test_gsi_requires_the_token(client, ctx):
    assert client.post("/gsi", json={**PLAYING, "auth": {"token": "wrong"}}).status_code == 403
    assert client.post("/gsi", json={k: v for k, v in PLAYING.items() if k != "auth"}).status_code == 403
    assert (
        client.post("/gsi", content=b"not json", headers={"content-type": "application/json"}).status_code
        == 400
    )
    assert client.post("/gsi", json=_gsi(ctx)).json() == {"ok": True}
    live = client.get("/api/live").json()
    assert live["phase"] == "in_game" and live["hero"]["name"] == "Juggernaut"
    assert live["connection"]["connected"] is True and live["connection"]["source"] == "game"
    assert ctx.settings.get().account_id == 123456  # learned from GSI


def test_gsi_only_from_this_computer(ctx, tmp_path):
    app = create_app(ctx, lan=True, static_dir=tmp_path)
    token = ctx.settings.get().lan_token
    with TestClient(app, client=("192.168.1.20", 5000)) as phone:
        assert phone.get("/api/version").status_code == 403
        assert phone.get(f"/api/version?token={token}").status_code == 200
        assert phone.post(f"/gsi?token={token}", json=_gsi(ctx)).status_code == 403


def test_lan_off_rejects_other_devices(ctx, tmp_path):
    with TestClient(create_app(ctx, lan=False, static_dir=tmp_path), client=("10.0.0.2", 1)) as other:
        token = ctx.settings.get().lan_token
        assert other.get(f"/api/version?token={token}").status_code == 403


def test_live_stream_sends_a_snapshot(client, ctx):
    client.post("/gsi", json=_gsi(ctx))
    with client.stream("GET", "/api/live/stream?once=true") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        line = next(line for line in r.iter_lines() if line.startswith("data: "))
    assert json.loads(line[6:])["hero"]["name"] == "Juggernaut"


def test_mark_and_reset(client, ctx):
    client.post("/gsi", json=_gsi(ctx))
    snap = client.post("/api/live/mark", json={"what": "roshan", "clock": 600}).json()
    assert next(t for t in snap["timers"] if t["id"] == "roshan")["at"] == 1080
    assert client.post("/api/live/mark", json={"what": "bad"}).status_code == 422
    client.post("/api/live/reset")
    assert client.get("/api/live").json()["phase"] == "waiting"


def test_demo_runs_and_stops(client):
    assert client.post("/api/demo", json={"hero": "nobody"}).status_code == 404
    r = client.post("/api/demo", json={"hero": "lion", "speed": 64, "minutes": 2}).json()
    assert r["frames"] > 10
    deadline = time.time() + 10
    while time.time() < deadline and client.get("/api/live").json().get("phase") != "post_game":
        time.sleep(0.1)
    assert client.get("/api/live").json()["demo"] is True
    client.post("/api/replay/stop")
    assert client.get("/api/replay").json()["running"] is False


def test_recordings_and_replay_path_safety(client, ctx):
    client.post("/gsi", json=_gsi(ctx))
    recs = client.get("/api/recordings").json()
    assert recs and recs[0]["name"].endswith(".jsonl.gz")
    assert client.post("/api/replay", json={"name": "../settings.json"}).status_code == 404
    svc = client.app.state.services
    svc.recorder.close()
    r = client.post("/api/replay", json={"name": recs[0]["name"], "speed": 64})
    assert r.status_code == 200 and r.json()["frames"] >= 1


def test_gsi_setup_install_and_remove(client, tmp_path):
    _, dota = _fake_steam(tmp_path)
    st = client.get("/api/gsi/status", params={"path": str(dota)}).json()
    assert st["dota_found"] and not st["installed"] and st["port"] == 4242
    assert client.post("/api/gsi/install", json={"path": str(dota)}).json()["installed"] is True
    assert client.get("/api/gsi/status", params={"path": str(dota)}).json()["current"] is True
    assert client.post("/api/gsi/remove", json={"path": str(dota)}).json()["removed"] is True
    assert client.post("/api/gsi/install", json={"path": str(tmp_path / "nowhere")}).status_code == 400


def test_heroes_items_meta_build(client):
    heroes = client.get("/api/heroes").json()
    assert len(heroes) >= 125 and {"traits", "positions", "win_rate"} <= set(heroes[0])
    assert client.get("/api/heroes/search", params={"q": "qop"}).json()[0]["name"] == "Queen of Pain"
    detail = client.get("/api/heroes/am").json()
    assert detail["name"] == "Anti-Mage" and detail["abilities"] and detail["countered_by"]
    assert client.get("/api/heroes/zzzz").status_code == 404
    b = client.get("/api/heroes/lion/build").json()
    assert b["hero"]["name"] == "Lion" and "skills" in b and "items" in b
    assert client.get("/api/heroes/lion/build.txt").text.startswith("Lion build")
    items = client.get("/api/items").json()
    assert any(i["key"] == "black_king_bar" for i in items)
    bkb = client.get("/api/items/black_king_bar").json()
    assert bkb["name"] == "Black King Bar" and bkb["components_detail"]
    assert client.get("/api/items/zzz").status_code == 404
    for source in ("bracket", "pro", "turbo", "matrix"):
        meta = client.get("/api/meta", params={"source": source}).json()
        assert meta["rows"], source
        assert {r["tier"] for r in meta["rows"]} <= {"S", "A", "B", "C", "D"}
    assert client.get("/api/meta", params={"bracket": 9}).status_code == 422
    assert client.get("/api/timers").json()["rules"]


def test_draft_endpoint(client, ctx):
    h = ctx.data.heroes
    body = {
        "allies": [h.require("juggernaut").id],
        "enemies": [h.require(k).id for k in ("riki", "lion")],
        "bans": [h.require("pudge").id],
        "compare": [h.require("axe").id],
        "side": "radiant",
    }
    res = client.post("/api/draft", json=body).json()
    taken = set(body["allies"]) | set(body["enemies"]) | set(body["bans"])
    assert res["suggestions"] and not taken & {c["hero"] for c in res["suggestions"]}
    assert set(res["by_position"]) == {"1", "2", "3", "4", "5"}
    assert 0 < res["win"]["us"] < 1
    assert any(r["id"] == "invisibility" for r in res["items"])
    assert res["compare"][0]["hero"] == h.require("axe").id
    assert client.post("/api/draft", json={"enemies": [99999]}).status_code == 422
    assert client.post("/api/draft", json={"enemies": [1, 2, 3, 4, 5, 6]}).status_code == 422
    parsed = client.post("/api/heroes/parse", json={"text": "am, qop, xyzzy"}).json()
    assert [x["name"] for x in parsed["heroes"]] == ["Anti-Mage", "Queen of Pain"] and parsed["unknown"] == [
        "xyzzy"
    ]
    assert client.get("/api/situational", params={"enemies": f"{h.require('riki').id}"}).json()


def test_settings_roundtrip_masks_secrets(client):
    s = client.get("/api/settings").json()
    assert "gsi_token" not in s and "lan_token" not in s
    updated = client.put("/api/settings", json={"rank_bucket": "5-6", "opendota_api_key": "abc"}).json()
    assert updated["rank_bucket"] == "5-6" and updated["opendota_api_key"] == "set"
    # Sending the masked value back keeps the key.
    assert client.put("/api/settings", json={"opendota_api_key": "set"}).json()["opendota_api_key"] == "set"
    assert client.put("/api/settings", json={"rank_bucket": "9-9"}).status_code == 422
    assert client.put("/api/settings", json={"gsi_token": "x"}).status_code == 422


def test_data_status(client):
    st = client.get("/api/data/status").json()
    assert st["files"]["heroes.json"]["present"] and "usage" in st
    assert client.post("/api/data/refresh", json={"steps": ["nope"]}).status_code == 422


# ── OpenDota-backed routes (mocked) ────────────────────────────────


@pytest.fixture
def live_client(ctx, tmp_path, monkeypatch):
    from d2bg.opendota import OpenDotaClient

    ctx._client = OpenDotaClient(cache_dir=tmp_path / "odcache", min_interval=0, sleep=lambda s: None)
    with TestClient(create_app(ctx, static_dir=tmp_path)) as c:
        yield c


def _match(account_id: int, hero: int, radiant_win: bool, start: int, slot: int = 0) -> dict:
    return {
        "match_id": start,
        "player_slot": slot,
        "radiant_win": radiant_win,
        "hero_id": hero,
        "start_time": start,
        "duration": 2000,
        "kills": 5,
        "deaths": 2,
        "assists": 8,
        "lobby_type": 7,
        "game_mode": 22,
        "lane_role": 1,
    }


@respx.mock
def test_profile_endpoints(live_client, ctx):
    assert live_client.get("/api/profile").status_code == 400  # no account yet
    respx.get(f"{BASE}/players/77").mock(
        return_value=httpx.Response(
            200, json={"profile": {"personaname": "Taj", "avatarfull": "a.png"}, "rank_tier": 53}
        )
    )
    matches = [_match(77, 8 if i % 3 else 1, i % 2 == 0, 1_790_000_000 - i * 3000) for i in range(40)]
    respx.get(f"{BASE}/players/77/matches").mock(return_value=httpx.Response(200, json=matches))
    respx.get(f"{BASE}/players/77/peers").mock(
        return_value=httpx.Response(
            200, json=[{"account_id": 5, "personaname": "friend", "with_games": 10, "with_win": 6}]
        )
    )
    respx.get(f"{BASE}/search").mock(
        return_value=httpx.Response(200, json=[{"account_id": 9, "personaname": "x"}])
    )
    p = live_client.get("/api/profile", params={"account_id": 77}).json()
    assert p["name"] == "Taj" and p["rank"] == "Legend 3"
    assert p["summary"]["games"] == 40 and p["hero_pool"][0]["games"] >= 13
    assert p["sessions"] and p["streaks"]["current"] >= 1
    assert live_client.get("/api/profile/peers", params={"account_id": 77}).json()[0]["with_win_rate"] == 0.6
    assert live_client.get("/api/players/search", params={"q": "xx"}).json()[0]["account_id"] == 9
    assert live_client.get("/api/players/search", params={"q": "123"}).json() == [
        {"account_id": 123, "name": None}
    ]


@respx.mock
def test_match_review_endpoint(live_client, ctx):
    jugg = ctx.data.heroes.require("juggernaut").id
    bkb = ctx.data.items.get("black_king_bar")
    assert bkb is not None
    me = {
        "account_id": 77,
        "player_slot": 0,
        "hero_id": jugg,
        "kills": 10,
        "deaths": 2,
        "assists": 5,
        "gold_per_min": 600,
        "xp_per_min": 650,
        "last_hits": 300,
        "item_0": bkb.id,
        "benchmarks": {"gold_per_min": {"raw": 600, "pct": 0.9}, "last_hits_per_min": {"raw": 6, "pct": 0.2}},
        "purchase_log": [{"time": 1500, "key": "black_king_bar"}],
        "lh_t": list(range(0, 110, 10)),
    }
    others = [{"account_id": None, "player_slot": s, "hero_id": h} for s, h in ((1, 1), (128, 2), (129, 3))]
    doc = {
        "match_id": 1,
        "duration": 2400,
        "radiant_win": True,
        "players": [me, *others],
        "version": 21,
        "radiant_score": 30,
        "dire_score": 20,
    }
    respx.get(f"{BASE}/matches/1").mock(return_value=httpx.Response(200, json=doc))
    respx.get(f"{BASE}/matches/2").mock(return_value=httpx.Response(404, json={"error": "Not Found"}))
    respx.post(f"{BASE}/request/1").mock(return_value=httpx.Response(200, json={"job": {"jobId": 5}}))
    r = live_client.get("/api/matches/1", params={"account_id": 77}).json()
    assert r["parsed"] and r["me"]["won"] and r["me"]["row"]["items"][0]["name"] == "Black King Bar"
    assert any("top 10%" in n for n in r["notes"]) and any("20th percentile" in n for n in r["notes"])
    assert r["me"]["row"]["lh_10"] == 100
    assert len(r["radiant"]) == 2 and len(r["dire"]) == 2
    assert live_client.get("/api/matches/2").status_code == 404
    assert live_client.post("/api/matches/1/parse").json()["requested"] is True
    assert live_client.get("/api/postgame").json() == []
    assert paths.user_dir().exists()
