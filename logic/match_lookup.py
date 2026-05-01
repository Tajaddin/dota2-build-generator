"""Look up the current match roster via local clients or remote APIs.

Strategy for detecting enemy heroes:
1. Local Overwolf / DotaPlus logs — parses live `roster` events
2. Local Steam userdata cache — parses `last_match.dat`
3. Stratz GraphQL API — queries live match data using match_id (requires token)
4. OpenDota API — queries recently finished matches
5. Fallback — hero-only mode (no enemy data, just popular builds)
"""
import json
import os
import re
import time
import threading
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from logic.gsi_installer import find_dota2_path

OPENDOTA_BASE = "https://api.opendota.com/api"
STRATZ_GRAPHQL = "https://api.stratz.com/graphql"
STEAM_APP_ID = "570"
STEAM64_BASE = 76561197960265728
COMMON_STEAM_ROOTS = [
    Path(r"C:\Program Files (x86)\Steam"),
    Path(r"C:\Program Files\Steam"),
    Path(r"D:\Steam"),
    Path(r"D:\SteamLibrary"),
    Path(r"E:\Steam"),
    Path(r"E:\SteamLibrary"),
    Path(r"F:\Steam"),
    Path(r"F:\SteamLibrary"),
    Path(r"G:\Steam"),
    Path(r"G:\SteamLibrary"),
]
OVERWOLF_ROOT = Path(os.environ.get("LOCALAPPDATA", "")) / "Overwolf" / "Log" / "Apps"
OVERWOLF_DOTAPLUS_LOG = OVERWOLF_ROOT / "DotaPlus" / "controller.html.log"
OVERWOLF_GEP_LOG = OVERWOLF_ROOT / "Overwolf General GameEvents Provider" / "index.html.log"
OVERWOLF_TAIL_BYTES = 2 * 1024 * 1024
MATCH_ID_PATTERNS = (
    re.compile(r"matchStore: Detecting match (\d+)"),
    re.compile(r"matchStore: Detected match id (\d+)"),
)


