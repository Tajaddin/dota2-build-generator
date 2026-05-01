"""Parse raw GSI JSON data into structured game state."""
import json
from pathlib import Path
from typing import Optional


GAME_STATES = {
    "DOTA_GAMERULES_STATE_HERO_SELECTION": "hero_selection",
    "DOTA_GAMERULES_STATE_STRATEGY_TIME": "strategy",
    "DOTA_GAMERULES_STATE_PRE_GAME": "pre_game",
    "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS": "in_game",
    "DOTA_GAMERULES_STATE_POST_GAME": "post_game",
    "DOTA_GAMERULES_STATE_WAIT_FOR_PLAYERS_TO_LOAD": "loading",
    "DOTA_GAMERULES_STATE_CUSTOM_GAME_SETUP": "custom_setup",
}


class GSIParser:
    """Parses raw GSI data into usable game state."""

    def __init__(self, data_dir: str):
        data_path = Path(data_dir)
        map_path = data_path / "hero_id_map.json"
        if map_path.exists():
            with open(map_path, "r", encoding="utf-8") as f:
                id_map = json.load(f)
            self._valve_to_internal = id_map.get("valve_to_internal", {})
            self._id_to_name = id_map.get("hero_id_to_name", {})
        else:
            self._valve_to_internal = {}
            self._id_to_name = {}

        # Load hero tags for role info in scoreboard
        tags_path = data_path / "hero_tags.json"
        if tags_path.exists():
            with open(tags_path, "r", encoding="utf-8") as f:
                self._hero_tags = json.load(f)
        else:
            self._hero_tags = {}

    def _strip_hero_prefix(self, hero_name: str) -> str:
        """Convert 'npc_dota_hero_drow_ranger' -> 'drow_ranger'."""
        prefix = "npc_dota_hero_"
        if hero_name.startswith(prefix):
            return hero_name[len(prefix):]
        return hero_name

    def _to_internal_id(self, valve_id: str) -> str:
        """Convert Valve hero ID to our internal ID."""
        return self._valve_to_internal.get(valve_id, valve_id)

    @staticmethod
    def _slot_sort_key(slot_key: str) -> tuple[int, str]:
        """Sort GSI player slots numerically for stable hero ordering."""
        digits = "".join(ch for ch in str(slot_key) if ch.isdigit())
        if digits:
            return int(digits), str(slot_key)
        return 999, str(slot_key)

    def parse(self, gsi_data: dict) -> dict:
        """Parse a GSI JSON payload into structured state."""
        result = {
            "phase": "unknown",
            "my_hero": None,
            "my_hero_valve": None,
            "my_team": None,
            "game_time": 0,
            "my_items": [],
            "raw": gsi_data,
        }

        # Game state
        map_data = gsi_data.get("map", {})
        game_state = map_data.get("game_state", "")
        result["phase"] = GAME_STATES.get(game_state, "unknown")
        result["game_time"] = map_data.get("clock_time", 0)

        # Player info — try player.team_name first, fall back to map.player_team
        player = gsi_data.get("player", {})
        team_name = player.get("team_name")
        if not team_name:
            # Some GSI states put team info in the map block instead
            team_name = map_data.get("player_team")
        result["my_team"] = team_name

        # Hero info
        hero = gsi_data.get("hero", {})
        hero_name_raw = hero.get("name", "")
        valve_id = self._strip_hero_prefix(hero_name_raw)
        result["my_hero_valve"] = valve_id
        result["my_hero"] = self._to_internal_id(valve_id)

        # Items (current inventory)
        items = gsi_data.get("items", {})
        my_items = []
        for slot in ["slot0", "slot1", "slot2", "slot3", "slot4", "slot5",
                      "stash0", "stash1", "stash2", "stash3", "stash4", "stash5"]:
            item = items.get(slot, {})
            if item.get("name") and item["name"] != "empty":
                item_name = item["name"]
                if item_name.startswith("item_"):
                    item_name = item_name[5:]
                my_items.append(item_name)
        result["my_items"] = my_items

        return result

    def parse_draft(self, gsi_data: dict) -> dict:
        """Extract draft/pick information from GSI data.

        GSI draft structure varies by game mode. This handles the common format
        where team2=radiant and team3=dire.

        Data sources tried in order:
        1. draft.team2/team3 — available during hero selection
        2. allheroes.team2/team3 — hero identity during gameplay (most reliable)
        3. allplayers.team2/team3 — fallback hero_id during gameplay
        4. allplayers as flat dict — some GSI versions
        5. player.team2/team3 — spectator mode fallback
        """
        result = {
            "radiant_picks": [],
            "dire_picks": [],
            "radiant_bans": [],
            "dire_bans": [],
        }

        # ══ Source 1: Draft data (hero selection phase) ══
        draft = gsi_data.get("draft", {})
        for team in ["team2", "team3"]:
            team_data = draft.get(team, {})
            team_key = "radiant" if team == "team2" else "dire"

            for i in range(7):  # up to 7 picks/bans per team
                pick = team_data.get(f"pick{i}_id")
                if pick and int(pick) > 0 and str(pick) in self._id_to_name:
                    hero_name = self._id_to_name[str(pick)]
                    if hero_name not in result[f"{team_key}_picks"]:
                        result[f"{team_key}_picks"].append(hero_name)

                ban = team_data.get(f"ban{i}_id")
                if ban and int(ban) > 0 and str(ban) in self._id_to_name:
                    hero_name = self._id_to_name[str(ban)]
                    if hero_name not in result[f"{team_key}_bans"]:
                        result[f"{team_key}_bans"].append(hero_name)

        # ══ Source 2: allheroes data (during gameplay — hero identity) ══
        if not any(result[k] for k in ["radiant_picks", "dire_picks"]):
            allheroes = gsi_data.get("allheroes", {})
            if isinstance(allheroes, dict):
                for key in ["team2", "team3"]:
                    team_heroes = allheroes.get(key, {})
                    if isinstance(team_heroes, dict):
                        team_key = "radiant" if key == "team2" else "dire"
                        for player_key in sorted(team_heroes.keys(), key=self._slot_sort_key):
                            hero_data = team_heroes[player_key]
                            if isinstance(hero_data, dict):
                                # allheroes has "id" (numeric) and "name" (npc_dota_hero_X)
                                hero_id = hero_data.get("id")
                                if hero_id and int(hero_id) > 0 and str(hero_id) in self._id_to_name:
                                    hero_name = self._id_to_name[str(hero_id)]
                                    if hero_name not in result[f"{team_key}_picks"]:
                                        result[f"{team_key}_picks"].append(hero_name)
                                    continue
                                # Fallback: parse from hero name string
                                hero_name_raw = hero_data.get("name", "")
                                if hero_name_raw:
                                    valve_id = self._strip_hero_prefix(hero_name_raw)
                                    if valve_id and valve_id not in result[f"{team_key}_picks"]:
                                        result[f"{team_key}_picks"].append(valve_id)

        # ══ Source 3: allplayers data (during gameplay — fallback for hero_id) ══
        if not any(result[k] for k in ["radiant_picks", "dire_picks"]):
            allplayers = gsi_data.get("allplayers", {})
            if isinstance(allplayers, dict):
                for key in ["team2", "team3"]:
                    team_players = allplayers.get(key, {})
                    if isinstance(team_players, dict):
                        team_key = "radiant" if key == "team2" else "dire"
                        for player_key in sorted(team_players.keys(), key=self._slot_sort_key):
                            player_data = team_players[player_key]
                            if isinstance(player_data, dict):
                                # Try hero_id (numeric) first
                                hero_id = player_data.get("hero_id")
                                if hero_id and int(hero_id) > 0 and str(hero_id) in self._id_to_name:
                                    hero_name = self._id_to_name[str(hero_id)]
                                    if hero_name not in result[f"{team_key}_picks"]:
                                        result[f"{team_key}_picks"].append(hero_name)
                                    continue
                                # Fallback: hero name string from heroid field
                                hero_name_raw = player_data.get("heroid")
                                if hero_name_raw:
                                    valve_id = self._strip_hero_prefix(str(hero_name_raw))
                                    if valve_id and valve_id not in result[f"{team_key}_picks"]:
                                        result[f"{team_key}_picks"].append(valve_id)

        # ══ Source 4: allplayers as flat dict (some GSI versions) ══
        if not any(result[k] for k in ["radiant_picks", "dire_picks"]):
            allplayers = gsi_data.get("allplayers", {})
            if isinstance(allplayers, dict):
                for player_key in sorted(allplayers.keys(), key=self._slot_sort_key):
                    player_data = allplayers[player_key]
                    if not isinstance(player_data, dict):
                        continue
                    team_slot = player_data.get("team_name", "")
                    hero_id = player_data.get("hero_id")
                    if not team_slot or not hero_id:
                        continue
                    team_key = team_slot  # "radiant" or "dire"
                    if team_key not in ("radiant", "dire"):
                        continue
                    if int(hero_id) > 0 and str(hero_id) in self._id_to_name:
                        hero_name = self._id_to_name[str(hero_id)]
                        if hero_name not in result[f"{team_key}_picks"]:
                            result[f"{team_key}_picks"].append(hero_name)

        # ══ Source 5: player.team2/team3 (spectator mode) ══
        if not any(result[k] for k in ["radiant_picks", "dire_picks"]):
            player = gsi_data.get("player", {})
            for key in ["team2", "team3"]:
                team_players = player.get(key, {})
                if isinstance(team_players, dict):
                    team_key = "radiant" if key == "team2" else "dire"
                    for player_key in sorted(team_players.keys(), key=self._slot_sort_key):
                        player_data = team_players[player_key]
                        if isinstance(player_data, dict):
                            hero_id = player_data.get("hero_id")
                            if hero_id and int(hero_id) > 0 and str(hero_id) in self._id_to_name:
                                hero_name = self._id_to_name[str(hero_id)]
                                if hero_name not in result[f"{team_key}_picks"]:
                                    result[f"{team_key}_picks"].append(hero_name)

        return result

    def get_all_heroes_in_match(self, gsi_data: dict, my_team: str) -> tuple[list, list]:
        """Extract enemy and ally hero lists from GSI data.

        Returns:
            (allies, enemies) - lists of Valve hero IDs
        """
        draft = self.parse_draft(gsi_data)

        if my_team == "radiant":
            allies = draft["radiant_picks"]
            enemies = draft["dire_picks"]
        elif my_team == "dire":
            allies = draft["dire_picks"]
            enemies = draft["radiant_picks"]
        else:
            # Unknown team — try to figure it out from our hero
            # by checking which team list contains our hero
            hero = gsi_data.get("hero", {})
            hero_name_raw = hero.get("name", "")
            my_valve = self._strip_hero_prefix(hero_name_raw)
            if my_valve in draft["radiant_picks"]:
                allies = draft["radiant_picks"]
                enemies = draft["dire_picks"]
            elif my_valve in draft["dire_picks"]:
                allies = draft["dire_picks"]
                enemies = draft["radiant_picks"]
            else:
                allies = []
                enemies = []

        return allies, enemies

    def parse_all_players(self, gsi_data: dict, my_team: str) -> dict:
        """Parse allplayers + allheroes data from GSI into structured player info.

        Returns:
            {"allies": [...], "enemies": [...]} where each entry is:
            {"hero": str, "hero_name": str, "items": [str], "net_worth": int, "role_tags": [str]}
        """
        result = {"allies": [], "enemies": []}

        all_players = gsi_data.get("allplayers")
        if not all_players or not isinstance(all_players, dict):
            return result

        # Build hero lookup from allheroes (hero identity per player slot)
        allheroes = gsi_data.get("allheroes", {})
        hero_by_slot = {}  # {("team2", "player0"): "nevermore", ...}
        if isinstance(allheroes, dict):
            for team_key in ["team2", "team3"]:
                team_heroes = allheroes.get(team_key, {})
                if isinstance(team_heroes, dict):
                    for slot_key in sorted(team_heroes.keys(), key=self._slot_sort_key):
                        hero_data = team_heroes[slot_key]
                        if isinstance(hero_data, dict):
                            hero_id = hero_data.get("id")
                            if hero_id and int(hero_id) > 0 and str(hero_id) in self._id_to_name:
                                hero_by_slot[(team_key, slot_key)] = self._id_to_name[str(hero_id)]
                            else:
                                hero_name_raw = hero_data.get("name", "")
                                if hero_name_raw:
                                    hero_by_slot[(team_key, slot_key)] = self._strip_hero_prefix(hero_name_raw)

        my_team_key = "team2" if my_team == "radiant" else "team3"
        enemy_team_key = "team3" if my_team == "radiant" else "team2"

        for team_key, group in [(my_team_key, "allies"), (enemy_team_key, "enemies")]:
            team_data = all_players.get(team_key, {})
            if not isinstance(team_data, dict):
                continue
            for player_id in sorted(team_data.keys(), key=self._slot_sort_key):
                player_data = team_data[player_id]
                if not isinstance(player_data, dict):
                    continue

                # Extract hero — prefer allheroes lookup, then allplayers hero_id
                hero_name_internal = hero_by_slot.get((team_key, player_id), "")
                if not hero_name_internal:
                    hero_id = player_data.get("hero_id")
                    if hero_id and int(hero_id) > 0:
                        hero_name_internal = self._id_to_name.get(str(hero_id), "")
                if not hero_name_internal:
                    continue

                # Extract items from inventory slots
                items = []
                for slot_prefix in ["item", "stash"]:
                    for i in range(6):
                        slot_key = f"{slot_prefix}{i}"
                        item_data = player_data.get(slot_key, {})
                        if isinstance(item_data, dict):
                            item_name = item_data.get("name", "empty")
                        else:
                            item_name = "empty"
                        if item_name and item_name != "empty":
                            if item_name.startswith("item_"):
                                item_name = item_name[5:]
                            items.append(item_name)

                # Extract net worth
                net_worth = player_data.get("net_worth", 0)
                if not net_worth:
                    net_worth = player_data.get("gold", 0) + player_data.get("gold_from_hero_kills", 0)

                # Get role tags and display name from hero_tags.json
                hero_tags = self._hero_tags.get(hero_name_internal, {})
                role_tags = hero_tags.get("role_tags", [])
                display_name = hero_tags.get("name", hero_name_internal.replace("_", " ").title())

                result[group].append({
                    "hero": hero_name_internal,
                    "hero_name": display_name,
                    "items": items,
                    "net_worth": net_worth,
                    "role_tags": role_tags,
                })

        # Sort by net worth descending
        for group in ["allies", "enemies"]:
            result[group].sort(key=lambda p: p["net_worth"], reverse=True)

        return result
