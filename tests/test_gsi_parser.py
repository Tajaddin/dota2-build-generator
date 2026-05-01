"""Tests for GSI data parser."""

from logic.gsi_parser import GSIParser


class TestGSIParser:
    def setup_method(self):
        self.parser = GSIParser("data")

    def test_parse_hero_selection_phase(self):
        gsi_data = {
            "map": {"game_state": "DOTA_GAMERULES_STATE_HERO_SELECTION"},
            "player": {"team_name": "radiant"},
            "hero": {"name": "npc_dota_hero_drow_ranger", "id": 6},
        }
        result = self.parser.parse(gsi_data)
        assert result["phase"] == "hero_selection"
        assert result["my_hero"] == "drow_ranger"
        assert result["my_team"] == "radiant"

    def test_parse_in_game_phase_and_items(self):
        gsi_data = {
            "map": {
                "game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS",
                "clock_time": 600,
            },
            "player": {"team_name": "radiant"},
            "hero": {"name": "npc_dota_hero_drow_ranger", "id": 6},
            "items": {
                "slot0": {"name": "item_power_treads"},
                "slot1": {"name": "item_dragon_lance"},
            },
        }
        result = self.parser.parse(gsi_data)
        assert result["phase"] == "in_game"
        assert result["game_time"] == 600
        assert result["my_items"] == ["power_treads", "dragon_lance"]

    def test_parse_hero_name_strips_prefix_and_maps(self):
        gsi_data = {
            "map": {"game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"},
            "player": {"team_name": "dire"},
            "hero": {"name": "npc_dota_hero_nevermore", "id": 11},
        }
        result = self.parser.parse(gsi_data)
        assert result["my_hero"] == "shadow_fiend"
        assert result["my_hero_valve"] == "nevermore"

    def test_parse_draft_team_blocks(self):
        gsi_data = {
            "draft": {
                "team2": {"pick0_id": 6},
                "team3": {"pick0_id": 11},
            }
        }
        draft = self.parser.parse_draft(gsi_data)
        assert "drow_ranger" in draft["radiant_picks"]
        assert "nevermore" in draft["dire_picks"]

        allies, enemies = self.parser.get_all_heroes_in_match(gsi_data, "radiant")
        assert "drow_ranger" in allies
        assert "nevermore" in enemies

    def test_parse_all_players(self):
        gsi_data = {
            "allplayers": {
                "team2": {
                    "0": {
                        "hero_id": 6,
                        "item0": {"name": "item_power_treads"},
                        "item1": {"name": "item_dragon_lance"},
                        "net_worth": 10300,
                    }
                },
                "team3": {
                    "0": {
                        "hero_id": 26,
                        "item0": {"name": "item_blink"},
                        "item1": {"name": "item_aether_lens"},
                        "net_worth": 6200,
                    }
                },
            }
        }
        parsed = self.parser.parse_all_players(gsi_data, my_team="radiant")
        assert len(parsed["allies"]) == 1
        assert len(parsed["enemies"]) == 1
        assert parsed["allies"][0]["hero"] == "drow_ranger"
        assert "carry" in parsed["allies"][0].get("role_tags", [])
        assert parsed["enemies"][0]["items"] == ["blink", "aether_lens"]

    def test_parse_draft_from_allheroes_is_stable_when_slots_are_unsorted(self):
        gsi_data = {
            "allheroes": {
                "team2": {
                    "player3": {"id": 74},
                    "player0": {"id": 6},
                    "player1": {"id": 2},
                },
                "team3": {
                    "player4": {"id": 11},
                    "player0": {"id": 26},
                    "player2": {"id": 5},
                },
            }
        }
        draft = self.parser.parse_draft(gsi_data)
        assert draft["radiant_picks"] == ["drow_ranger", "axe", "invoker"]
        assert draft["dire_picks"] == ["lion", "crystal_maiden", "nevermore"]
