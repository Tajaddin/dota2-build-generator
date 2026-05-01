"""AI-powered item recommendation using hero build statistics + matchup adjustment.

Primary approach: Stats-first
  1. hero_item_stats.json provides per-hero item frequencies and win rates
     extracted from real match data (final inventories + purchase timestamps).
  2. Items are assigned to game phases (early/mid/late) using purchase-log
     timing data cross-referenced with final-inventory items.
  3. XGBoost models (trained on embeddings) provide matchup-specific score
     adjustments — boosting items that are strong against the enemy draft.

Fallback: If hero stats are unavailable for a hero, falls back to the old
XGBoost-only prediction (less accurate but still functional).
"""
import json
import pickle
import numpy as np
import torch
from pathlib import Path
from typing import Optional

from ml.embedding_model import DotaEmbeddingModel
from ml.id_mapper import IDMapper
from logic.item_recommender import ItemRecommender

# Items that should never be recommended (event items, recipes, non-purchasable)
BLOCKED_ITEM_PREFIXES = ("recipe_",)
BLOCKED_ITEMS = {
    # Innate/event items (not purchasable in normal games)
    "famango", "great_famango", "greater_famango",
    "ofrenda", "ofrenda_shovel", "ofrenda_pledge",
    "mysterious_hat", "river_painter", "river_painter2",
    "river_painter3", "river_painter4", "river_painter5",
    "river_painter6", "river_painter7",
    # Roshan drops / non-purchasable
    "aegis", "cheese", "refresher_shard",
    # Consumables — never recommend as core build items
    "tpscroll", "tp_scroll", "tango", "tango_shared", "clarity",
    "flask", "faerie_fire", "enchanted_mango", "blood_grenade",
    "smoke_of_deceit", "dust", "dust_of_appearance",
    "ward_observer", "ward_sentry", "observer_ward", "sentry_ward",
    "tome_of_knowledge", "gem_of_true_sight",
    # Cheap components — not worth a recommendation slot
    "iron_branch", "branches", "circlet", "gauntlets", "slippers",
    "mantle", "ring_of_protection", "magic_stick",
}


