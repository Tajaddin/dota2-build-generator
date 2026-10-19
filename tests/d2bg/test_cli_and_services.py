"""CLI commands, the draft service, hero builds and settings storage."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from d2bg.builds.benchmarks import compare, percentile_of, value_at
from d2bg.builds.guide import build_order, build_text, hero_build, next_items
from d2bg.cli import app
from d2bg.draft.service import DraftRequest, analyze
from d2bg.settings import Settings, SettingsStore
from tests.d2bg.test_gsi import _fake_steam

runner = CliRunner()


def test_cli_version_draft_build():
    assert runner.invoke(app, ["version"]).stdout.strip() == "2.0.0"
    r = runner.invoke(app, ["draft", "--enemy", "pa, lion, xyzzy", "--ally", "jugg"])
    assert r.exit_code == 0, r.output
    assert "Suggested picks" in r.stdout and "unknown heroes: xyzzy" in r.output
    b = runner.invoke(app, ["build", "invoker"])
    assert b.exit_code == 0 and b.stdout.startswith("Invoker build")
    assert runner.invoke(app, ["build", "qqqqqq"]).exit_code == 1


def test_cli_gsi_commands(tmp_path):
    _, dota = _fake_steam(tmp_path)
    r = runner.invoke(app, ["gsi", "install", "--path", str(dota)])
    assert r.exit_code == 0 and "installed" in r.stdout
    status = json.loads(runner.invoke(app, ["gsi", "status", "--path", str(dota)]).stdout)
    assert status["installed"] and status["current"]
    assert "removed" in runner.invoke(app, ["gsi", "remove", "--path", str(dota)]).stdout


def test_cli_data_status():
    doc = json.loads(runner.invoke(app, ["data", "status"]).stdout)
    assert doc["files"]["heroes.json"]["present"]


def test_draft_service_pool_modes(shared_ctx):
    h = shared_ctx.data.heroes
    enemies = [h.require(k).id for k in ("phantom_assassin", "lion")]
    pool = [h.require(k).id for k in ("axe", "juggernaut", "lina")]
    settings = Settings()
    only = analyze(shared_ctx, DraftRequest(enemies=enemies, pool_mode="only", hero_pool=pool), settings)
    assert {c["hero"] for c in only["suggestions"]} <= set(pool)
    boost = analyze(
        shared_ctx, DraftRequest(enemies=enemies, pool_mode="boost", hero_pool=pool, n=40), settings
    )
    plain = analyze(shared_ctx, DraftRequest(enemies=enemies, n=40), settings)
    rank = {c["hero"]: i for i, c in enumerate(boost["suggestions"])}
    rank_plain = {c["hero"]: i for i, c in enumerate(plain["suggestions"])}
    assert any(rank.get(p, 99) < rank_plain.get(p, 99) for p in pool)
    small = analyze(shared_ctx, DraftRequest(enemies=enemies, rank_bucket="7-8"), settings)
    assert small["bucket"] == "7-8" and small["sample_matches"] > 0
    full = analyze(
        shared_ctx,
        DraftRequest(
            allies=[h.require(k).id for k in ("juggernaut", "lion", "axe", "invoker", "crystal_maiden")],
            enemies=[h.require(k).id for k in ("phantom_assassin", "riki", "pudge", "zuus", "earthshaker")],
        ),
        settings,
    )
    assert len(full["lanes"]) == 3 and full["win"]["detail"]["complete"]
    assert sorted(full["positions"]["ours"].values()) == [1, 2, 3, 4, 5]


def test_hero_build_and_text(shared_ctx):
    b = hero_build(shared_ctx, shared_ctx.data.heroes.require("juggernaut").id)
    assert b["pro"]["games"] > 0 and b["skills"]["by_level"] and b["items"]["order"]
    assert all(o["median"].count(":") == 1 for o in b["items"]["order"])
    assert {t["level"] for t in b["skills"]["talents"]} <= {10, 15, 20, 25}
    text = build_text(b)
    assert "Items:" in text and "Skills:" in text


def test_next_items_skips_owned_and_folded_parts(shared_ctx):
    items = shared_ctx.data.items
    order = [{"key": "power_treads"}, {"key": "yasha"}, {"key": "manta"}, {"key": "black_king_bar"}]
    nxt = next_items(order, ["power_treads", "manta"], items)
    assert [n["item"] for n in nxt] == ["black_king_bar"]
    assert build_order(shared_ctx, shared_ctx.data.heroes.require("lion").id)


def test_benchmark_interpolation():
    pts = [[0.1, 100], [0.5, 200], [0.9, 300]]
    assert percentile_of(150, pts) == pytest.approx(0.3)
    assert percentile_of(400, pts) == 0.9
    assert percentile_of(50, pts) == pytest.approx(0.05)
    assert value_at(0.5, pts) == 200 and value_at(0.7, pts) == 250
    assert percentile_of(1, []) is None
    rows = compare({"gold_per_min": 200}, {"gold_per_min": pts})
    assert rows[0]["percentile"] == 0.5 and rows[0]["median"] == 200


def test_settings_store(tmp_path):
    store = SettingsStore(tmp_path / "s.json")
    assert store.get().gsi_token and store.get().gsi_token != store.get().lan_token
    store.update({"synergy_weight": 0.8})
    assert SettingsStore(tmp_path / "s.json").get().synergy_weight == 0.8
    with pytest.raises(ValueError):
        store.update({"gsi_token": "x"})
    assert store.set_account_if_missing(5) and not store.set_account_if_missing(6)
    assert store.get().account_id == 5
    (tmp_path / "bad.json").write_text("{not json")
    fresh = SettingsStore(tmp_path / "bad.json")
    assert fresh.get().account_id is None and (tmp_path / "bad.corrupt.json").exists()
