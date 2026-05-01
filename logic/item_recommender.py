"""Immortal-level item recommendation engine.

Uses a hybrid approach combining:
1. Real statistical data from OpenDota (what items top players actually build)
2. Threat analysis (counter-building against enemy draft)
3. Matchup-specific adjustments (statistical win rates)
4. Team composition gap filling
5. Hero-specific base builds (hand-curated fallback)

Scoring formula per item:
  score = popularity (0-50) + threat_counter (0-30) + matchup_adj (0-15)
        + team_gap (0-10) + base_build (0-10) + priority_rules (variable)

The popularity score is the dominant factor — it reflects what real high-MMR
players build on each hero. The threat/matchup/team layers then adjust the
build dynamically for the specific 10-hero draft.
"""

import json
from pathlib import Path
from typing import Optional
from logic.threat_analyzer import ThreatAnalyzer
from logic.team_analyzer import TeamAnalyzer
from logic.data_loader import DataLoader


class ItemRecommender:
    """Recommends items based on real data + draft analysis."""

    ROLE_ALIASES = {
        "pos1": "pos1",
        "pos 1": "pos1",
        "1": "pos1",
        "hard carry": "pos1",
        "carry": "pos1",
        "pos2": "pos2",
        "pos 2": "pos2",
        "2": "pos2",
        "mid": "pos2",
        "midlane": "pos2",
        "pos3": "pos3",
        "pos 3": "pos3",
        "3": "pos3",
        "offlane": "pos3",
        "offlaner": "pos3",
        "pos4": "pos4",
        "pos 4": "pos4",
        "4": "pos4",
        "soft support": "pos4",
        "roamer": "pos4",
        "pos5": "pos5",
        "pos 5": "pos5",
        "5": "pos5",
        "hard support": "pos5",
        "hard_support": "pos5",
    }

    ROLE_CONFIGS = {
        "pos1": {
            "label": "Hard Carry (Pos 1)",
            "phase_counts": (2, 2, 2),
            "max_core_items": 6,
            "priority": "DPS > Survivability > Utility",
            "budget": "5-6 full items by 40 min",
            "timings": ["12-15 min", "20-24 min", "28-34 min", "36-42 min"],
        },
        "pos2": {
            "label": "Mid (Pos 2)",
            "phase_counts": (2, 2, 1),
            "max_core_items": 5,
            "priority": "Impact > Tempo > Scaling",
            "budget": "5-6 full items by 40 min",
            "timings": ["10-13 min", "18-22 min", "26-32 min", "34-40 min"],
        },
        "pos3": {
            "label": "Offlane (Pos 3)",
            "phase_counts": (2, 2, 1),
            "max_core_items": 5,
            "priority": "Aura/Utility > Survivability > Initiation",
            "budget": "4-5 items by 40 min",
            "timings": ["10-14 min", "18-24 min", "28-34 min", "36-42 min"],
        },
        "pos4": {
            "label": "Soft Support (Pos 4)",
            "phase_counts": (2, 1, 0),
            "max_core_items": 3,
            "priority": "Utility > Save > Initiation",
            "budget": "3-4 items by 40 min (12-15k gold)",
            "timings": ["10-13 min", "18-24 min", "28-34 min"],
        },
        "pos5": {
            "label": "Hard Support (Pos 5)",
            "phase_counts": (1, 2, 0),
            "max_core_items": 3,
            "priority": "Save > Wards/Detection > Survivability",
            "budget": "2-3 items by 40 min (8-10k gold)",
            "timings": ["12-15 min", "22-28 min", "32-38 min"],
        },
    }

    BOOT_IDS = {
        "power_treads", "phase_boots", "arcane_boots",
        "tranquil_boots", "boots_of_travel", "boots_of_travel_2",
        "travel_boots",  # alias used in some data sources
        "guardian_greaves",
    }

    DEFAULT_BOOTS = {
        "agi": "power_treads",
        "str": "phase_boots",
        "int": "arcane_boots",
        "uni": "power_treads",
        "all": "power_treads",
    }

    # Items that should never appear in carry/mid builds (support-only items)
    SUPPORT_ONLY = {
        "ward_observer", "ward_sentry", "dust", "smoke_of_deceit",
        "flying_courier", "tome_of_knowledge",
    }

    # Component/intermediate items that shouldn't appear in final builds
    COMPONENT_ITEMS = {
        # Basic components
        "broadsword", "claymore", "blades_of_attack", "mithril_hammer",
        "ring_of_health", "void_stone", "platemail", "hyperstone",
        "demon_edge", "eaglesong", "eagle", "reaver", "mystic_staff", "sacred_relic",
        "ogre_axe", "blade_of_alacrity", "staff_of_wizardry", "point_booster",
        "vitality_booster", "energy_booster", "talisman_of_evasion",
        "javelin", "quarterstaff", "helm_of_iron_will", "ring_of_regen",
        "ring_of_protection", "stout_shield", "boots", "gloves",
        "belt_of_strength", "robe", "band_of_elvenskin", "cloak",
        "ring_of_tarrasque", "fluffy_hat",
        "diadem", "cornucopia", "tiara_of_selemene", "voodoo_mask",
        "blitz_knuckles", "crown",
        # Intermediate items (usually built into something else)
        "lesser_crit", "oblivion_staff", "perseverance", "mask_of_death",
        "headdress", "buckler",
        "helm_of_the_dominator", "yasha", "sange", "kaya",
        "veil_of_discord",
        # Starting items (not for mid/late builds)
        "tango", "branches", "faerie_fire", "healing_salve", "clarity",
        "enchanted_mango", "gauntlets", "slippers", "mantle", "circlet",
        "quelling_blade",
    }

    GREEDY_DPS_ITEMS = {
        "bfury", "maelstrom", "mjollnir", "greater_crit", "daedalus",
        "butterfly", "satanic", "rapier", "monkey_king_bar", "bloodthorn",
        "nullifier", "silver_edge", "shadow_blade", "desolator",
        "diffusal_blade", "disperser", "mask_of_madness", "armlet",
    }

    SUPPORT_UTILITY_ITEMS = {
        "blink", "force_staff", "glimmer_cape", "ghost", "aeon_disk",
        "lotus_orb", "ultimate_scepter", "spirit_vessel", "solar_crest",
        "rod_of_atos", "ancient_janggo", "pavise", "cyclone",
    }

    FRONTLINE_UTILITY_ITEMS = {
        "pipe", "crimson_guard", "shivas_guard", "lotus_orb",
        "eternal_shroud", "heavens_halberd", "blade_mail", "assault",
    }

    TRAVEL_ITEMS = {"travel_boots", "boots_of_travel", "boots_of_travel_2"}

    POS1_CORE_RESTRICTIONS = {
        "force_staff", "glimmer_cape", "ghost", "pavise", "solar_crest",
        "guardian_greaves", "mekansm", "pipe", "crimson_guard",
    }
    POS1_LUXURY_POOL = [
        "butterfly", "skadi", "satanic", "abyssal_blade",
        "nullifier", "monkey_king_bar", "linken_sphere", "disperser",
    ]
    FARM_ACCELERATOR_ITEMS = {
        "bfury", "maelstrom", "mjollnir", "gleipnir", "radiance", "hand_of_midas",
    }

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.loader = DataLoader(str(self.data_dir))
        self.threat_analyzer = ThreatAnalyzer(data_dir)
        self.team_analyzer = TeamAnalyzer(data_dir)

        # Load item tags (rule-based counter system)
        item_tags_path = self.data_dir / "item_tags.json"
        if item_tags_path.exists():
            with open(item_tags_path, "r", encoding="utf-8") as f:
                self._item_tags = json.load(f)
        else:
            self._item_tags = {}

        # Load hero ID mapping
        map_path = self.data_dir / "hero_id_map.json"
        if map_path.exists():
            with open(map_path, "r", encoding="utf-8") as f:
                self._id_map = json.load(f)
        else:
            self._id_map = {}

        # Load OpenDota trained data (the real statistics)
        self._trained_builds = {}
        self._matchup_data = {}
        trained_path = self.data_dir / "opendota" / "trained_data.json"
        if trained_path.exists():
            with open(trained_path, "r", encoding="utf-8") as f:
                trained = json.load(f)
            self._trained_builds = trained.get("builds", {})
            self._matchup_data = trained.get("matchup_data", {})
            print(f"[Recommender] Loaded OpenDota data: {len(self._trained_builds)} heroes")
        else:
            print("[Recommender] No OpenDota data found - using rule-based fallback")

        # Load full matchup win-rate data
        self._full_matchups = {}
        matchups_path = self.data_dir / "opendota" / "matchups.json"
        if matchups_path.exists():
            with open(matchups_path, "r", encoding="utf-8") as f:
                self._full_matchups = json.load(f)
            print(f"[Recommender] Loaded matchup data: {len(self._full_matchups)} heroes")
        else:
            print("[Recommender] matchups.json missing -- matchup-specific tuning disabled")

        # Cache internal hero IDs for fast lookup in _ensure_valve_id
        self._internal_ids = {h["id"] for h in self.loader.get_all_heroes()}

    def _to_valve_id(self, hero_id: str) -> str:
        """Convert internal hero ID to Valve ID for tag lookup."""
        mapping = self._id_map.get("internal_to_valve", {})
        return mapping.get(hero_id, hero_id)

    def _to_internal_id(self, valve_id: str) -> str:
        """Convert Valve hero ID to internal ID for build lookup."""
        mapping = self._id_map.get("valve_to_internal", {})
        return mapping.get(valve_id, valve_id)

    def recommend(self, my_hero: str, enemies: list[str], allies: list[str],
                  my_items: Optional[list[str]] = None,
                  role: Optional[str] = None) -> dict:
        """Generate item recommendation for given draft.

        Args:
            my_hero: Hero ID (Valve or internal format)
            enemies: List of enemy hero IDs (Valve format)
            allies: List of ally hero IDs (Valve format)
            my_items: Current player inventory, used to avoid re-recommending owned items
            role: Explicit player role (pos1-pos5 / human-readable alias)

        Returns:
            Dict with early_game, mid_game, late_game items,
            plus threats, team_analysis, and reasoning.
        """
        # Normalize hero IDs
        internal_hero = self._to_internal_id(my_hero)
        valve_hero = self._to_valve_id(internal_hero)

        # Ensure enemies/allies are in Valve format for tag lookup
        valve_enemies = [self._ensure_valve_id(e) for e in enemies]
        valve_allies = [self._ensure_valve_id(a) for a in allies]
        owned_items = set(my_items or [])

        # Run analyses
        threats = self.threat_analyzer.analyze_enemies(valve_enemies)
        team = self.team_analyzer.analyze_team(valve_allies)

        # Get hero's hand-curated builds (fallback)
        hero_data = self.loader.get_hero(internal_hero)
        base_build = None
        if hero_data and hero_data.get("builds"):
            base_build = list(hero_data["builds"].values())[0]

        hero_attr = hero_data.get("primary_attr", "agi") if hero_data else "agi"
        hero_name = hero_data["name"] if hero_data else internal_hero.replace("_", " ").title()
        role_key = self._normalize_role_input(role)
        hero_profile = self._build_hero_profile(internal_hero, valve_allies, hero_data, role_key)
        role_context = self._build_role_context(role_key, hero_profile)

        # Get OpenDota popularity data for this hero
        opendota_builds = self._trained_builds.get(valve_hero, {})

        # Calculate matchup-specific adjustments
        matchup_context = self._analyze_matchup_context(valve_hero, valve_enemies)

        # Score items for each phase using the hybrid engine
        starting_items = self._build_early_game(valve_hero, opendota_builds, base_build, hero_attr)
        mid_scored = self._score_items_hybrid(
            "mid", valve_hero, opendota_builds, threats, team,
            matchup_context, hero_attr, base_build, owned_items, hero_profile, role_context
        )
        late_scored = self._score_items_hybrid(
            "late", valve_hero, opendota_builds, threats, team,
            matchup_context, hero_attr, base_build, owned_items, hero_profile, role_context
        )

        # Select top items per phase
        mid_candidates = self._select_phase_items(mid_scored, hero_attr, owned_items=owned_items)
        late_candidates = self._select_phase_items(
            late_scored, hero_attr, mid_candidates, owned_items=owned_items
        )
        early_game, mid_game, late_game, situational_swaps = self._build_role_plan(
            role_context, mid_candidates, late_candidates, threats, team, matchup_context, hero_profile
        )
        key_item_timings = self._build_key_item_timings(role_context, early_game, mid_game, late_game)

        # Generate reasoning
        reasoning = self._build_reasoning(
            threats, team, matchup_context, mid_game, late_game,
            hero_data=hero_data, hero_profile=hero_profile, role_context=role_context
        )

        return {
            "hero": internal_hero,
            "hero_name": hero_name,
            "role": role_context["code"],
            "role_label": role_context["label"],
            "starting_items": starting_items,
            "early_game": early_game,
            "mid_game": mid_game,
            "late_game": late_game,
            "situational_swaps": situational_swaps,
            "key_item_timings": key_item_timings,
            "threats": threats,
            "team_analysis": team,
            "matchup_context": matchup_context,
            "reasoning": reasoning,
            "hero_profile": hero_profile,
            "role_context": role_context,
        }

    def _ensure_valve_id(self, hero_id: str) -> str:
        """Ensure a hero ID is in Valve format."""
        if hero_id in self._internal_ids:
            return self._to_valve_id(hero_id)
        return hero_id

    @staticmethod
    def _normalize_roles(roles: list[str]) -> set[str]:
        return {
            str(role).strip().lower().replace(" ", "_")
            for role in roles or []
            if str(role).strip()
        }

    def _normalize_role_input(self, role: Optional[str]) -> Optional[str]:
        if not role:
            return None
        normalized = str(role).strip().lower().replace("_", " ")
        return self.ROLE_ALIASES.get(normalized) or self.ROLE_ALIASES.get(normalized.replace(" ", ""))

    def _build_role_context(self, role_key: Optional[str], hero_profile: dict) -> dict:
        if role_key is None:
            if hero_profile.get("support_lean"):
                role_key = "pos4"
            elif hero_profile.get("frontline_lean"):
                role_key = "pos3"
            elif hero_profile.get("carry_lean") and hero_profile.get("spellcaster_lean"):
                role_key = "pos2"
            elif hero_profile.get("carry_lean"):
                role_key = "pos1"
            else:
                role_key = "pos2"

        config = dict(self.ROLE_CONFIGS[role_key])
        config["code"] = role_key
        return config

    def _build_hero_profile(self, internal_hero: str, valve_allies: list[str],
                            hero_data: Optional[dict],
                            role_key: Optional[str] = None) -> dict:
        """Infer a practical build profile for flexible heroes.

        The app does not currently receive an explicit role input, so this keeps
        the recommender from treating flexible supports like generic right-click
        cores whenever the enemy draft suggests anti-illusion or split-push tech.
        """
        hero_roles = self._normalize_roles(hero_data.get("roles", []) if hero_data else [])
        allied_core_count = 0
        for ally in valve_allies:
            ally_internal = self._to_internal_id(ally)
            if ally_internal == internal_hero:
                continue
            ally_data = self.loader.get_hero(ally_internal)
            ally_roles = self._normalize_roles(ally_data.get("roles", []) if ally_data else [])
            if ally_roles & {"carry", "mid", "offlane"}:
                allied_core_count += 1

        support_lean = role_key in {"pos4", "pos5"} or ("support" in hero_roles and allied_core_count >= 3)
        carry_lean = role_key in {"pos1", "pos2"} or (not support_lean and bool(hero_roles & {"carry", "mid"}))
        frontline_lean = role_key == "pos3" or bool(hero_roles & {"durable", "initiator"})
        spellcaster_lean = (
            role_key in {"pos4", "pos5"}
            or (role_key == "pos2" and (hero_data or {}).get("primary_attr") == "int")
            or
            (hero_data or {}).get("primary_attr") == "int"
            or bool(hero_roles & {"support", "nuker", "disabler"})
        )
        stats_by_internal = getattr(self.loader, "_hero_stats_by_internal", {})
        stats = stats_by_internal.get(internal_hero, {})
        attack_type = str(stats.get("attack_type", "")).lower()
        is_ranged = attack_type == "ranged"
        is_melee = attack_type == "melee" or not is_ranged

        return {
            "roles": sorted(hero_roles),
            "role_override": role_key,
            "support_lean": support_lean,
            "carry_lean": carry_lean,
            "frontline_lean": frontline_lean,
            "spellcaster_lean": spellcaster_lean,
            "allied_core_count": allied_core_count,
            "attack_type": attack_type,
            "is_ranged": is_ranged,
            "is_melee": is_melee,
        }

    def _analyze_matchup_context(self, my_hero: str, enemies: list[str]) -> dict:
        """Analyze matchup-specific context from statistical data.

        Returns items that help in bad matchups and general difficulty assessment.
        """
        hero_matchups = self._full_matchups.get(my_hero, {})
        if not hero_matchups:
            return {"difficulty": "unknown", "bad_matchups": [], "adjustments": []}

        bad_matchups = []
        total_disadvantage = 0.0
        enemy_count = 0

        for enemy in enemies:
            matchup = hero_matchups.get(enemy)
            if matchup:
                advantage = matchup.get("advantage", 0)
                total_disadvantage += advantage
                enemy_count += 1
                if advantage < -0.03:  # More than 3% disadvantage
                    bad_matchups.append({
                        "enemy": enemy,
                        "advantage": advantage,
                        "games": matchup.get("games", 0),
                    })

        avg_advantage = total_disadvantage / enemy_count if enemy_count > 0 else 0

        if avg_advantage < -0.03:
            difficulty = "very_hard"
        elif avg_advantage < -0.01:
            difficulty = "hard"
        elif avg_advantage > 0.03:
            difficulty = "easy"
        elif avg_advantage > 0.01:
            difficulty = "favorable"
        else:
            difficulty = "even"

        # Sort bad matchups by how bad they are
        bad_matchups.sort(key=lambda x: x["advantage"])

        return {
            "difficulty": difficulty,
            "avg_advantage": round(avg_advantage, 4),
            "bad_matchups": bad_matchups[:5],
            "adjustments": [],
        }

    def _build_early_game(self, valve_hero: str, opendota_builds: dict,
                          base_build: Optional[dict], hero_attr: str) -> list[dict]:
        """Build early game items.

        Starting items are formulaic and don't vary much by matchup,
        so we prefer hand-curated builds for early game. OpenDota data
        is most valuable for mid/late itemization.
        """
        # Always prefer hand-curated builds for starting items
        if base_build and "early_game" in base_build:
            return base_build["early_game"]

        # Fallback: construct a sensible starting build from hero attribute
        return self._default_early(hero_attr)

    def _score_items_hybrid(self, phase: str, valve_hero: str,
                            opendota_builds: dict, threats: dict, team: dict,
                            matchup_context: dict, hero_attr: str,
                            base_build: Optional[dict],
                            owned_items: Optional[set[str]] = None,
                            hero_profile: Optional[dict] = None,
                            role_context: Optional[dict] = None) -> list[tuple[str, float, str]]:
        """Score items using hybrid: OpenDota data + threat analysis + team gaps.

        Scoring weights:
            - OpenDota popularity:   0-50 points (dominant factor)
            - Threat counter:        0-30 points (reactive to enemy draft)
            - Matchup difficulty:    0-15 points (adjusts for hard matchups)
            - Team gap:              0-10 points (fills team needs)
            - Base build affinity:   0-10 points (hero-specific tiebreaker)
            - Priority rules:        variable (conditional bonuses)
        """
        owned_items = owned_items or set()
        scored = {}  # item_id -> (score, reasons)

        phase_key = f"{phase}_game"
        opendota_phase = opendota_builds.get(phase_key, [])

        # ═══ LAYER 1: OpenDota Popularity (0-50 points) ═══
        # This is the DOMINANT signal - what do real players build?
        if opendota_phase:
            # Filter to final items only, then normalize among them
            final_items = [
                e for e in opendota_phase
                if e["item"] not in self.SUPPORT_ONLY
                and e["item"] not in self.COMPONENT_ITEMS
            ]
            max_pop = max(e["popularity"] for e in final_items) if final_items else 1

            for entry in final_items:
                item_id = entry["item"]

                # Normalize popularity to 0-50 score (relative to most popular final item)
                pop_score = (entry["popularity"] / max(max_pop, 1)) * 50
                reasons = [f"{entry['popularity']:.0f}% build rate"]
                scored[item_id] = (pop_score, reasons)

        # ═══ LAYER 2: Threat Counter (0-30 points) ═══
        # Items that directly counter enemy threats get big bonuses
        for item_id, tags in self._item_tags.items():
            phases = tags.get("phase", [])
            if phase not in phases:
                continue

            threat_score = 0.0
            threat_reasons = []

            for counter in tags.get("counters", []):
                if counter in threats.get("threat_summary", []):
                    threat_score += 12
                    threat_reasons.append(f"counters {counter}")

            # Cap threat score at 30
            threat_score = min(threat_score, 30)

            if threat_score > 0:
                if item_id in scored:
                    old_score, old_reasons = scored[item_id]
                    scored[item_id] = (old_score + threat_score, old_reasons + threat_reasons[:2])
                else:
                    scored[item_id] = (threat_score, threat_reasons[:2])

        # ═══ LAYER 3: Matchup Difficulty Adjustment (0-15 points) ═══
        # In hard matchups, prioritize defensive/survival items
        difficulty = matchup_context.get("difficulty", "even")
        if difficulty in ("very_hard", "hard"):
            defensive_items = {
                "black_king_bar", "aeon_disk", "linken_sphere", "satanic",
                "heart", "assault", "shivas_guard", "heavens_halberd",
                "blade_mail", "hood_of_defiance", "pipe", "crimson_guard",
                "eternal_shroud", "mage_slayer",
            }
            for item_id in defensive_items:
                bonus = 15 if difficulty == "very_hard" else 10
                if item_id in scored:
                    old_score, old_reasons = scored[item_id]
                    scored[item_id] = (old_score + bonus, old_reasons + ["hard matchup - survival"])
                elif item_id in self._item_tags:
                    tags = self._item_tags[item_id]
                    if phase in tags.get("phase", []):
                        scored[item_id] = (bonus, ["hard matchup - survival"])

        # ═══ LAYER 4: Team Gap (0-10 points) ═══
        for item_id, tags in self._item_tags.items():
            if phase not in tags.get("phase", []):
                continue
            gap_score = 0
            gap_reasons = []
            for provides in tags.get("provides", []):
                if provides in team.get("gaps", []):
                    gap_score += 10
                    gap_reasons.append(f"team needs {provides}")
            if gap_score > 0:
                gap_score = min(gap_score, 10)
                if item_id in scored:
                    old_score, old_reasons = scored[item_id]
                    scored[item_id] = (old_score + gap_score, old_reasons + gap_reasons[:1])
                else:
                    scored[item_id] = (gap_score, gap_reasons[:1])

        # ═══ LAYER 5: Base Build Affinity (0-10 points) ═══
        if base_build:
            base_items = [i.get("item") for i in base_build.get(phase_key, [])]
            for item_id in base_items:
                if item_id in scored:
                    old_score, old_reasons = scored[item_id]
                    scored[item_id] = (old_score + 10, old_reasons + ["hero core item"])
                else:
                    scored[item_id] = (10, ["hero core item"])

        # ═══ LAYER 6: Priority Rules (variable) ═══
        for item_id, tags in self._item_tags.items():
            if phase not in tags.get("phase", []):
                continue
            for rule in tags.get("priority_rules", []):
                condition = rule.get("condition", "")
                bonus = rule.get("bonus", 0)
                if self._evaluate_condition(condition, threats, hero_attr):
                    if item_id in scored:
                        old_score, old_reasons = scored[item_id]
                        scored[item_id] = (old_score + bonus, old_reasons)
                    else:
                        scored[item_id] = (bonus, [condition])

        # ═══ LAYER 7: Attribute Match (small tiebreaker) ═══
        for item_id, tags in self._item_tags.items():
            if phase not in tags.get("phase", []):
                continue
            stat_type = tags.get("stat_type", "")
            if stat_type == hero_attr and item_id in scored:
                old_score, old_reasons = scored[item_id]
                scored[item_id] = (old_score + 3, old_reasons)

        self._apply_profile_biases(scored, phase, hero_profile or {})
        self._apply_role_biases(scored, phase, role_context or {}, hero_profile or {})

        # Convert to sorted list
        result = []
        for item_id, (score, reasons) in scored.items():
            if item_id in self.SUPPORT_ONLY:
                continue
            if item_id in owned_items:
                continue
            reason_str = ", ".join(reasons[:3])
            result.append((item_id, score, reason_str))

        result.sort(key=lambda x: x[1], reverse=True)
        return result

    @staticmethod
    def _apply_score_delta(scored: dict, item_id: str, delta: float, reason: str = ""):
        if item_id not in scored:
            return
        old_score, old_reasons = scored[item_id]
        reasons = old_reasons + [reason] if reason and delta > 0 else old_reasons
        scored[item_id] = (old_score + delta, reasons)

    def _apply_profile_biases(self, scored: dict, phase: str, hero_profile: dict):
        """Bias scoring toward realistic hero jobs in the current draft."""
        if hero_profile.get("support_lean"):
            utility_bonus = 14 if phase == "mid" else 10
            for item_id in self.SUPPORT_UTILITY_ITEMS:
                self._apply_score_delta(scored, item_id, utility_bonus, "support-lean utility")
            for item_id in self.GREEDY_DPS_ITEMS:
                self._apply_score_delta(scored, item_id, -22)
            self._apply_score_delta(scored, "bfury", -40)
            for item_id in self.TRAVEL_ITEMS:
                self._apply_score_delta(scored, item_id, -12)
            for item_id in {"pipe", "crimson_guard", "shivas_guard", "assault", "eternal_shroud", "blade_mail"}:
                self._apply_score_delta(scored, item_id, -10)

        if hero_profile.get("spellcaster_lean"):
            for item_id in {"bfury", "maelstrom", "mjollnir", "greater_crit", "daedalus", "desolator"}:
                self._apply_score_delta(scored, item_id, -16)
            for item_id in {
                "ultimate_scepter", "lotus_orb", "aeon_disk", "force_staff",
                "cyclone", "glimmer_cape", "ghost", "rod_of_atos",
                "spirit_vessel", "solar_crest", "kaya_and_sange",
                "shivas_guard", "blink",
            }:
                self._apply_score_delta(scored, item_id, 8, "spellcaster fit")

        if hero_profile.get("frontline_lean"):
            for item_id in self.FRONTLINE_UTILITY_ITEMS:
                self._apply_score_delta(scored, item_id, 8, "frontline utility")

        if hero_profile.get("carry_lean") and not hero_profile.get("support_lean"):
            for item_id in self.GREEDY_DPS_ITEMS:
                self._apply_score_delta(scored, item_id, 6, "core scaling")

    def _apply_role_biases(self, scored: dict, phase: str, role_context: dict, hero_profile: dict):
        """Apply explicit role priorities on top of generic hero-profile logic."""
        role_code = role_context.get("code")
        if not role_code:
            return

        if role_code == "pos1":
            for item_id in self.GREEDY_DPS_ITEMS:
                self._apply_score_delta(scored, item_id, 10, "pos1 scaling")
            for item_id in self.SUPPORT_UTILITY_ITEMS | self.FRONTLINE_UTILITY_ITEMS | self.POS1_CORE_RESTRICTIONS:
                self._apply_score_delta(scored, item_id, -16)
            if hero_profile.get("is_melee"):
                for item_id in {"hurricane_pike", "dragon_lance"}:
                    self._apply_score_delta(scored, item_id, -28)
        elif role_code == "pos2":
            for item_id in {"blink", "black_king_bar", "ultimate_scepter", "cyclone",
                            "orchid", "rod_of_atos", "witch_blade", "force_staff"}:
                self._apply_score_delta(scored, item_id, 10, "pos2 tempo")
            for item_id in {"pipe", "crimson_guard"}:
                self._apply_score_delta(scored, item_id, -10)
        elif role_code == "pos3":
            for item_id in self.FRONTLINE_UTILITY_ITEMS | {"blink", "lotus_orb"}:
                self._apply_score_delta(scored, item_id, 14, "pos3 utility")
            for item_id in self.GREEDY_DPS_ITEMS:
                self._apply_score_delta(scored, item_id, -12)
        elif role_code == "pos4":
            for item_id in self.SUPPORT_UTILITY_ITEMS | {"gleipnir", "glimmer_cape"}:
                self._apply_score_delta(scored, item_id, 16, "pos4 utility")
            for item_id in self.GREEDY_DPS_ITEMS:
                self._apply_score_delta(scored, item_id, -24)
            for item_id in self.FRONTLINE_UTILITY_ITEMS | self.TRAVEL_ITEMS:
                self._apply_score_delta(scored, item_id, -14)
        elif role_code == "pos5":
            for item_id in {"force_staff", "glimmer_cape", "pavise", "solar_crest",
                            "lotus_orb", "ghost", "aeon_disk", "ultimate_scepter"}:
                self._apply_score_delta(scored, item_id, 18, "pos5 save")
            for item_id in self.GREEDY_DPS_ITEMS | self.FRONTLINE_UTILITY_ITEMS | self.TRAVEL_ITEMS:
                self._apply_score_delta(scored, item_id, -18)

    def _build_role_plan(self, role_context: dict, mid_candidates: list[dict], late_candidates: list[dict],
                         threats: dict, team: dict, matchup_context: dict,
                         hero_profile: Optional[dict] = None) -> tuple[list[dict], list[dict], list[dict], list[str]]:
        ranked_candidates = self._merge_ranked_candidates(
            mid_candidates, late_candidates, role_context, threats, hero_profile or {}
        )
        max_core = role_context.get("max_core_items", 6)
        core_items = ranked_candidates[:max_core]
        early_count, mid_count, late_count = role_context.get("phase_counts", (2, 2, 2))

        early_game = core_items[:early_count]
        mid_game = core_items[early_count:early_count + mid_count]
        late_game = core_items[early_count + mid_count:early_count + mid_count + late_count]
        situational_swaps = self._build_situational_swaps(
            role_context, threats, team, matchup_context, ranked_candidates[max_core:], core_items, hero_profile or {}
        )
        return early_game, mid_game, late_game, situational_swaps

    def _merge_ranked_candidates(self, mid_candidates: list[dict], late_candidates: list[dict],
                                 role_context: dict, threats: dict,
                                 hero_profile: Optional[dict] = None) -> list[dict]:
        merged = []
        seen = set()
        for item in mid_candidates + late_candidates:
            item_id = item.get("item", "")
            if (not item_id or item_id == "magic_wand" or item_id in seen
                    or item_id in self.COMPONENT_ITEMS or item_id in self.SUPPORT_ONLY):
                continue
            if self._is_role_conflict(item_id, seen, role_context, threats, hero_profile or {}):
                continue
            merged.append(item)
            seen.add(item_id)
        return merged

    def _is_role_conflict(self, item_id: str, seen: set[str], role_context: dict,
                          threats: dict, hero_profile: Optional[dict] = None) -> bool:
        conflict_pair = {"black_king_bar", "aeon_disk"}
        if item_id in conflict_pair and seen & conflict_pair:
            role_code = role_context.get("code")
            preferred = "aeon_disk" if role_code == "pos5" else "black_king_bar"
            if threats.get("disable_count", 0) >= 4 and role_code in {"pos4", "pos5"}:
                preferred = "aeon_disk"
            return item_id != preferred
        if item_id in self.FARM_ACCELERATOR_ITEMS and seen & self.FARM_ACCELERATOR_ITEMS:
            return True
        role_code = role_context.get("code")
        if role_code == "pos1":
            if item_id in self.POS1_CORE_RESTRICTIONS:
                return True
            if (hero_profile or {}).get("is_melee") and item_id in {"hurricane_pike", "dragon_lance"}:
                return True
        return False

    def _build_key_item_timings(self, role_context: dict,
                                early_game: list[dict], mid_game: list[dict], late_game: list[dict]) -> list[str]:
        plan = early_game + mid_game + late_game
        timings = role_context.get("timings", [])
        all_items = self.loader.get_all_items()
        lines = []
        for idx, item in enumerate(plan[:len(timings)]):
            item_id = item.get("item", "")
            if not item_id:
                continue
            item_name = all_items.get(item_id, {}).get("name", item_id.replace("_", " ").title())
            lines.append(f"{item_name} by {timings[idx]}")
        return lines

    def _build_situational_swaps(self, role_context: dict, threats: dict, team: dict,
                                 matchup_context: dict, fallback_candidates: list[dict],
                                 core_items: list[dict],
                                 hero_profile: Optional[dict] = None) -> list[str]:
        role_code = role_context.get("code")
        core_ids = {item.get("item", "") for item in core_items}
        all_items = self.loader.get_all_items()
        lines = []
        used_swaps = set()

        def item_name(item_id: str) -> str:
            return all_items.get(item_id, {}).get("name", item_id.replace("_", " ").title())

        def add_swap(prefix: str, candidates: list[str]) -> None:
            for candidate in candidates:
                if candidate in core_ids or candidate in used_swaps:
                    continue
                used_swaps.add(candidate)
                lines.append(f"{prefix} -> {item_name(candidate)}")
                return

        if role_code == "pos1":
            if threats.get("magic_threat_count", 0) >= 2:
                add_swap("IF magic burst overwhelms fights", ["black_king_bar", "linken_sphere"])
            if threats.get("disable_count", 0) >= 3 or threats.get("silence_count", 0) >= 1:
                disable_candidates = ["linken_sphere", "satanic"]
                if threats.get("silence_count", 0) >= 1:
                    disable_candidates = ["manta"] + disable_candidates
                add_swap("IF you keep getting chain-disabled", disable_candidates)
            if threats.get("physical_threat_count", 0) >= 3:
                add_swap("IF physical focus becomes the issue", ["butterfly", "satanic"])
        else:
            if threats.get("magic_threat_count", 0) >= 2:
                swap = "glimmer_cape" if role_code in {"pos4", "pos5"} else "pipe"
                add_swap("IF magic burst overwhelms fights", [swap])
            if threats.get("disable_count", 0) >= 3 or threats.get("silence_count", 0) >= 1:
                if role_code in {"pos3", "pos4"}:
                    swap = "lotus_orb"
                elif role_code == "pos5":
                    swap = "force_staff"
                else:
                    swap = "linken_sphere"
                add_swap("IF your team keeps getting chain-disabled", [swap])
            if threats.get("physical_threat_count", 0) >= 3:
                swap = "ghost" if role_code in {"pos4", "pos5"} else "shivas_guard"
                add_swap("IF physical focus becomes the issue", [swap])
        if threats.get("invis_count", 0) >= 1 and role_code in {"pos4", "pos5"}:
            lines.append("IF invis heroes come online -> carry Dust/Sentries, later Gem if you control map")
        if "save" in team.get("gaps", []) and role_code in {"pos4", "pos5"}:
            lines.append("IF your cores keep getting caught -> Force Staff or Lotus Orb before greed")

        if role_code == "pos1":
            for item_id in self.POS1_LUXURY_POOL:
                if len(lines) >= 3:
                    break
                if item_id in core_ids or item_id not in all_items:
                    continue
                if (hero_profile or {}).get("is_melee") and item_id in {"hurricane_pike", "dragon_lance"}:
                    continue
                lines.append(f"IF the game goes long -> {item_name(item_id)}")
            return lines[:3]

        for item in fallback_candidates:
            if len(lines) >= 3:
                break
            item_id = item.get("item", "")
            if not item_id or item_id in core_ids:
                continue
            lines.append(f"IF the game goes long -> {item_name(item_id)}")

        return lines[:3]

    def _evaluate_condition(self, condition: str, threats: dict, hero_attr: str) -> bool:
        """Evaluate a priority rule condition."""
        if not condition:
            return False
        try:
            if "hero_is_ranged" in condition:
                return hero_attr == "agi"
            if "hero_is_melee" in condition:
                return hero_attr in ("str", "uni")

            for op in [">=", "<=", "==", ">"]:
                if op in condition:
                    parts = condition.split(op)
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = int(parts[1].strip())
                        actual = threats.get(key, 0)
                        if op == ">=" and actual >= val:
                            return True
                        elif op == "<=" and actual <= val:
                            return True
                        elif op == "==" and actual == val:
                            return True
                        elif op == ">" and actual > val:
                            return True
        except (ValueError, KeyError, IndexError):
            pass
        return False

    def _select_phase_items(self, scored: list, hero_attr: str,
                            prev_phase: list = None,
                            owned_items: Optional[set[str]] = None) -> list[dict]:
        """Select top 6 items for a phase, ensuring boots and avoiding duplicates.

        When prev_phase is provided (e.g. mid_game items passed when building late_game),
        items already in the previous phase are skipped so each phase recommends
        distinct items and the build shows actual progression.
        """
        selected = []
        selected_ids = set()
        owned_items = owned_items or set()

        # Track items from previous phase to avoid recommending them again
        prev_ids = set()
        if prev_phase:
            prev_ids = {item["item"] for item in prev_phase}
        has_existing_boots = any(item_id in self.BOOT_IDS for item_id in owned_items) or any(
            item_id in self.BOOT_IDS for item_id in prev_ids
        )

        # Ensure boots first (boots can carry over between phases)
        boot_added = False
        if not has_existing_boots:
            for item_id, score, reason in scored:
                if item_id in owned_items:
                    continue
                if item_id in self.BOOT_IDS:
                    selected.append({"item": item_id, "note": reason})
                    selected_ids.add(item_id)
                    boot_added = True
                    break

            if not boot_added:
                default_boot = self.DEFAULT_BOOTS.get(hero_attr, "power_treads")
                boot_candidates = [default_boot] + [b for b in sorted(self.BOOT_IDS) if b != default_boot]
                fallback_boot = next((b for b in boot_candidates if b not in owned_items), None)
                if fallback_boot:
                    selected.append({"item": fallback_boot, "note": "standard boots"})
                    selected_ids.add(fallback_boot)

        # Fill remaining 5 slots, skipping items already in the previous phase
        for item_id, score, reason in scored:
            if len(selected) >= 6:
                break
            if item_id in selected_ids or item_id in self.BOOT_IDS:
                continue
            if item_id in owned_items:
                continue
            if item_id in self.COMPONENT_ITEMS:
                continue
            if item_id in prev_ids:
                continue  # Don't repeat items from the previous phase
            selected.append({"item": item_id, "note": reason})
            selected_ids.add(item_id)

        # Pad if needed
        while len(selected) < 6:
            selected.append({"item": "magic_wand", "note": "utility"})

        return selected

    def _default_early(self, hero_attr: str) -> list[dict]:
        """Default starting items if no data available."""
        stat_item = {
            "agi": "slippers",
            "str": "gauntlets",
            "int": "mantle",
            "uni": "circlet",
            "all": "circlet",
        }.get(hero_attr, "circlet")

        return [
            {"item": "tango", "note": "Regen"},
            {"item": "branches", "note": "Cheap stats"},
            {"item": "branches", "note": "Cheap stats"},
            {"item": stat_item, "note": "Stat item"},
            {"item": "circlet", "note": "Stats"},
            {"item": "quelling_blade" if hero_attr in ("agi", "str") else "faerie_fire", "note": "Last hits"},
        ]

    def _build_reasoning(self, threats: dict, team: dict, matchup_context: dict,
                         mid_items: list, late_items: list,
                         hero_data: Optional[dict] = None,
                         hero_profile: Optional[dict] = None,
                         role_context: Optional[dict] = None) -> list[str]:
        """Generate human-readable reasoning."""
        lines = []

        # Runtime honesty: disclose when this hero uses synthesized fallback data.
        if hero_data and hero_data.get("auto_generated"):
            lines.append("Using auto-generated hero profile (no curated hero file bundled)")

        if role_context:
            lines.append(f"{role_context['label']}: {role_context['priority']}")

        if hero_profile and hero_profile.get("support_lean"):
            lines.append("Support-lean draft for this hero - prioritizing utility over greedy DPS")
        elif hero_profile and hero_profile.get("spellcaster_lean"):
            lines.append("Spellcaster profile - prioritizing control and survivability")

        # Matchup difficulty
        difficulty = matchup_context.get("difficulty", "even")
        if difficulty == "very_hard":
            lines.append("HARD GAME - prioritizing survivability items")
        elif difficulty == "hard":
            lines.append("Tough matchup - defensive items recommended")
        elif difficulty == "easy":
            lines.append("Favorable matchup - greedy build viable")

        # Threat warnings
        for warning in threats.get("warnings", []):
            lines.append(warning)

        # Bad matchups
        bad = matchup_context.get("bad_matchups", [])
        if bad:
            worst = bad[0]
            adv_pct = abs(worst["advantage"]) * 100
            enemy_name = worst["enemy"].replace("_", " ").title()
            lines.append(f"Watch out for {enemy_name} ({adv_pct:.1f}% disadvantage)")

        # Team gaps
        summary = team.get("summary", {})
        weaknesses = summary.get("weaknesses", [])
        if weaknesses:
            lines.append(f"Team lacks: {', '.join(weaknesses[:3])}")

        # Key item explanations (from top mid items)
        all_items = self.loader.get_all_items()
        for item in mid_items[1:4]:  # Skip boots
            note = item.get("note", "")
            item_id = item.get("item", "")
            if note and "standard boots" not in note and "utility" not in note:
                item_info = all_items.get(item_id, {})
                item_name = item_info.get("name", item_id.replace("_", " ").title())
                # Truncate long notes
                if len(note) > 50:
                    note = note[:50] + "..."
                lines.append(f"{item_name}: {note}")

        return lines[:7]  # Cap at 7 lines
