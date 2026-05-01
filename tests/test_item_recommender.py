"""Tests for item recommender."""

from logic.item_recommender import ItemRecommender


class TestItemRecommender:
    def setup_method(self):
        self.recommender = ItemRecommender("data")

    def test_recommend_returns_required_fields(self):
        rec = self.recommender.recommend(
            my_hero="drow_ranger",
            enemies=["slardar", "antimage", "crystal_maiden", "lion", "tinker"],
            allies=["centaur", "necrolyte", "hoodwink", "shadow_shaman"],
            role="pos1",
        )
        for key in [
            "hero", "hero_name", "role", "role_label", "starting_items",
            "early_game", "mid_game", "late_game", "situational_swaps",
            "key_item_timings", "threats", "team_analysis", "reasoning"
        ]:
            assert key in rec
        assert rec["hero"] == "drow_ranger"
        assert rec["role"] == "pos1"
        assert len(rec["starting_items"]) == 6
        assert len(rec["early_game"]) == 2
        assert len(rec["mid_game"]) == 2
        assert len(rec["late_game"]) <= 2

    def test_recommend_accepts_valve_hero_id(self):
        rec = self.recommender.recommend(
            my_hero="nevermore",
            enemies=["zuus", "lion"],
            allies=["axe", "oracle"],
            role="mid",
        )
        assert rec["hero"] == "shadow_fiend"
        assert rec["role"] == "pos2"

    def test_mid_and_late_items_are_not_support_only(self):
        rec = self.recommender.recommend(
            my_hero="drow_ranger",
            enemies=["slardar", "antimage", "lion"],
            allies=["centaur", "oracle"],
        )
        disallowed = {"ward_observer", "ward_sentry", "dust", "smoke_of_deceit"}
        mid_ids = {i["item"] for i in rec["mid_game"]}
        late_ids = {i["item"] for i in rec["late_game"]}
        assert disallowed.isdisjoint(mid_ids)
        assert disallowed.isdisjoint(late_ids)

    def test_phase_items_have_item_and_note(self):
        rec = self.recommender.recommend(
            my_hero="juggernaut",
            enemies=["lion", "tinker"],
            allies=["axe", "oracle"],
        )
        for phase in ["early_game", "mid_game", "late_game"]:
            for item in rec[phase]:
                assert "item" in item
                assert "note" in item

    def test_recommend_skips_owned_items_in_future_phases(self):
        rec = self.recommender.recommend(
            my_hero="drow_ranger",
            enemies=["slardar", "antimage", "lion"],
            allies=["centaur", "oracle"],
            my_items=["power_treads", "dragon_lance", "black_king_bar"],
            role="pos1",
        )
        owned = {"power_treads", "dragon_lance", "black_king_bar"}
        mid_ids = {i["item"] for i in rec["mid_game"]}
        late_ids = {i["item"] for i in rec["late_game"]}
        assert owned.isdisjoint(mid_ids)
        assert owned.isdisjoint(late_ids)

    def test_recommend_discloses_auto_generated_hero_profile(self):
        rec = self.recommender.recommend(
            my_hero="necrophos",
            enemies=["slardar", "lion"],
            allies=["centaur", "oracle"],
            role="pos2",
        )
        assert any("auto-generated hero profile" in line for line in rec["reasoning"])

    def test_disable_heavy_necrophos_matchup_keeps_bkb_and_skips_mjollnir(self):
        rec = self.recommender.recommend(
            my_hero="necrophos",
            enemies=["lion", "shadow_shaman", "natures_prophet", "tidehunter", "terrorblade"],
            allies=["necrophos", "shadow_demon", "slark", "death_prophet", "mirana"],
            role="mid",
        )

        core_ids = [item["item"] for item in rec["early_game"] + rec["mid_game"] + rec["late_game"]]

        assert "black_king_bar" in core_ids
        assert "mjollnir" not in core_ids

    def test_support_lean_mirana_avoids_greedy_carry_items(self):
        rec = self.recommender.recommend(
            my_hero="mirana",
            enemies=["wraith_king", "chaos_knight", "undying", "sniper", "silencer"],
            allies=["bristleback", "pudge", "troll_warlord", "kunkka", "mirana"],
            role="pos4",
        )

        core_ids = [item["item"] for item in rec["early_game"] + rec["mid_game"] + rec["late_game"]]

        assert rec["hero_profile"]["role_override"] == "pos4"
        assert len(core_ids) <= 3
        assert "bfury" not in core_ids
        assert "maelstrom" not in core_ids
        assert "travel_boots" not in core_ids
        assert "black_king_bar" not in core_ids or "aeon_disk" not in core_ids
        assert rec["situational_swaps"]

    def test_late_phase_does_not_repeat_boots_when_mid_already_has_boots(self):
        scored = [
            ("travel_boots", 20, "boots"),
            ("lotus_orb", 18, "utility"),
            ("shivas_guard", 17, "armor"),
            ("ultimate_scepter", 16, "core"),
            ("aeon_disk", 15, "save"),
            ("heart", 14, "hp"),
        ]
        prev_phase = [{"item": "travel_boots", "note": "boots"}]

        late = self.recommender._select_phase_items(
            scored, hero_attr="int", prev_phase=prev_phase, owned_items=set()
        )

        late_ids = [item["item"] for item in late]
        assert "travel_boots" not in late_ids

    def test_pos5_caps_core_items_and_adds_detection_situational(self):
        rec = self.recommender.recommend(
            my_hero="shadow_shaman",
            enemies=["riki", "puck", "slardar", "lina", "phantom_lancer"],
            allies=["dragon_knight", "juggernaut", "dazzle", "shadow_shaman"],
            role="pos5",
        )

        core_ids = [item["item"] for item in rec["early_game"] + rec["mid_game"] + rec["late_game"]]
        assert len(core_ids) <= 3
        assert any("Dust/Sentries" in line or "Gem" in line for line in rec["situational_swaps"])

    def test_pos1_antimage_avoids_support_utility_leaks(self):
        rec = self.recommender.recommend(
            my_hero="antimage",
            enemies=["axe", "enchantress", "lion", "puck", "storm_spirit"],
            allies=["abaddon", "puck", "disruptor", "centaur"],
            role="pos1",
        )

        core_ids = [item["item"] for item in rec["early_game"] + rec["mid_game"] + rec["late_game"]]
        situational = "\n".join(rec["situational_swaps"])

        assert "hurricane_pike" not in core_ids
        assert "pipe" not in core_ids
        assert "force_staff" not in core_ids
        assert "Pipe of Insight" not in situational
        assert "Force Staff" not in situational
        assert any(
            keyword in situational
            for keyword in ["Black King Bar", "Linken", "Butterfly", "Satanic"]
        )
