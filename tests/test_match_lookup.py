"""Tests for local match roster lookup."""

import struct
from pathlib import Path

from logic.match_lookup import MatchLookup
import logic.match_lookup as match_lookup_module


def _build_last_match_blob(match_id: int, players: list[dict]) -> bytes:
    blob = bytearray()
    blob.extend(b"VBKV")
    blob.extend(b"last_match_id\x00")
    blob.extend(struct.pack("<Q", match_id))
    blob.extend(b"\x00match_data\x00\x07match_id\x00")
    blob.extend(struct.pack("<Q", match_id))
    blob.extend(b"\x02players\x00")

    for idx, player in enumerate(players, start=1):
        blob.extend(str(idx).encode("ascii"))
        blob.extend(b"\x00\x02account_id\x00")
        blob.extend(struct.pack("<I", player["account_id"]))
        blob.extend(b"\x02hero_id\x00")
        blob.extend(struct.pack("<I", player["hero_id"]))
        blob.extend(b"\x0bplayer_slot\x00")
        blob.extend(struct.pack("<I", player["player_slot"]))
        blob.extend(b"\x02team_number\x00")
        blob.extend(struct.pack("<I", player["team_number"]))

    return bytes(blob)


class TestMatchLookup:
    def setup_method(self):
        self.lookup = MatchLookup("data")

    def test_parse_local_last_match_bytes_extracts_teams(self):
        blob = _build_last_match_blob(
            8721855367,
            [
                {"account_id": 100, "hero_id": 54, "player_slot": 0, "team_number": 0},
                {"account_id": 101, "hero_id": 6, "player_slot": 1, "team_number": 0},
                {"account_id": 200, "hero_id": 11, "player_slot": 128, "team_number": 1},
                {"account_id": 201, "hero_id": 22, "player_slot": 129, "team_number": 1},
            ],
        )

        parsed = self.lookup._parse_local_last_match_bytes(
            blob, expected_match_id=8721855367
        )

        assert parsed is not None
        assert parsed["radiant"] == ["life_stealer", "drow_ranger"]
        assert parsed["dire"] == ["nevermore", "zuus"]

    def test_parse_local_last_match_bytes_rejects_wrong_match_id(self):
        blob = _build_last_match_blob(
            8721855367,
            [
                {"account_id": 100, "hero_id": 54, "player_slot": 0, "team_number": 0},
                {"account_id": 200, "hero_id": 11, "player_slot": 128, "team_number": 1},
            ],
        )

        parsed = self.lookup._parse_local_last_match_bytes(
            blob, expected_match_id=9999999999
        )

        assert parsed is None

    def test_parse_overwolf_controller_lines_extracts_current_match(self):
        lines = [
            "2026-03-09 02:13:52,956 (INFO) - matchStore: Processing roster for detected match with game mode AllDraft and hero pool undefined.",
            '2026-03-09 02:13:52,958 (INFO) - matchStore: Roster: [{"steamId":"1100597905","hero":"life_stealer","team":2},{"steamId":"1258046960","hero":"huskar","team":2},{"steamId":"1719389796","hero":"crystal_maiden","team":2},{"steamId":"364527581","hero":"viper","team":2},{"steamId":"1131228225","hero":"shadow_shaman","team":2},{"steamId":"1919524818","hero":"axe","team":3},{"steamId":"317690163","hero":"antimage","team":3},{"steamId":"295957835","hero":"pudge","team":3},{"steamId":"1088895688","hero":"vengefulspirit","team":3},{"steamId":"1190432681","hero":"muerta","team":3}]',
            "2026-03-09 02:13:52,958 (INFO) - matchStore: Detecting match 8721855367 - AllDraft - playing - ranked",
        ]

        result = self.lookup._parse_overwolf_controller_lines(
            lines,
            "8721855367",
            {"1100597905"},
            "radiant",
            "life_stealer",
        )

        assert result["allies"] == [
            "lifestealer", "huskar", "crystal_maiden", "viper", "shadow_shaman"
        ]
        assert result["enemies"] == [
            "axe", "anti_mage", "pudge", "vengefulspirit", "muerta"
        ]
        assert result["complete"] is True

    def test_parse_overwolf_gep_lines_extracts_current_roster(self):
        lines = [
            '2026-03-09 02:13:52,900 (INFO) </libs/bundle.min.js> (:1) - [InfoDBContainer] UPDATING INFO (decoded): {"feature":"match_state_changed","category":"game","key":"match_state","value":"DOTA_GAMERULES_STATE_STRATEGY_TIME"}',
            '2026-03-09 02:13:52,901 (INFO) </libs/bundle.min.js> (:1) - [InfoDBContainer] UPDATING INFO (decoded): {"feature":"match_info","category":"match_info","key":"pseudo_match_id","value":"8721855367"}',
            '2026-03-09 02:13:53,014 (INFO) </libs/bundle.min.js> (:1) - [InfoDBContainer] UPDATING INFO (decoded): {"feature":"roster","category":"roster","key":"players","value":"[{\\"steamId\\":\\"76561199049161416\\",\\"hero\\":\\"vengefulspirit\\",\\"team\\":3},{\\"steamId\\":\\"76561199150698409\\",\\"hero\\":\\"muerta\\",\\"team\\":3},{\\"steamId\\":\\"76561198277955891\\",\\"hero\\":\\"antimage\\",\\"team\\":3},{\\"steamId\\":\\"76561199879790546\\",\\"hero\\":\\"axe\\",\\"team\\":3},{\\"steamId\\":\\"76561198256223563\\",\\"hero\\":\\"pudge\\",\\"team\\":3},{\\"steamId\\":\\"76561199091493953\\",\\"hero\\":\\"shadow_shaman\\",\\"team\\":2},{\\"steamId\\":\\"76561199679655524\\",\\"hero\\":\\"crystal_maiden\\",\\"team\\":2},{\\"steamId\\":\\"76561199060863633\\",\\"hero\\":\\"life_stealer\\",\\"team\\":2},{\\"steamId\\":\\"76561199218312688\\",\\"hero\\":\\"huskar\\",\\"team\\":2},{\\"steamId\\":\\"76561198324793309\\",\\"hero\\":\\"viper\\",\\"team\\":2}]"}',
        ]

        result = self.lookup._parse_overwolf_gep_lines(
            lines,
            "8721855367",
            {"1100597905", "76561199060863633"},
            "radiant",
            "life_stealer",
        )

        assert result["allies"] == [
            "shadow_shaman", "crystal_maiden", "lifestealer", "huskar", "viper"
        ]
        assert result["enemies"] == [
            "vengefulspirit", "muerta", "anti_mage", "axe", "pudge"
        ]
        assert result["complete"] is True

    def test_parse_overwolf_gep_lines_ignores_other_match_ids(self):
        lines = [
            '2026-03-09 02:12:06,100 (INFO) </libs/bundle.min.js> (:1) - [InfoDBContainer] UPDATING INFO (decoded): {"feature":"match_info","category":"match_info","key":"pseudo_match_id","value":"111"}',
            '2026-03-09 02:12:06,101 (INFO) </libs/bundle.min.js> (:1) - [InfoDBContainer] UPDATING INFO (decoded): {"feature":"roster","category":"roster","key":"players","value":"[{\\"steamId\\":\\"76561199060863633\\",\\"hero\\":\\"life_stealer\\",\\"team\\":2,\\"player_index\\":0,\\"pickConfirmed\\":true},{\\"steamId\\":\\"1\\",\\"hero\\":\\"axe\\",\\"team\\":3,\\"player_index\\":5,\\"pickConfirmed\\":true}]"}',
            '2026-03-09 02:13:06,100 (INFO) </libs/bundle.min.js> (:1) - [InfoDBContainer] UPDATING INFO (decoded): {"feature":"match_info","category":"match_info","key":"pseudo_match_id","value":"222"}',
            '2026-03-09 02:13:06,101 (INFO) </libs/bundle.min.js> (:1) - [InfoDBContainer] UPDATING INFO (decoded): {"feature":"roster","category":"roster","key":"players","value":"[{\\"steamId\\":\\"76561199060863633\\",\\"hero\\":\\"life_stealer\\",\\"team\\":2,\\"player_index\\":0,\\"pickConfirmed\\":true},{\\"steamId\\":\\"2\\",\\"hero\\":\\"muerta\\",\\"team\\":3,\\"player_index\\":5,\\"pickConfirmed\\":true}]"}',
        ]

        result = self.lookup._parse_overwolf_gep_lines(
            lines,
            "222",
            {"1100597905", "76561199060863633"},
            "radiant",
            "life_stealer",
        )

        assert result["allies"] == ["lifestealer"]
        assert result["enemies"] == ["muerta"]

    def test_lookup_overwolf_roster_refreshes_when_logs_change(self, tmp_path, monkeypatch):
        controller_log = tmp_path / "controller.html.log"
        gep_log = tmp_path / "index.html.log"
        controller_log.write_text("", encoding="utf-8")

        monkeypatch.setattr(match_lookup_module, "OVERWOLF_DOTAPLUS_LOG", controller_log)
        monkeypatch.setattr(match_lookup_module, "OVERWOLF_GEP_LOG", gep_log)

        first_snapshot = "\n".join([
            '2026-03-09 02:12:06,185 (INFO) </libs/bundle.min.js> (:1) - [InfoDBContainer] UPDATING INFO (decoded): {"feature":"match_info","category":"match_info","key":"pseudo_match_id","value":"8721855367"}',
            '2026-03-09 02:12:39,786 (INFO) </libs/bundle.min.js> (:1) - [InfoDBContainer] UPDATING INFO (decoded): {"feature":"roster","category":"roster","key":"players","value":"[{\\"steamId\\":\\"76561199060863633\\",\\"name\\":\\"me\\",\\"pickConfirmed\\":false,\\"hero\\":\\"life_stealer\\",\\"team\\":2,\\"player_index\\":0},{\\"steamId\\":\\"76561199218312688\\",\\"name\\":\\"ally\\",\\"pickConfirmed\\":false,\\"hero\\":\\"huskar\\",\\"team\\":2,\\"player_index\\":1},{\\"steamId\\":\\"76561199049161416\\",\\"name\\":\\"enemy\\",\\"pickConfirmed\\":true,\\"hero\\":\\"vengefulspirit\\",\\"team\\":3,\\"player_index\\":8},{\\"steamId\\":\\"76561199879790546\\",\\"name\\":\\"enemy2\\",\\"pickConfirmed\\":true,\\"hero\\":\\"axe\\",\\"team\\":3,\\"player_index\\":5}]"}',
        ])
        gep_log.write_text(first_snapshot, encoding="utf-8")

        first = self.lookup.lookup_overwolf_roster(
            "8721855367",
            "1100597905",
            "radiant",
            "life_stealer",
        )

        assert first == (["lifestealer", "huskar"], ["vengefulspirit", "axe"])

        second_snapshot = first_snapshot + "\n" + '2026-03-09 02:13:53,014 (INFO) </libs/bundle.min.js> (:1) - [InfoDBContainer] UPDATING INFO (decoded): {"feature":"roster","category":"roster","key":"players","value":"[{\\"steamId\\":\\"76561199049161416\\",\\"hero\\":\\"vengefulspirit\\",\\"team\\":3,\\"player_index\\":8,\\"pickConfirmed\\":true},{\\"steamId\\":\\"76561199150698409\\",\\"hero\\":\\"muerta\\",\\"team\\":3,\\"player_index\\":9,\\"pickConfirmed\\":true},{\\"steamId\\":\\"76561198277955891\\",\\"hero\\":\\"antimage\\",\\"team\\":3,\\"player_index\\":6,\\"pickConfirmed\\":true},{\\"steamId\\":\\"76561199879790546\\",\\"hero\\":\\"axe\\",\\"team\\":3,\\"player_index\\":5,\\"pickConfirmed\\":true},{\\"steamId\\":\\"76561198256223563\\",\\"hero\\":\\"pudge\\",\\"team\\":3,\\"player_index\\":7,\\"pickConfirmed\\":true},{\\"steamId\\":\\"76561199091493953\\",\\"hero\\":\\"shadow_shaman\\",\\"team\\":2,\\"player_index\\":4,\\"pickConfirmed\\":true},{\\"steamId\\":\\"76561199679655524\\",\\"hero\\":\\"crystal_maiden\\",\\"team\\":2,\\"player_index\\":2,\\"pickConfirmed\\":true},{\\"steamId\\":\\"76561199060863633\\",\\"hero\\":\\"life_stealer\\",\\"team\\":2,\\"player_index\\":0,\\"pickConfirmed\\":true},{\\"steamId\\":\\"76561199218312688\\",\\"hero\\":\\"huskar\\",\\"team\\":2,\\"player_index\\":1,\\"pickConfirmed\\":true},{\\"steamId\\":\\"76561198324793309\\",\\"hero\\":\\"viper\\",\\"team\\":2,\\"player_index\\":3,\\"pickConfirmed\\":true}]"}'
        gep_log.write_text(second_snapshot, encoding="utf-8")

        second = self.lookup.lookup_overwolf_roster(
            "8721855367",
            "1100597905",
            "radiant",
            "life_stealer",
        )

        assert second == (
            ["shadow_shaman", "crystal_maiden", "lifestealer", "huskar", "viper"],
            ["vengefulspirit", "muerta", "anti_mage", "axe", "pudge"],
        )