class MatchLookup:
    """Fetches current match roster from Stratz (live) or OpenDota (finished)."""

    def __init__(self, data_dir: str):
        data_path = Path(data_dir)
        map_path = data_path / "hero_id_map.json"
        if map_path.exists():
            with open(map_path, "r", encoding="utf-8") as f:
                id_map = json.load(f)
            self._id_to_name = id_map.get("hero_id_to_name", {})
            self._valve_to_internal = id_map.get("valve_to_internal", {})
        else:
            self._id_to_name = {}
            self._valve_to_internal = {}

        # Load config for Stratz token
        self._stratz_token = ""
        config_path = data_path / "config.json"
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                self._stratz_token = config.get("stratz_token", "")
                if self._stratz_token:
                    print("[MatchLookup] Stratz API token loaded - live enemy detection enabled")
                else:
                    print("[MatchLookup] No Stratz token configured - hero-only mode for live games")
                    print("[MatchLookup] Get a free token at https://stratz.com/api")
            except Exception:
                pass

        self._cache: Optional[dict] = None
        self._cache_time: float = 0
        self._cache_ttl = 120  # Cache for 2 minutes
        self._lock = threading.Lock()
        self._last_match_id: Optional[str] = None
        self._overwolf_cache: Optional[dict] = None

    def has_stratz_token(self) -> bool:
        """Check if a Stratz API token is configured."""
        return bool(self._stratz_token)

    def reload_config(self, data_dir: str):
        """Reload config file (call after user enters token)."""
        config_path = Path(data_dir) / "config.json"
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                self._stratz_token = config.get("stratz_token", "")
            except Exception:
                pass

    def lookup_local_last_match(
        self,
        match_id: str,
        account_id: str,
        my_team: str,
    ) -> Optional[tuple[list, list]]:
        """Recover the current roster from Steam userdata's `last_match.dat`.

        Dota writes this local binary blob on match connect even when GSI omits
        `allheroes`/`allplayers`. It contains the current match ID and the 10
        hero IDs, which is enough for draft-aware recommendations.
        """
        if not match_id or not account_id:
            return None

        with self._lock:
            if (
                self._cache is not None
                and time.time() - self._cache_time < self._cache_ttl
                and self._last_match_id == str(match_id)
            ):
                cached = self._cache.get("local_teams")
                if cached:
                    return cached

        last_match_path = self._find_last_match_file(account_id)
        if not last_match_path or not last_match_path.exists():
            return None

        try:
            parsed = self._parse_local_last_match_bytes(
                last_match_path.read_bytes(),
                expected_match_id=int(match_id),
            )
        except Exception as e:
            print(f"[MatchLookup] Local match parse error: {e}")
            return None

        if not parsed:
            return None

        radiant = parsed.get("radiant", [])
        dire = parsed.get("dire", [])
        if not radiant and not dire:
            return None

        if my_team == "radiant":
            result = (radiant, dire)
        elif my_team == "dire":
            result = (dire, radiant)
        else:
            return None

        with self._lock:
            self._cache = {
                "local_teams": result,
                "local_match_path": str(last_match_path),
            }
            self._cache_time = time.time()
            self._last_match_id = str(match_id)

        allies, enemies = result
        print(
            f"[MatchLookup] Found local roster via last_match.dat: "
            f"Allies={allies} Enemies={enemies}"
        )
        return result

    def lookup_overwolf_roster(
        self,
        match_id: str,
        account_id: str,
        my_team: str,
        my_hero: Optional[str] = None,
    ) -> Optional[tuple[list, list]]:
        """Recover live roster from Overwolf/DotaPlus local logs."""
        if not match_id or not account_id or not my_team:
            return None

        match_id = str(match_id)
        account_id = str(account_id)
        my_hero_internal = self._to_internal_id(my_hero) if my_hero else ""

        controller_sig = self._get_file_signature(OVERWOLF_DOTAPLUS_LOG)
        gep_sig = self._get_file_signature(OVERWOLF_GEP_LOG)

        with self._lock:
            cached = self._overwolf_cache
            if (
                cached is not None
                and cached.get("match_id") == match_id
                and cached.get("account_id") == account_id
                and cached.get("my_team") == my_team
                and cached.get("my_hero") == my_hero_internal
                and cached.get("controller_sig") == controller_sig
                and cached.get("gep_sig") == gep_sig
            ):
                return cached.get("result")

        expected_ids = {account_id}
        try:
            expected_ids.add(str(int(account_id) + STEAM64_BASE))
        except ValueError:
            pass

        controller_candidate = self._parse_overwolf_controller_lines(
            self._read_log_lines(OVERWOLF_DOTAPLUS_LOG, full_scan=False),
            match_id,
            expected_ids,
            my_team,
            my_hero,
        )
        gep_candidate = self._parse_overwolf_gep_lines(
            self._read_log_lines(OVERWOLF_GEP_LOG, full_scan=False),
            match_id,
            expected_ids,
            my_team,
            my_hero,
            allow_recent_fallback=True,
        )
        best = self._pick_best_overwolf_candidate(controller_candidate, gep_candidate)

        if best is None:
            controller_candidate = self._parse_overwolf_controller_lines(
                self._read_log_lines(OVERWOLF_DOTAPLUS_LOG, full_scan=True),
                match_id,
                expected_ids,
                my_team,
                my_hero,
            )
            gep_candidate = self._parse_overwolf_gep_lines(
                self._read_log_lines(OVERWOLF_GEP_LOG, full_scan=True),
                match_id,
                expected_ids,
                my_team,
                my_hero,
                allow_recent_fallback=False,
            )
            best = self._pick_best_overwolf_candidate(controller_candidate, gep_candidate)

        with self._lock:
            self._overwolf_cache = {
                "match_id": match_id,
                "account_id": account_id,
                "my_team": my_team,
                "my_hero": my_hero_internal,
                "controller_sig": controller_sig,
                "gep_sig": gep_sig,
                "result": (best["allies"], best["enemies"]) if best else None,
            }

        if not best:
            return None

        allies = best["allies"]
        enemies = best["enemies"]
        print(
            f"[MatchLookup] Found Overwolf roster via {best['source']}: "
            f"filled={best['filled_slots']}/10 confirmed={best['confirmed_slots']} "
            f"Allies={allies} Enemies={enemies}"
        )
        return allies, enemies

    def _candidate_steam_roots(self) -> list[Path]:
        """Return possible Steam install roots for local userdata lookup."""
        roots: list[Path] = []

        dota_path = find_dota2_path()
        if dota_path is not None and len(dota_path.parents) >= 3:
            roots.append(dota_path.parents[2])

        program_files_x86 = os.environ.get("ProgramFiles(x86)")
        if program_files_x86:
            roots.append(Path(program_files_x86) / "Steam")
        program_files = os.environ.get("ProgramFiles")
        if program_files:
            roots.append(Path(program_files) / "Steam")

        roots.extend(COMMON_STEAM_ROOTS)

        deduped: list[Path] = []
        seen = set()
        for root in roots:
            key = str(root).lower()
            if key in seen:
                continue
            seen.add(key)
            if root.exists():
                deduped.append(root)
        return deduped

    def _canonical_team_name(self, team_name) -> str:
        if team_name is None:
            return ""
        team = str(team_name).lower()
        if team in {"radiant", "team2", "2"}:
            return "radiant"
        if team in {"dire", "team3", "3"}:
            return "dire"
        return ""

    def _to_internal_id(self, hero_name: str) -> str:
        hero_name = str(hero_name or "")
        if hero_name.startswith("npc_dota_hero_"):
            hero_name = hero_name[len("npc_dota_hero_"):]
        return self._valve_to_internal.get(hero_name, hero_name)

    def _parse_log_timestamp(self, line: str) -> Optional[datetime]:
        prefix = line[:23]
        try:
            return datetime.strptime(prefix, "%Y-%m-%d %H:%M:%S,%f")
        except ValueError:
            return None

    def _read_log_lines(self, path: Path, full_scan: bool) -> list[str]:
        if not path.exists():
            return []
        if full_scan:
            try:
                return path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                return []
        return self._read_log_tail_lines(path)

    def _read_log_tail_lines(self, path: Path, max_bytes: int = OVERWOLF_TAIL_BYTES) -> list[str]:
        if not path.exists():
            return []
        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                start = max(0, size - max_bytes)
                f.seek(start)
                data = f.read()
        except OSError:
            return []
        return data.decode("utf-8", errors="ignore").splitlines()

    def _get_file_signature(self, path: Path) -> Optional[tuple[int, int]]:
        if not path.exists():
            return None
        try:
            stat = path.stat()
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def _extract_controller_match_id(self, line: str) -> Optional[str]:
        for pattern in MATCH_ID_PATTERNS:
            match = pattern.search(line)
            if match:
                return match.group(1)
        return None

    def _pick_best_overwolf_candidate(self, *candidates: Optional[dict]) -> Optional[dict]:
        valid = [candidate for candidate in candidates if candidate]
        if not valid:
            return None
        valid.sort(
            key=lambda candidate: (
                1 if candidate.get("complete") else 0,
                candidate.get("filled_slots", 0),
                candidate.get("confirmed_slots", 0),
                candidate.get("timestamp_epoch", 0.0),
                1 if candidate.get("source") == "gep" else 0,
            ),
            reverse=True,
        )
        return valid[0]

    def _parse_overwolf_controller_lines(
        self,
        lines: list[str],
        expected_match_id: str,
        expected_ids: set[str],
        my_team: str,
        my_hero: Optional[str] = None,
    ) -> Optional[dict]:
        for idx in range(len(lines) - 1, -1, -1):
            line = lines[idx]
            marker = "matchStore: Roster: "
            marker_idx = line.find(marker)
            if marker_idx == -1:
                continue

            roster_json = line[marker_idx + len(marker):].strip()
            try:
                players = json.loads(roster_json)
            except json.JSONDecodeError:
                continue

            nearby_match_id = None
            for nearby_idx in range(max(0, idx - 6), min(len(lines), idx + 8)):
                nearby_match_id = self._extract_controller_match_id(lines[nearby_idx])
                if nearby_match_id:
                    break
            if nearby_match_id != str(expected_match_id):
                continue

            result = self._extract_teams_from_overwolf_players(
                players,
                expected_ids,
                my_team,
                my_hero,
            )
            if result:
                timestamp = self._parse_log_timestamp(line)
                result["source"] = "controller"
                result["timestamp_epoch"] = timestamp.timestamp() if timestamp else 0.0
                return result
        return None

    def _parse_overwolf_gep_lines(
        self,
        lines: list[str],
        expected_match_id: str,
        expected_ids: set[str],
        my_team: str,
        my_hero: Optional[str] = None,
        allow_recent_fallback: bool = False,
    ) -> Optional[dict]:
        marker = '[InfoDBContainer] UPDATING INFO (decoded): '
        current_match_id = None
        pending_players: list[tuple[Optional[datetime], list]] = []
        best = None
        recent_unmatched = None
        newest_timestamp = None

        for line in lines:
            marker_idx = line.find(marker)
            if marker_idx == -1:
                continue

            timestamp = self._parse_log_timestamp(line)
            if timestamp:
                newest_timestamp = timestamp

            payload_json = line[marker_idx + len(marker):].strip()
            try:
                payload = json.loads(payload_json)
            except json.JSONDecodeError:
                continue

            feature = payload.get("feature")
            key = payload.get("key")

            if feature == "match_info" and key == "pseudo_match_id":
                value = payload.get("value")
                current_match_id = str(value) if value not in (None, "", "null") else None
                if current_match_id == str(expected_match_id):
                    for pending_timestamp, players in pending_players:
                        candidate = self._extract_teams_from_overwolf_players(
                            players,
                            expected_ids,
                            my_team,
                            my_hero,
                        )
                        if not candidate:
                            continue
                        candidate["source"] = "gep"
                        candidate["timestamp_epoch"] = (
                            pending_timestamp.timestamp() if pending_timestamp else 0.0
                        )
                        best = self._pick_best_overwolf_candidate(best, candidate)
                pending_players = []
                continue

            if feature != "roster" or key != "players":
                continue

            try:
                players = json.loads(payload.get("value", "[]"))
            except json.JSONDecodeError:
                continue
            if not isinstance(players, list) or not players:
                continue

            candidate = self._extract_teams_from_overwolf_players(
                players,
                expected_ids,
                my_team,
                my_hero,
            )
            if not candidate:
                continue

            candidate["source"] = "gep"
            candidate["timestamp_epoch"] = timestamp.timestamp() if timestamp else 0.0

            if current_match_id == str(expected_match_id):
                best = self._pick_best_overwolf_candidate(best, candidate)
            else:
                pending_players.append((timestamp, players))
                pending_players = pending_players[-4:]
                recent_unmatched = self._pick_best_overwolf_candidate(recent_unmatched, candidate)

        if best:
            return best

        if (
            allow_recent_fallback
            and recent_unmatched
            and newest_timestamp
            and recent_unmatched["timestamp_epoch"]
            and newest_timestamp.timestamp() - recent_unmatched["timestamp_epoch"] <= 120
        ):
            return recent_unmatched

        return None

    def _extract_teams_from_overwolf_players(
        self,
        players: list,
        expected_ids: set[str],
        my_team: str,
        my_hero: Optional[str] = None,
    ) -> Optional[dict]:
        canonical_team = self._canonical_team_name(my_team)
        if canonical_team not in {"radiant", "dire"}:
            return None

        my_hero_internal = self._to_internal_id(my_hero) if my_hero else ""
        matched_me = None
        radiant = []
        dire = []
        radiant_slots = set()
        dire_slots = set()
        confirmed_slots = set()

        for player in players:
            if not isinstance(player, dict):
                continue

            hero_name = self._to_internal_id(player.get("hero", ""))
            team_name = self._canonical_team_name(player.get("team"))
            if not team_name:
                continue

            steam_id = str(player.get("steamId", "")).strip()
            if steam_id in expected_ids:
                matched_me = {
                    "team": team_name,
                    "hero": hero_name,
                }

            if not hero_name:
                continue

             # Track slot completeness separately from unique hero names.
            slot_marker = player.get("player_index", player.get("team_slot"))
            if slot_marker is None:
                slot_marker = f"{team_name}:{hero_name}:{len(radiant) + len(dire)}"
            if team_name == "radiant":
                radiant_slots.add(slot_marker)
            else:
                dire_slots.add(slot_marker)
            if player.get("pickConfirmed"):
                confirmed_slots.add((team_name, slot_marker))

            team_bucket = radiant if team_name == "radiant" else dire
            if hero_name not in team_bucket:
                team_bucket.append(hero_name)

        if not matched_me:
            return None
        if matched_me["team"] != canonical_team:
            return None
        if my_hero_internal and matched_me["hero"] and matched_me["hero"] != my_hero_internal:
            return None

        allies = radiant if canonical_team == "radiant" else dire
        enemies = dire if canonical_team == "radiant" else radiant
        if canonical_team == "radiant":
            ally_slots = radiant_slots
            enemy_slots = dire_slots
        else:
            ally_slots = dire_slots
            enemy_slots = radiant_slots

        return {
            "allies": allies,
            "enemies": enemies,
            "filled_slots": len(radiant_slots) + len(dire_slots),
            "confirmed_slots": len(confirmed_slots),
            "complete": len(ally_slots) >= 5 and len(enemy_slots) >= 5,
        }

    def _find_last_match_file(self, account_id: str) -> Optional[Path]:
        """Find Steam's local current-match cache for this account."""
        for steam_root in self._candidate_steam_roots():
            candidate = (
                steam_root
                / "userdata"
                / str(account_id)
                / STEAM_APP_ID
                / "remote"
                / "cfg"
                / "last_match.dat"
            )
            if candidate.exists():
                return candidate
        return None

    def _extract_u32_values(self, blob: bytes, key: bytes) -> list[int]:
        needle = key + b"\x00"
        values = []
        start = 0
        while True:
            idx = blob.find(needle, start)
            if idx == -1:
                break
            value_pos = idx + len(needle)
            if value_pos + 4 <= len(blob):
                values.append(int.from_bytes(blob[value_pos:value_pos + 4], "little"))
            start = value_pos
        return values

    def _extract_u64_values(self, blob: bytes, key: bytes) -> list[int]:
        needle = key + b"\x00"
        values = []
        start = 0
        while True:
            idx = blob.find(needle, start)
            if idx == -1:
                break
            value_pos = idx + len(needle)
            if value_pos + 8 <= len(blob):
                values.append(int.from_bytes(blob[value_pos:value_pos + 8], "little"))
            start = value_pos
        return values

    def _parse_local_last_match_bytes(
        self,
        blob: bytes,
        expected_match_id: Optional[int] = None,
    ) -> Optional[dict]:
        """Parse the small subset of Valve's binary blob that we need."""
        match_ids = self._extract_u64_values(blob, b"match_id")
        # The player block belongs to the nested `match_data.match_id`, which is
        # the last `match_id` key in the blob. `last_match_id` may refer to a
        # newer live match and would otherwise cause a false positive roster.
        if not match_ids:
            return None
        roster_match_id = match_ids[-1]
        if expected_match_id is not None and roster_match_id != expected_match_id:
            return None

        account_ids = self._extract_u32_values(blob, b"account_id")
        hero_ids = self._extract_u32_values(blob, b"hero_id")
        player_slots = self._extract_u32_values(blob, b"player_slot")
        team_numbers = self._extract_u32_values(blob, b"team_number")

        count = min(len(account_ids), len(hero_ids), len(player_slots), len(team_numbers))
        if count < 2:
            return None

        radiant = []
        dire = []
        players = []
        for i in range(count):
            hero_id = hero_ids[i]
            hero_name = self._id_to_name.get(str(hero_id))
            if not hero_name:
                continue

            team_number = team_numbers[i]
            if team_number not in (0, 1):
                team_number = 0 if player_slots[i] < 128 else 1

            player = {
                "account_id": account_ids[i],
                "hero_id": hero_id,
                "hero": hero_name,
                "player_slot": player_slots[i],
                "team_number": team_number,
            }
            players.append(player)

            if team_number == 0:
                if hero_name not in radiant:
                    radiant.append(hero_name)
            else:
                if hero_name not in dire:
                    dire.append(hero_name)

        if not radiant and not dire:
            return None

        return {
            "match_ids": match_ids,
            "roster_match_id": roster_match_id,
            "players": players,
            "radiant": radiant,
            "dire": dire,
        }

    # ═══════════════════════════════════════════════════════════════════
    # Primary: Stratz live match lookup (needs match_id from GSI)
    # ═══════════════════════════════════════════════════════════════════

    def lookup_live_stratz(self, match_id: str, my_team: str) -> Optional[tuple[list, list]]:
        """Query Stratz GraphQL API for a live match's hero roster.

        Args:
            match_id: Dota 2 match ID (from GSI map.matchid)
            my_team: "radiant" or "dire"

        Returns:
            (allies, enemies) tuple of internal hero ID strings, or None.
        """
        if not self._stratz_token:
            return None

        # Check cache
        with self._lock:
            if (self._cache is not None
                    and time.time() - self._cache_time < self._cache_ttl
                    and self._last_match_id == match_id):
                cached = self._cache.get("stratz_teams")
                if cached:
                    return cached

        query = """{
  live {
    match(id: %s) {
      matchId
      gameTime
      players {
        heroId
        isRadiant
      }
    }
  }
}""" % match_id

        try:
            req_data = json.dumps({"query": query}).encode("utf-8")
            req = urllib.request.Request(
                STRATZ_GRAPHQL,
                data=req_data,
                headers={
                    "Authorization": f"Bearer {self._stratz_token}",
                    "Content-Type": "application/json",
                    "User-Agent": "Dota2BuildGenerator/1.0",
                },
            )

            with urllib.request.urlopen(req, timeout=8) as response:
                data = json.loads(response.read().decode("utf-8"))

            match = data.get("data", {}).get("live", {}).get("match")
            if not match:
                print(f"[Stratz] Match {match_id} not found in live data")
                return None

            players = match.get("players", [])
            if not players:
                return None

            radiant = []
            dire = []
            for p in players:
                hero_id = p.get("heroId")
                if not hero_id or hero_id == 0:
                    continue
                hero_name = self._id_to_name.get(str(hero_id))
                if not hero_name:
                    continue
                if p.get("isRadiant"):
                    radiant.append(hero_name)
                else:
                    dire.append(hero_name)

            if not radiant and not dire:
                return None

            if my_team == "radiant":
                result = (radiant, dire)
            elif my_team == "dire":
                result = (dire, radiant)
            else:
                return None

            # Cache the result
            with self._lock:
                self._cache = {"stratz_teams": result}
                self._cache_time = time.time()
                self._last_match_id = match_id

            allies, enemies = result
            print(f"[Stratz] Live match {match_id}: "
                  f"Allies={allies} Enemies={enemies}")
            return result

        except urllib.error.HTTPError as e:
            if e.code == 401:
                print("[Stratz] Invalid API token - check data/config.json")
            else:
                print(f"[Stratz] HTTP error {e.code}: {e.reason}")
            return None
        except Exception as e:
            print(f"[Stratz] API error: {e}")
            return None

    # ═══════════════════════════════════════════════════════════════════
    # Fallback: OpenDota recent matches (only works for finished games)
    # ═══════════════════════════════════════════════════════════════════

    def lookup_match_heroes(self, account_id: str, my_team: str) -> Optional[tuple[list, list]]:
        """Look up finished match data from OpenDota using account ID.

        Args:
            account_id: Steam account ID (32-bit, from GSI player.accountid)
            my_team: "radiant" or "dire"

        Returns:
            (allies, enemies) tuple of hero ID strings, or None if lookup fails.
        """
        with self._lock:
            if (self._cache is not None
                    and time.time() - self._cache_time < self._cache_ttl
                    and self._cache.get("opendota_account") == account_id):
                return self._extract_teams(self._cache.get("opendota_match", {}), my_team)

        try:
            url = f"{OPENDOTA_BASE}/players/{account_id}/recentMatches"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                matches = resp.json()
                if matches and isinstance(matches, list) and len(matches) > 0:
                    match_id = matches[0].get("match_id")
                    if match_id:
                        match_url = f"{OPENDOTA_BASE}/matches/{match_id}"
                        match_resp = requests.get(match_url, timeout=8)
                        if match_resp.status_code == 200:
                            match_data = match_resp.json()
                            with self._lock:
                                self._cache = {
                                    "opendota_match": match_data,
                                    "opendota_account": account_id,
                                }
                                self._cache_time = time.time()
                            result = self._extract_teams(match_data, my_team)
                            if result:
                                print(f"[MatchLookup] Found match {match_id} via OpenDota")
                                return result
        except (requests.RequestException, json.JSONDecodeError, KeyError) as e:
            print(f"[MatchLookup] OpenDota API error: {e}")

        return None

    def _extract_teams(self, match_data: dict, my_team: str) -> Optional[tuple[list, list]]:
        """Extract ally and enemy hero lists from OpenDota match data."""
        players = match_data.get("players", [])
        if not players:
            return None

        radiant = []
        dire = []

        for p in players:
            hero_id = p.get("hero_id")
            if not hero_id:
                continue
            hero_name = self._id_to_name.get(str(hero_id))
            if not hero_name:
                continue

            is_radiant = p.get("isRadiant", p.get("player_slot", 128) < 128)
            if is_radiant:
                radiant.append(hero_name)
            else:
                dire.append(hero_name)

        if not radiant and not dire:
            return None

        if my_team == "radiant":
            return radiant, dire
        elif my_team == "dire":
            return dire, radiant
        else:
            return None

    def invalidate_cache(self):
        """Clear the cached match data (call when match changes)."""
        with self._lock:
            self._cache = None
            self._cache_time = 0
            self._last_match_id = None
            self._overwolf_cache = None
