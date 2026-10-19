"""Heroes, search, items, traits and counter-item rules on the committed snapshot."""

from __future__ import annotations

import pytest

from d2bg.knowledge.counters import situational_items
from d2bg.knowledge.similar import cosine, most_similar
from d2bg.knowledge.traits import Trait


def test_snapshot_has_every_hero(data):
    assert len(data.heroes) >= 125
    assert data.patch.startswith("7.")


def test_aliases_point_at_real_heroes(data):
    aliases = data.knowledge_file("aliases.json")
    keys = {h.key for h in data.heroes}
    assert set(aliases) <= keys


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("am", "Anti-Mage"),
        ("qop", "Queen of Pain"),
        ("wr", "Windranger"),
        ("sf", "Shadow Fiend"),
        ("cm", "Crystal Maiden"),
        ("juggernot", "Juggernaut"),
        ("invo", "Invoker"),
        ("pa", "Phantom Assassin"),
        ("np", "Nature's Prophet"),
        ("1", "Anti-Mage"),
        ("lion", "Lion"),
    ],
)
def test_search_understands_shorthand_and_typos(data, query, expected):
    assert data.heroes.search(query)[0].name == expected


def test_get_by_any_reference(data):
    am = data.heroes.get(1)
    assert am is not None
    assert data.heroes.get("antimage") is am
    assert data.heroes.get("npc_dota_hero_antimage") is am
    assert data.heroes.get("Anti-Mage") is am
    assert data.heroes.get("magina") is am
    assert data.heroes.get("not a hero") is None


def test_parse_list_reports_unknown(data):
    found, unknown = data.heroes.parse_list("am, qop / wr\nzzzzzz")
    assert [h.name for h in found] == ["Anti-Mage", "Queen of Pain", "Windranger"]
    assert unknown == ["zzzzzz"]


def test_remaining_cost_uses_owned_components(data):
    items = data.items
    bkb = items.get("black_king_bar")
    axe = items.get("ogre_axe")
    assert bkb and axe and set(bkb.components) >= {"ogre_axe", "mithril_hammer"}
    assert items.remaining_cost("black_king_bar", []) == bkb.cost
    assert items.remaining_cost("black_king_bar", ["ogre_axe"]) == bkb.cost - axe.cost
    assert items.remaining_cost("black_king_bar", ["item_black_king_bar"]) == 0
    # One owned Ogre Axe can't pay for two.
    assert items.remaining_cost("black_king_bar", ["ogre_axe", "ogre_axe"]) == bkb.cost - axe.cost
    assert "black_king_bar" in items.builds_into("ogre_axe")
    prog = items.owned_progress("black_king_bar", ["ogre_axe"])
    assert prog["remaining"] == bkb.cost - axe.cost and 0 < prog["progress"] < 1


@pytest.mark.parametrize(
    ("hero", "trait"),
    [
        ("riki", Trait.INVISIBILITY),
        ("bounty_hunter", Trait.INVISIBILITY),
        ("phantom_lancer", Trait.ILLUSIONS),
        ("naga_siren", Trait.ILLUSIONS),
        ("lion", Trait.STUN),
        ("lion", Trait.HEX),
        ("silencer", Trait.SILENCE),
        ("necrolyte", Trait.HEAL),
        ("phantom_assassin", Trait.EVASION),
        ("dazzle", Trait.SAVE),
        ("broodmother", Trait.SUMMONS),
        ("zuus", Trait.GLOBAL),
        ("bristleback", Trait.ARMOR_REDUCTION),
    ],
)
def test_known_traits(shared_ctx, hero, trait):
    h = shared_ctx.data.heroes.require(hero)
    assert trait in shared_ctx.traits.of(h.id), shared_ctx.traits.view(h.id)


def test_traits_have_evidence_and_overrides_apply(shared_ctx):
    storm = shared_ctx.data.heroes.require("storm_spirit")
    assert Trait.ILLUSIONS not in shared_ctx.traits.of(storm.id)
    invoker = shared_ctx.data.heroes.require("invoker")
    assert shared_ctx.traits.of(invoker.id)[Trait.INVISIBILITY] == ["reviewed"]
    for view in shared_ctx.traits.view(shared_ctx.data.heroes.require("lion").id):
        assert view["evidence"] and view["label"]


def test_counter_items_exist_and_are_bought_this_patch(shared_ctx):
    items = shared_ctx.data.items
    pro = shared_ctx.data.load("pro_builds.json")
    bought: set[str] = set()
    if pro:
        for doc in pro["heroes"].values():
            bought.update(doc["items"]["median_timings"])
    for rule in shared_ctx.counter_rules:
        for key in rule.items:
            item = items.get(key)
            assert item is not None, f"{rule.id}: {key} is not an item"
            # The pro timing table only holds items with a recipe or costing 1000+ (not wards, dust, gem).
            if pro and (item.components or item.cost >= 1000):
                assert key in bought, f"{rule.id}: {key} not bought in any pro game this patch"


def test_situational_items_for_invisible_and_illusion_lineup(shared_ctx):
    h = shared_ctx.data.heroes
    enemies = [h.require(k).id for k in ("riki", "phantom_lancer", "lion")]
    rules = situational_items(
        enemies, shared_ctx.traits, shared_ctx.counter_rules, shared_ctx.data.items, h.name, owned=["dust"]
    )
    by_id = {r["id"]: r for r in rules}
    assert "Riki" in by_id["invisibility"]["heroes"]
    assert next(i for i in by_id["invisibility"]["items"] if i["key"] == "dust")["owned"] is True
    assert "Phantom Lancer" in by_id["illusions"]["heroes"]
    assert "magic" not in by_id  # needs three magic-damage heroes


def test_similarity(data):
    assert cosine(
        {str(i): float(i) for i in range(20)}, {str(i): float(i) for i in range(20)}
    ) == pytest.approx(1.0)
    assert cosine({"1": 1.0}, {"1": 1.0}) == 0.0  # too few shared heroes to say
    sims = most_similar(data.matchup_bucket("all"), 1, n=5)
    assert len(sims) == 5 and all(-1 <= s <= 1 for _, s in sims) and all(h != 1 for h, _ in sims)


@pytest.mark.parametrize(("hero", "trait"), [
    ("crystal_maiden", Trait.ROOT), ("axe", Trait.TAUNT), ("legion_commander", Trait.TAUNT),
    ("doom_bringer", Trait.SILENCE),
])
def test_more_disables(shared_ctx, hero, trait):
    assert trait in shared_ctx.traits.of(shared_ctx.data.heroes.require(hero).id)


@pytest.mark.parametrize("hero", ["invoker", "doom_bringer", "rubick"])
def test_placeholder_slots_are_not_passives(shared_ctx, hero):
    assert Trait.PASSIVES not in shared_ctx.traits.of(shared_ctx.data.heroes.require(hero).id)


def test_talent_placeholders_become_x(data):
    jugg = data.heroes.require("juggernaut")
    names = [t.name for t in jugg.talents]
    assert "+X Blade Fury DPS" in names
    assert not any("{" in n for h in data.heroes for n in (t.name for t in h.talents))
