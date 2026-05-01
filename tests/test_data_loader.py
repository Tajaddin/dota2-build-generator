"""Tests for data_loader module."""

from logic.data_loader import DataLoader


class TestDataLoader:
    def test_load_all_heroes(self):
        loader = DataLoader()
        heroes = loader.get_all_heroes()
        assert len(heroes) >= 120
        assert all("id" in h for h in heroes)
        assert all("name" in h for h in heroes)

    def test_load_hero_by_id(self):
        loader = DataLoader()
        hero = loader.get_hero("anti_mage")
        assert hero["name"] == "Anti-Mage"
        assert len(hero["builds"]) >= 2

    def test_load_items(self):
        loader = DataLoader()
        items = loader.get_all_items()
        assert "bfury" in items
        assert items["bfury"]["name"] == "Battle Fury"

    def test_get_heroes_by_role(self):
        loader = DataLoader()
        carries = loader.get_heroes_by_role("Carry")
        assert len(carries) >= 20
        mids = loader.get_heroes_by_role("Mid")
        assert len(mids) >= 15
        supports = loader.get_heroes_by_role("Support")
        assert len(supports) >= 15

    def test_hero_build_has_required_fields(self):
        loader = DataLoader()
        hero = loader.get_hero("anti_mage")
        build = list(hero["builds"].values())[0]
        assert "label" in build
        assert "early_game" in build
        assert "mid_game" in build
        assert "late_game" in build
        assert "skill_build" in build
        assert "strategy" in build
        assert len(build["early_game"]) == 6
        assert len(build["mid_game"]) == 6
        assert len(build["late_game"]) == 6

    def test_synthesizes_missing_heroes_from_bundled_stats(self):
        loader = DataLoader()
        hero = loader.get_hero("necrophos")
        assert hero is not None
        assert hero["name"] == "Necrophos"
        assert hero["auto_generated"] is True
        assert "Mid" in hero["roles"]
        build = list(hero["builds"].values())[0]
        assert build["label"] == "OpenDota Meta"
        assert len(build["early_game"]) == 6
        assert len(build["mid_game"]) == 6
        assert len(build["late_game"]) == 6