class AIRecommender:
    """Stats-first item recommender with neural matchup adjustment.

    Uses hero_item_stats.json as the primary data source for what items each
    hero builds, with XGBoost models providing matchup-specific adjustments.
    Falls back to None if no data is available at all.
    """

    def __init__(self, data_dir: str, model_dir: str = "models"):
        self.data_dir = Path(data_dir)
        self.model_dir = Path(model_dir)
        self.mapper = IDMapper(data_dir)
        self._embedder = None
        self._xgb_models = {}
        self._hero_stats = {}
        self._available = False
        self._availability_reason = "not_initialized"

        # Load items.json for display names and cost data
        items_path = self.data_dir / "items.json"
        if items_path.exists():
            with open(items_path, "r", encoding="utf-8") as f:
                self._items = json.load(f)
        else:
            self._items = {}

        # Build set of valid purchasable item names from items.json
        self._valid_items = set(self._items.keys()) if self._items else None

        # Load hero display names
        self._hero_display_names = {}
        hero_map_path = self.data_dir / "hero_id_map.json"
        self._valve_to_internal = {}
        self._internal_to_valve = {}
        if hero_map_path.exists():
            with open(hero_map_path, "r", encoding="utf-8") as f:
                hmap = json.load(f)
            self._valve_to_internal = hmap.get("valve_to_internal", {})
            self._internal_to_valve = hmap.get("internal_to_valve", {})
            hero_tags_path = self.data_dir / "hero_tags.json"
            if hero_tags_path.exists():
                with open(hero_tags_path, "r", encoding="utf-8") as f:
                    hero_tags = json.load(f)
                for internal, data in hero_tags.items():
                    if isinstance(data, dict) and "name" in data:
                        self._hero_display_names[internal] = data["name"]

        # Load hero item statistics (primary data source)
        self._load_hero_stats()

        # Load neural models (for matchup adjustment)
        self._try_load_models()

    def _load_hero_stats(self):
        """Load per-hero item statistics from hero_item_stats.json."""
        stats_path = self.model_dir / "hero_item_stats.json"
        if stats_path.exists():
            with open(stats_path, "r", encoding="utf-8") as f:
                self._hero_stats = json.load(f)
            print(f"[AIRecommender] Loaded hero item stats for {len(self._hero_stats)} heroes")
        else:
            self._hero_stats = {}
            print("[AIRecommender] No hero_item_stats.json found")

    def _try_load_models(self):
        """Attempt to load embedding + XGBoost models for matchup adjustment."""
        embed_path = self.model_dir / "embeddings.pt"

        # Hero stats alone are enough for basic recommendations
        if self._hero_stats:
            self._available = True
            self._availability_reason = f"stats_only:{len(self._hero_stats)}_heroes"
            print(f"[AIRecommender] Stats-based recommendations available ({len(self._hero_stats)} heroes)")

        if not embed_path.exists():
            if not self._hero_stats:
                self._availability_reason = "no_stats_no_models"
                print("[AIRecommender] No hero stats or embedding model — AI disabled")
            return

        try:
            checkpoint = torch.load(embed_path, map_location="cpu", weights_only=True)
            self._embedder = DotaEmbeddingModel(
                num_heroes=checkpoint["max_hero_id"],
                num_items=checkpoint["max_item_id"],
                hero_embed_dim=checkpoint.get("hero_embed_dim", 64),
                item_embed_dim=checkpoint.get("item_embed_dim", 32),
            )
            self._embedder.load_state_dict(checkpoint["model_state"])
            self._embedder.eval()
            print("[AIRecommender] Loaded embedding model (matchup adjustment enabled)")

            for phase in ["draft", "early", "mid", "late"]:
                pkl_path = self.model_dir / f"xgb_{phase}.pkl"
                if pkl_path.exists():
                    with open(pkl_path, "rb") as f:
                        self._xgb_models[phase] = pickle.load(f)

            if self._xgb_models:
                self._force_xgb_cpu_inference()
                self._available = True
                phases = ",".join(sorted(self._xgb_models.keys()))
                mode = "stats+matchup" if self._hero_stats else "xgb_only"
                self._availability_reason = f"ready:{mode}:{phases}"
                print(f"[AIRecommender] AI ready — {mode} mode with {len(self._xgb_models)} XGBoost models")

        except Exception as e:
            print(f"[AIRecommender] Failed to load neural models: {e}")
            if not self._hero_stats:
                self._available = False
                self._availability_reason = f"load_error:{e}"

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def availability_reason(self) -> str:
        return self._availability_reason

    def _force_xgb_cpu_inference(self):
        """Normalize loaded XGBoost estimators to CPU for desktop inference."""
        normalized = 0
        for model_data in self._xgb_models.values():
            multi_model = model_data.get("model")
            estimators = getattr(multi_model, "estimators_", None)
            if not estimators:
                continue
            for estimator in estimators:
                try:
                    estimator.set_params(device="cpu")
                except Exception:
                    pass
                try:
                    estimator.get_booster().set_param({"device": "cpu"})
                except Exception:
                    pass
            normalized += 1
        if normalized:
            print(f"[AIRecommender] Forced {normalized} XGBoost model groups to CPU inference")

    # ═══════════════════════════════════════════════════════════════
    # Item validation
    # ═══════════════════════════════════════════════════════════════

    def _is_valid_item(self, item_name: str) -> bool:
        """Check if an item is a valid purchasable item (not a recipe/event/junk)."""
        if not item_name or item_name.startswith("unknown"):
            return False
        if item_name in BLOCKED_ITEMS:
            return False
        for prefix in BLOCKED_ITEM_PREFIXES:
            if item_name.startswith(prefix):
                return False
        if self._valid_items and item_name not in self._valid_items:
            return False
        return True

    def _is_recommendable_item(self, item_name: str) -> bool:
        """Check if an item should appear in build recommendations.

        Filters out components, support-only items, and non-purchasable junk
        on top of the basic validity check.
        """
        if not self._is_valid_item(item_name):
            return False
        if item_name in ItemRecommender.SUPPORT_ONLY:
            return False
        if item_name in ItemRecommender.COMPONENT_ITEMS:
            return False
        return True

    # ═══════════════════════════════════════════════════════════════
    # Hero name resolution
    # ═══════════════════════════════════════════════════════════════

    def _get_hero_display_name(self, hero_name: str) -> str:
        """Get proper display name (e.g., 'nevermore' -> 'Shadow Fiend')."""
        if hero_name in self._hero_display_names:
            return self._hero_display_names[hero_name]
        # Try valve name
        valve = self._internal_to_valve.get(hero_name, hero_name)
        if valve in self._hero_display_names:
            return self._hero_display_names[valve]
        return hero_name.replace("_", " ").title()

    def _normalize_hero_name(self, hero_name: str) -> str:
        """Normalize aliases/Valve IDs to internal hero IDs."""
        hero_id = self.mapper.hero_name_to_id(str(hero_name or ""))
        normalized = self.mapper.hero_id_to_name(hero_id)
        if normalized.startswith("unknown"):
            return str(hero_name or "")
        return normalized

    def _normalize_hero_list(self, hero_names: list[str], limit: int,
                             exclude: Optional[set[str]] = None) -> list[str]:
        """Normalize heroes, remove duplicates/excluded IDs, and cap length."""
        excluded = {self._normalize_hero_name(h) for h in (exclude or set())}
        seen = set()
        normalized = []
        for hero in hero_names:
            hero_norm = self._normalize_hero_name(hero)
            if not hero_norm or hero_norm in excluded or hero_norm in seen:
                continue
            seen.add(hero_norm)
            normalized.append(hero_norm)
            if len(normalized) >= limit:
                break
        return normalized

    def _resolve_stats_name(self, hero_name: str) -> Optional[str]:
        """Find the hero's key in hero_item_stats.json.

        Tries: internal name, valve name, and normalized forms.
        """
        # Direct match
        if hero_name in self._hero_stats:
            return hero_name
        # Try valve → internal
        internal = self._valve_to_internal.get(hero_name, "")
        if internal and internal in self._hero_stats:
            return internal
        # Try internal → valve
        valve = self._internal_to_valve.get(hero_name, "")
        if valve and valve in self._hero_stats:
            return valve
        # Try normalized
        normalized = self._normalize_hero_name(hero_name)
        if normalized in self._hero_stats:
            return normalized
        # Try normalized valve
        norm_valve = self._internal_to_valve.get(normalized, "")
        if norm_valve and norm_valve in self._hero_stats:
            return norm_valve
        return None

    def _is_valid_phase_item(self, item_name: str, phase: str) -> bool:
        """Phase-aware validation (filters components/support/cheap items)."""
        if not self._is_valid_item(item_name):
            return False
        if item_name in ItemRecommender.SUPPORT_ONLY:
            return False
        if phase in ("mid", "late") and item_name in ItemRecommender.COMPONENT_ITEMS:
            return False
        return True

    def _merge_with_fallback(self, selected: list[dict],
                             fallback: list[dict]) -> tuple[list[dict], int]:
        """Backfill AI-selected items with fallback list up to 6 entries."""
        merged = [dict(item) for item in selected]
        ai_count = len(merged)
        used = {item.get("item", "") for item in merged if item.get("item")}
        for entry in fallback:
            item_name = entry.get("item", "")
            if not item_name or item_name in used:
                continue
            merged.append({
                "item": item_name,
                "score": float(entry.get("score", 0.1)),
                "note": entry.get("note", "fallback"),
            })
            used.add(item_name)
            if len(merged) >= 6:
                break
        return merged[:6], ai_count

    # ═══════════════════════════════════════════════════════════════
    # Main recommendation entry point
    # ═══════════════════════════════════════════════════════════════

    def recommend(self, my_hero: str, enemies: list[str], allies: list[str],
                  all_player_items: Optional[dict] = None,
                  game_time: int = 0,
                  my_items: Optional[list[str]] = None,
                  rule_based_rec: Optional[dict] = None) -> Optional[dict]:
        """Generate AI-powered item recommendation.

        Strategy:
        1. If hero stats exist → stats-first approach (primary)
        2. If only XGBoost models → XGBoost-only approach (fallback)
        3. If neither → return None

        Returns:
            Dict with early_game, mid_game, late_game item lists + confidence,
            or None if AI is not available.
        """
        if not self._available:
            return None

        # Try stats-first approach
        stats_name = self._resolve_stats_name(my_hero)
        if stats_name and self._hero_stats.get(stats_name):
            return self._recommend_stats_first(
                stats_name=stats_name,
                my_hero=my_hero,
                enemies=enemies,
                allies=allies,
                all_player_items=all_player_items,
                game_time=game_time,
                my_items=my_items,
                rule_based_rec=rule_based_rec,
            )

        # Fallback to XGBoost-only
        if self._embedder and self._xgb_models:
            return self._recommend_xgb_only(
                my_hero=my_hero,
                enemies=enemies,
                allies=allies,
                all_player_items=all_player_items,
                game_time=game_time,
                my_items=my_items,
                rule_based_rec=rule_based_rec,
            )

        return None

    # ═══════════════════════════════════════════════════════════════
    # Stats-first recommendation (PRIMARY approach)
    # ═══════════════════════════════════════════════════════════════

    def _recommend_stats_first(self, stats_name: str, my_hero: str,
                               enemies: list[str], allies: list[str],
                               all_player_items: Optional[dict],
                               game_time: int, my_items: Optional[list[str]],
                               rule_based_rec: Optional[dict]) -> dict:
        """Build recommendation from hero statistics + matchup adjustment.

        Phase assignment uses purchase-log timing data cross-referenced with
        final inventory items. This naturally assigns items to the phase when
        they are typically purchased (e.g., PA's Battle Fury goes in 'early'
        even though it costs 4100g because PA rushes it before 15 minutes).
        """
        hero_data = self._hero_stats[stats_name]
        total_games = hero_data.get("games", 0)

        # ── Step 1: Build the valid final-item pool with scores ──
        # Only include items with >= 2% build rate (skip niche/cheese builds)
        MIN_BUILD_RATE = 0.02
        final_item_scores = {}
        for entry in hero_data.get("final_items", []):
            name = entry["item"]
            if not self._is_recommendable_item(name):
                continue
            if entry["rate"] < MIN_BUILD_RATE:
                continue
            cost = self._items.get(name, {}).get("cost", 0)
            # Score = popularity × effectiveness (items that are both common AND winning)
            score = entry["rate"] * entry["win_rate"]
            final_item_scores[name] = {
                "score": score,
                "rate": entry["rate"],
                "win_rate": entry["win_rate"],
                "cost": cost,
            }

        # ── Step 2: Build purchase-phase membership ──
        # Which final-build items are typically purchased in each phase?
        # Require >= 3% purchase rate in that phase to count as a meaningful
        # assignment (avoids e.g. 0.9% early Desolator on PA polluting early).
        MIN_PHASE_RATE = 0.03
        phase_membership = {"early": set(), "mid": set(), "late": set()}
        for phase_key in ["early", "mid", "late"]:
            for entry in hero_data.get(phase_key, []):
                name = entry["item"]
                if name in final_item_scores and entry["rate"] >= MIN_PHASE_RATE:
                    phase_membership[phase_key].add(name)

        # Items not assigned to any phase by purchase data → use cost tiers
        assigned = phase_membership["early"] | phase_membership["mid"] | phase_membership["late"]
        for name, data in final_item_scores.items():
            if name in assigned:
                continue
            cost = data["cost"]
            if name in ItemRecommender.BOOT_IDS:
                phase_membership["early"].add(name)
            elif cost < 2800:
                phase_membership["early"].add(name)
            elif cost < 5000:
                phase_membership["mid"].add(name)
            else:
                phase_membership["late"].add(name)

        # ── Step 3: XGBoost matchup adjustment ──
        if enemies and self._embedder and self._xgb_models:
            xgb_boosts = self._compute_xgb_boosts(
                my_hero, enemies, allies, all_player_items,
                game_time, my_items,
            )
            for name in final_item_scores:
                if name in xgb_boosts:
                    # Adjust score by up to ±40% based on matchup
                    adj = max(-0.4, min(0.4, xgb_boosts[name]))
                    final_item_scores[name]["score"] *= (1.0 + adj)

        # ── Step 4: Select items per phase ──
        owned = set(my_items or [])
        used = set()

        early = self._pick_phase_items("early", phase_membership["early"],
                                       final_item_scores, owned, used, rule_based_rec)
        mid = self._pick_phase_items("mid", phase_membership["mid"],
                                     final_item_scores, owned, used, rule_based_rec)
        late = self._pick_phase_items("late", phase_membership["late"],
                                      final_item_scores, owned, used, rule_based_rec)

        # ── Step 5: Calculate confidence ──
        confidence = self._calc_stats_confidence(total_games, final_item_scores,
                                                 bool(enemies))

        return {
            "hero": my_hero,
            "hero_name": self._get_hero_display_name(my_hero),
            "source": "ai",
            "confidence": confidence,
            "early_game": early,
            "mid_game": mid,
            "late_game": late,
        }

    def _pick_phase_items(self, phase: str, phase_items: set,
                          all_scores: dict, owned: set, used: set,
                          rule_based_rec: Optional[dict]) -> list[dict]:
        """Pick up to 6 items for a game phase.

        Prioritizes items that belong to this phase (from purchase timing data),
        then fills gaps from remaining high-score items.
        """
        items = []

        # ── Boots handling (early game gets boots first) ──
        if phase == "early":
            boot_candidates = []
            for name in phase_items:
                if name in ItemRecommender.BOOT_IDS and name not in owned and name not in used:
                    data = all_scores.get(name)
                    if data:
                        boot_candidates.append((name, data["score"], data))
            # Also check all_scores for boots not in phase_items
            if not boot_candidates:
                for name, data in all_scores.items():
                    if name in ItemRecommender.BOOT_IDS and name not in owned and name not in used:
                        boot_candidates.append((name, data["score"], data))
            boot_candidates.sort(key=lambda x: x[1], reverse=True)
            if boot_candidates:
                bname, bscore, bdata = boot_candidates[0]
                items.append(self._make_phase_item(bname, bscore,
                    note=f"{bdata['rate']:.0%} build rate"))
                used.add(bname)
            elif "power_treads" not in owned and "power_treads" not in used:
                items.append(self._make_phase_item("power_treads", 0.3,
                    note="Standard boots"))
                used.add("power_treads")

        # ── Collect phase candidates (items assigned to this phase) ──
        candidates = []
        for name in phase_items:
            if name in owned or name in used or name in ItemRecommender.BOOT_IDS:
                continue
            data = all_scores.get(name)
            if data:
                candidates.append((name, data["score"], data))
        candidates.sort(key=lambda x: x[1], reverse=True)

        # ── Add top candidates ──
        for name, score, data in candidates:
            if len(items) >= 6:
                break
            rate_str = f"{data['rate']:.0%} pick"
            wr_str = f"{data['win_rate']:.0%} WR"
            items.append(self._make_phase_item(name, score,
                note=f"{rate_str}, {wr_str}"))
            used.add(name)

        # ── Fill gaps: pull from remaining high-score items not yet assigned ──
        if len(items) < 3:
            remaining = []
            for name, data in sorted(all_scores.items(),
                                     key=lambda x: x[1]["score"], reverse=True):
                if name in used or name in owned or name in ItemRecommender.BOOT_IDS:
                    continue
                cost = data["cost"]
                # Enforce reasonable cost ranges per phase
                if phase == "early" and cost > 4500:
                    continue  # Don't pull luxury items into early
                if phase == "mid" and cost < 2000:
                    continue
                if phase == "late" and cost < 3500:
                    continue
                remaining.append((name, data["score"], data))

            for name, score, data in remaining:
                if len(items) >= 6:
                    break
                items.append(self._make_phase_item(name, score,
                    note=f"{data['rate']:.0%} pick, {data['win_rate']:.0%} WR"))
                used.add(name)

        # ── Last resort: rule-based fallback ──
        if len(items) < 3 and rule_based_rec:
            phase_name = {"early": "early_game", "mid": "mid_game",
                          "late": "late_game"}[phase]
            for entry in rule_based_rec.get(phase_name, []):
                if len(items) >= 6:
                    break
                item_name = entry.get("item", "")
                if item_name and item_name not in used and item_name not in owned:
                    if self._is_recommendable_item(item_name):
                        items.append(self._make_phase_item(item_name, 0.1,
                            note=entry.get("note", "fallback")))
                        used.add(item_name)

        return items[:6]

    def _compute_xgb_boosts(self, my_hero: str, enemies: list[str],
                            allies: list[str],
                            all_player_items: Optional[dict],
                            game_time: int,
                            my_items: Optional[list[str]]) -> dict[str, float]:
        """Use XGBoost to compute per-item matchup score adjustments.

        Returns a dict of item_name → relative_boost where positive values
        mean the item is stronger in this matchup than average.
        """
        my_id = self.mapper.hero_name_to_id(my_hero)
        ally_ids = [self.mapper.hero_name_to_id(h) for h in allies[:4]]
        enemy_ids = [self.mapper.hero_name_to_id(h) for h in enemies[:5]]
        while len(ally_ids) < 4:
            ally_ids.append(0)
        while len(enemy_ids) < 5:
            enemy_ids.append(0)

        hero_ids = torch.tensor([[my_id] + ally_ids + enemy_ids], dtype=torch.long)

        with torch.no_grad():
            if all_player_items and game_time > 0:
                player_items_tensor, my_items_tensor = self._encode_player_items(
                    all_player_items, my_hero, my_items=my_items
                )
                time_oh = self._time_onehot(game_time)
                embedding = self._embedder.encode_live(
                    hero_ids, player_items_tensor, my_items_tensor, time_oh
                ).numpy()
            else:
                embedding = self._embedder.encode_draft(hero_ids).numpy()
                embedding = np.pad(embedding, ((0, 0), (0, 128)))

        # Pick the best XGBoost model for current game time
        if game_time > 1800 and "late" in self._xgb_models:
            model_key = "late"
        elif game_time > 900 and "mid" in self._xgb_models:
            model_key = "mid"
        elif "early" in self._xgb_models:
            model_key = "early"
        elif "draft" in self._xgb_models:
            model_key = "draft"
        else:
            return {}

        model_data = self._xgb_models[model_key]
        multi_model = model_data["model"]
        top_indices = model_data["top_item_indices"]

        pred_probs = multi_model.predict_proba(embedding)
        scores = np.array([p[0][1] if len(p[0]) > 1 else 0.0 for p in pred_probs])

        # Convert raw probabilities to relative boosts
        mean_score = float(np.mean(scores)) if len(scores) > 0 else 0.01
        boosts = {}
        for idx, score in enumerate(scores):
            if idx < len(top_indices):
                item_id = top_indices[idx]
                item_name = self.mapper.item_id_to_name(item_id)
                if item_name and not item_name.startswith("unknown"):
                    if mean_score > 0.001:
                        # Relative strength vs average: +0.5 means 50% above average
                        boosts[item_name] = (float(score) - mean_score) / mean_score
                    else:
                        boosts[item_name] = 0.0

        return boosts

    def _calc_stats_confidence(self, total_games: int,
                               item_scores: dict,
                               has_enemies: bool) -> float:
        """Calculate confidence based on data quality.

        Factors:
        - Sample size (more games → more reliable stats)
        - Build clarity (if top items dominate → clearer recommendation)
        - Matchup info available (enemies known → matchup-adjusted)
        """
        # Factor 1: Sample size
        if total_games >= 5000:
            size_conf = 0.90
        elif total_games >= 2000:
            size_conf = 0.80
        elif total_games >= 500:
            size_conf = 0.65
        elif total_games >= 100:
            size_conf = 0.50
        else:
            size_conf = 0.30

        # Factor 2: Build clarity (how much the top items dominate)
        if item_scores:
            top_rates = sorted([d["rate"] for d in item_scores.values()],
                               reverse=True)[:3]
            avg_top_rate = sum(top_rates) / len(top_rates) if top_rates else 0
            # Rate 0.7+ → very clear build, 0.3 → moderate
            clarity_conf = min(0.95, avg_top_rate * 1.3)
        else:
            clarity_conf = 0.25

        # Factor 3: Matchup intelligence
        enemy_bonus = 0.05 if has_enemies else 0.0

        # Combined
        confidence = (size_conf * 0.45 + clarity_conf * 0.45) + enemy_bonus
        return min(0.95, max(0.20, confidence))

    # ═══════════════════════════════════════════════════════════════
    # XGBoost-only recommendation (FALLBACK for heroes not in stats)
    # ═══════════════════════════════════════════════════════════════

    def _recommend_xgb_only(self, my_hero: str, enemies: list[str],
                            allies: list[str],
                            all_player_items: Optional[dict],
                            game_time: int, my_items: Optional[list[str]],
                            rule_based_rec: Optional[dict]) -> Optional[dict]:
        """Fallback: Pure XGBoost prediction when no hero stats available."""
        my_id = self.mapper.hero_name_to_id(my_hero)
        ally_ids = [self.mapper.hero_name_to_id(h) for h in allies[:4]]
        enemy_ids = [self.mapper.hero_name_to_id(h) for h in enemies[:5]]
        while len(ally_ids) < 4:
            ally_ids.append(0)
        while len(enemy_ids) < 5:
            enemy_ids.append(0)

        hero_ids = torch.tensor([[my_id] + ally_ids + enemy_ids], dtype=torch.long)

        with torch.no_grad():
            if all_player_items and game_time > 0:
                player_items_tensor, my_items_tensor = self._encode_player_items(
                    all_player_items, my_hero, my_items=my_items
                )
                time_oh = self._time_onehot(game_time)
                embedding = self._embedder.encode_live(
                    hero_ids, player_items_tensor, my_items_tensor, time_oh
                ).numpy()
            else:
                embedding = self._embedder.encode_draft(hero_ids).numpy()
                embedding = np.pad(embedding, ((0, 0), (0, 128)))

        result = {
            "hero": my_hero,
            "hero_name": self._get_hero_display_name(my_hero),
            "source": "ai",
            "confidence": 0.0,
        }
        owned_items = set(my_items or [])
        used_items = set()

        for phase_name, phase_key in [("early_game", "early"),
                                       ("mid_game", "mid"),
                                       ("late_game", "late")]:
            xgb_key = phase_key if phase_key in self._xgb_models else "draft"
            if xgb_key not in self._xgb_models:
                result[phase_name] = self._xgb_fallback_phase(
                    phase_name, rule_based_rec, owned_items, used_items
                )
                continue

            model_data = self._xgb_models[xgb_key]
            multi_model = model_data["model"]
            top_indices = model_data["top_item_indices"]

            pred_probs = multi_model.predict_proba(embedding)
            scores = np.array([p[0][1] if len(p[0]) > 1 else 0.0
                               for p in pred_probs])

            item_scores = []
            for idx, score in enumerate(scores):
                if idx < len(top_indices):
                    item_id = top_indices[idx]
                    item_name = self.mapper.item_id_to_name(item_id)
                    if (self._is_recommendable_item(item_name)
                            and item_name not in owned_items):
                        item_scores.append((item_name, float(score)))

            # Blend with rule-based
            combined = {}
            for name, score in item_scores:
                if name not in owned_items:
                    combined[name] = max(combined.get(name, 0.0), score)

            if rule_based_rec:
                bonuses = [0.20, 0.16, 0.13, 0.10, 0.08, 0.06]
                for idx, entry in enumerate(rule_based_rec.get(phase_name, [])[:6]):
                    name = entry.get("item", "")
                    if name and name not in owned_items and self._is_recommendable_item(name):
                        combined[name] = combined.get(name, 0.0) + bonuses[min(idx, 5)]

            ranked = sorted(combined.items(), key=lambda x: x[1], reverse=True)
            top_items = []
            for name, score in ranked:
                if name in used_items:
                    continue
                top_items.append(self._make_phase_item(name, score))
                used_items.add(name)
                if len(top_items) >= 6:
                    break

            # Ensure boots in early
            if phase_name == "early_game" and not any(
                    i["item"] in ItemRecommender.BOOT_IDS for i in top_items):
                if "power_treads" not in owned_items:
                    top_items.insert(0, self._make_phase_item("power_treads", 0.2,
                                                              note="Standard boots"))
                    used_items.add("power_treads")
                    top_items = top_items[:6]

            result[phase_name] = top_items

            if top_items:
                raw = float(np.mean([t["score"] for t in top_items[:3]]))
                scaled = min(0.95, raw * 3.5 + 0.12) if raw > 0.02 else raw
                result["confidence"] = max(result["confidence"], scaled)

        return result

    def _xgb_fallback_phase(self, phase_name: str, rule_based_rec: Optional[dict],
                            owned: set, used: set) -> list[dict]:
        """Use rule-based items when XGBoost model unavailable for a phase."""
        if not rule_based_rec:
            return []
        items = []
        for entry in rule_based_rec.get(phase_name, []):
            name = entry.get("item", "")
            if name and name not in owned and name not in used:
                items.append(self._make_phase_item(name, 0.1,
                             note=entry.get("note", "")))
                used.add(name)
                if len(items) >= 6:
                    break
        return items

    # ═══════════════════════════════════════════════════════════════
    # Hero recommendation (draft phase)
    # ═══════════════════════════════════════════════════════════════

    def recommend_hero(self, allies_so_far: list[str],
                       enemies_so_far: list[str]) -> Optional[list[dict]]:
        """Recommend heroes to pick during draft phase.

        Returns top 5 hero suggestions with win probability scores.
        """
        if not self._embedder or "draft" not in self._xgb_models:
            return None

        ally_ids = [self.mapper.hero_name_to_id(h) for h in allies_so_far[:4]]
        enemy_ids = [self.mapper.hero_name_to_id(h) for h in enemies_so_far[:5]]
        while len(ally_ids) < 4:
            ally_ids.append(0)
        while len(enemy_ids) < 5:
            enemy_ids.append(0)

        picked = set(ally_ids + enemy_ids) - {0}
        candidates = []

        for hero_id in range(1, self.mapper.max_hero_id + 1):
            if hero_id in picked:
                continue
            hero_name = self.mapper.hero_id_to_name(hero_id)
            if hero_name.startswith("unknown"):
                continue

            hero_ids = torch.tensor([[hero_id] + ally_ids + enemy_ids],
                                    dtype=torch.long)
            with torch.no_grad():
                draft_embed = self._embedder.encode_draft(hero_ids).numpy()
                draft_embed = np.pad(draft_embed, ((0, 0), (0, 128)))

            model_data = self._xgb_models["draft"]
            pred = model_data["model"].predict_proba(draft_embed)
            avg_score = np.mean([p[0][1] if len(p[0]) > 1 else 0.0
                                 for p in pred])

            candidates.append({
                "hero": hero_name,
                "hero_name": self._get_hero_display_name(hero_name),
                "score": float(avg_score),
            })

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:5]

    # ═══════════════════════════════════════════════════════════════
    # Shared utilities
    # ═══════════════════════════════════════════════════════════════

    def _encode_player_items(self, all_player_items: dict, my_hero: str,
                             my_items: Optional[list[str]] = None):
        """Encode all players' items into tensors for embedding model."""
        player_items = torch.zeros(1, 10, 6, dtype=torch.long)
        my_items_tensor = torch.zeros(1, 6, dtype=torch.long)

        allies = all_player_items.get("allies", [])
        enemies = all_player_items.get("enemies", [])

        for pi, player in enumerate(allies[:5]):
            for si, item_name in enumerate(player.get("items", [])[:6]):
                item_id = self.mapper.item_name_to_id(item_name)
                player_items[0, pi, si] = item_id
                if player.get("hero") == my_hero:
                    my_items_tensor[0, si] = item_id

        for pi, player in enumerate(enemies[:5]):
            for si, item_name in enumerate(player.get("items", [])[:6]):
                item_id = self.mapper.item_name_to_id(item_name)
                player_items[0, 5 + pi, si] = item_id

        if not my_items_tensor.any() and my_items:
            for si, item_name in enumerate(my_items[:6]):
                my_items_tensor[0, si] = self.mapper.item_name_to_id(item_name)

        return player_items, my_items_tensor

    def _make_phase_item(self, item_name: str, score: float,
                         note: str = "") -> dict:
        """Create a phase item dict for the overlay."""
        display = self._items.get(item_name, {}).get(
            "name", item_name.replace("_", " ").title()
        )
        phase_note = note or f"AI score {score:.0%}"
        return {
            "item": item_name,
            "score": float(score),
            "name": display,
            "note": phase_note,
        }

    def _time_onehot(self, game_time: int) -> torch.Tensor:
        """Convert game time to one-hot [early, mid, late]."""
        t = torch.zeros(1, 3)
        if game_time < 900:
            t[0, 0] = 1.0
        elif game_time < 1800:
            t[0, 1] = 1.0
        else:
            t[0, 2] = 1.0
        return t
