"""Dota 2 Build Generator - Desktop App with Live Overlay

Two modes:
1. Browse Builds — manually select heroes and view static builds
2. Live Overlay — GSI auto-detects your match and recommends items dynamically
"""
import customtkinter as ctk
import faulthandler
import json
import queue
import sys
import threading
import time
import traceback
from pathlib import Path
from logic.data_loader import DataLoader
from logic.gsi_server import GSIServer
from logic.gsi_parser import GSIParser
from logic.gsi_installer import install_gsi_config, is_gsi_installed, is_gsi_outdated, find_dota2_path
from logic.item_recommender import ItemRecommender
from logic.item_threat_analyzer import ItemThreatAnalyzer
from logic.ai_recommender import AIRecommender
from logic.match_lookup import MatchLookup
from ui.hero_select import HeroSelectFrame
from ui.build_view import BuildViewFrame
from ui.overlay import OverlayWindow


class HomeScreen(ctk.CTkFrame):
    """Home screen with mode selection."""

    def __init__(self, master, on_browse, on_overlay, gsi_installed: bool, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(fg_color="transparent")

        # Title
        ctk.CTkLabel(self, text="DOTA 2 BUILD GENERATOR",
                     font=("Segoe UI", 32, "bold"), text_color="#e94560").pack(pady=(80, 10))
        ctk.CTkLabel(self, text="Smart item recommendations powered by draft analysis",
                     font=("Segoe UI", 14), text_color="#888").pack(pady=(0, 50))

        # Mode buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack()

        # Browse builds button
        browse_frame = ctk.CTkFrame(btn_frame, fg_color="#0f0f23", corner_radius=12,
                                    border_width=2, border_color="#2a2a4a")
        browse_frame.pack(side="left", padx=20)

        ctk.CTkLabel(browse_frame, text="BROWSE BUILDS",
                     font=("Segoe UI", 18, "bold"), text_color="#e94560").pack(padx=30, pady=(20, 5))
        ctk.CTkLabel(browse_frame, text="Manually select heroes\nand view item builds",
                     font=("Segoe UI", 11), text_color="#888").pack(padx=30, pady=(0, 10))
        ctk.CTkButton(browse_frame, text="Open Browser", width=200, height=40,
                      font=("Segoe UI", 13, "bold"),
                      fg_color="#2a2a4a", hover_color="#e94560",
                      command=on_browse).pack(padx=30, pady=(5, 20))

        # Live overlay button
        overlay_frame = ctk.CTkFrame(btn_frame, fg_color="#0f0f23", corner_radius=12,
                                     border_width=2, border_color="#e94560")
        overlay_frame.pack(side="left", padx=20)

        ctk.CTkLabel(overlay_frame, text="LIVE OVERLAY",
                     font=("Segoe UI", 18, "bold"), text_color="#e94560").pack(padx=30, pady=(20, 5))
        ctk.CTkLabel(overlay_frame, text="Auto-detect draft via GSI\nand get smart item advice",
                     font=("Segoe UI", 11), text_color="#888").pack(padx=30, pady=(0, 10))
        ctk.CTkButton(overlay_frame, text="Start Overlay", width=200, height=40,
                      font=("Segoe UI", 13, "bold"),
                      fg_color="#e94560", hover_color="#c81e45",
                      command=on_overlay).pack(padx=30, pady=(5, 20))

        # GSI status
        gsi_status = "GSI Config: Installed" if gsi_installed else "GSI Config: Not installed (will prompt)"
        gsi_color = "#4CAF50" if gsi_installed else "#FF9800"
        ctk.CTkLabel(self, text=gsi_status, font=("Segoe UI", 10),
                     text_color=gsi_color).pack(pady=(30, 5))

        ctk.CTkLabel(self, text="Alt+D toggles overlay visibility during game",
                     font=("Segoe UI", 10), text_color="#555").pack(pady=(0, 10))


class DotaBuildApp(ctk.CTk):
    """Main application window with screen navigation and GSI integration."""

    def __init__(self):
        super().__init__()
        self.report_callback_exception = self._report_tk_callback_exception
        self.title("Dota 2 Build Generator")
        self.geometry("1200x800")
        self.minsize(1000, 700)
        self.configure(fg_color="#0a0a1a")

        # Center window on screen
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 1200) // 2
        y = (self.winfo_screenheight() - 800) // 2
        self.geometry(f"1200x800+{x}+{y}")

        # Load data
        self.base_dir = Path(__file__).parent
        self.assets_dir = self.base_dir / "assets"
        self.data_dir = str(self.base_dir / "data")
        self.loader = DataLoader(self.data_dir)

        hero_count = len(self.loader.get_all_heroes())
        item_count = len(self.loader.get_all_items())
        print(f"[App] Loaded {hero_count} heroes and {item_count} items")

        # GSI components
        self.gsi_server = GSIServer(port=4001, on_update=self._on_gsi_update)
        self.gsi_parser = GSIParser(self.data_dir)
        self.recommender = ItemRecommender(self.data_dir)
        self.ai_recommender = AIRecommender(self.data_dir)
        if self.ai_recommender.is_available:
            print("[App] AI recommendation system loaded")
        else:
            print("[App] AI models not found -- using rule-based recommendations")
            print(f"[App] AI fallback reason: {self.ai_recommender.availability_reason}")
        self.match_lookup = MatchLookup(self.data_dir)
        self.item_threat_analyzer = ItemThreatAnalyzer(self.data_dir)
        self._ui_queue = queue.Queue()
        self.overlay = None
        self._hotkey_listener = None
        self.selected_role = None
        self._last_recommendation = None
        self._last_recommendation_signature = None
        self._last_overlay_items_signature = None
        self._last_enemies = []
        self._last_hero = None
        self._draft_cache = {}  # Cache draft picks during hero selection
        self._api_lookup_in_progress = False
        self._api_lookup_cooldown_until = 0  # Timestamp: don't retry API before this time
        self._last_player_items_update = 0  # Throttle player items to every 5 seconds

        # Start GSI server immediately (background, no harm if no game running)
        try:
            self.gsi_server.start()
        except Exception as e:
            print(f"[App] GSI server failed to start: {e}")

        # Register global hotkey (Alt+D)
        self._setup_hotkey()

        self.current_frame = None
        self._show_home()
        self.after(50, self._drain_ui_queue)

        # Cleanup on close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_hotkey(self):
        """Register Alt+D global hotkey to toggle overlay."""
        try:
            from pynput import keyboard

            def on_hotkey():
                if self.overlay:
                    self._enqueue_ui_call(self.overlay.toggle)

            hotkey = keyboard.HotKey(
                keyboard.HotKey.parse("<alt>+d"),
                on_hotkey,
            )

            # Follow pynput's recommended pattern using the listener's
            # canonical() method to normalize keys on Windows.
            def on_press(key):
                hotkey.press(listener.canonical(key))

            def on_release(key):
                hotkey.release(listener.canonical(key))

            listener = keyboard.Listener(
                on_press=on_press,
                on_release=on_release,
            )
            listener.daemon = True
            listener.start()
            self._hotkey_listener = listener
            print("[App] Global hotkey Alt+D registered")

        except ImportError:
            print("[App] pynput not installed -- hotkey disabled. Install with: pip install pynput")
        except Exception as e:
            print(f"[App] Hotkey setup failed: {e}")

    @staticmethod
    def _listener_canonical(key):
        """Convert key to canonical form for HotKey."""
        from pynput import keyboard
        try:
            return keyboard.KeyCode.from_char(key.char)
        except AttributeError:
            return key

    @staticmethod
    def _normalize_hero_list(hero_ids: list[str]) -> list[str]:
        """Normalize hero lists so ordering noise doesn't trigger refreshes."""
        return sorted({hero_id for hero_id in hero_ids if hero_id})

    @staticmethod
    def _recommendation_time_bucket(game_time: int) -> int:
        """Bucket time so recommendations only refresh on meaningful progression."""
        if game_time <= 0:
            return 0
        return game_time // 300

    def _build_recommendation_signature(self, my_hero: str, allies: list[str],
                                        enemies: list[str], my_items: list[str],
                                        game_time: int, role: str | None) -> tuple:
        """Create a stable signature for recommendation refresh decisions."""
        return (
            my_hero,
            role or "",
            tuple(allies),
            tuple(enemies),
            tuple(sorted(my_items)),
            self._recommendation_time_bucket(game_time),
        )

    @staticmethod
    def _should_use_ai_items(ai_rec: dict, phase: str,
                             has_allplayers: bool,
                             my_items: list[str],
                             selected_role: str | None) -> tuple[bool, str]:
        """Gate AI item builds to contexts where they are reliable enough."""
        if not ai_rec:
            return False, "AI unavailable"
        if selected_role:
            return False, "role-aware rule engine active"
        if phase != "in_game":
            return False, "draft-phase item AI disabled"

        confidence = float(ai_rec.get("confidence", 0) or 0)
        if has_allplayers:
            return confidence >= 0.45, f"low AI confidence ({confidence:.0%})"
        if my_items:
            return confidence >= 0.65, f"low AI confidence ({confidence:.0%})"
        return False, "no live item context"

    def _set_selected_role(self, role_code: str):
        self.selected_role = role_code
        self._last_recommendation = None
        self._last_recommendation_signature = None
        self._last_overlay_items_signature = None
        if hasattr(self, "_role_value_label"):
            label = self.recommender.ROLE_CONFIGS[role_code]["label"]
            self._role_value_label.configure(text=label)
        if self.overlay:
            self._enqueue_ui_call(lambda: self.overlay.set_waiting("Waiting for match..."))

    def _prompt_role_selection(self, on_selected=None):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Select Role")
        dialog.geometry("520x360")
        dialog.attributes("-topmost", True)
        dialog.configure(fg_color="#0a0a1a")
        dialog.transient(self)
        dialog.grab_set()

        dialog.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 520) // 2
        y = self.winfo_y() + (self.winfo_height() - 360) // 2
        dialog.geometry(f"520x360+{x}+{y}")

        ctk.CTkLabel(dialog, text="SELECT YOUR ROLE",
                     font=("Segoe UI", 18, "bold"), text_color="#e94560").pack(pady=(18, 8))
        ctk.CTkLabel(
            dialog,
            text="Role is required before the app generates any item build.",
            font=("Segoe UI", 11),
            text_color="#aaa"
        ).pack(pady=(0, 12))

        selected = ctk.StringVar(value=self.selected_role or "")
        body = ctk.CTkFrame(dialog, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20)

        for role_code, config in self.recommender.ROLE_CONFIGS.items():
            row = ctk.CTkFrame(body, fg_color="#0f0f23", corner_radius=8,
                               border_width=1, border_color="#2a2a4a")
            row.pack(fill="x", pady=4)
            ctk.CTkRadioButton(
                row,
                text=config["label"],
                variable=selected,
                value=role_code,
                font=("Segoe UI", 12, "bold"),
                text_color="#ddd",
                fg_color="#e94560",
                hover_color="#c81e45",
            ).pack(anchor="w", padx=12, pady=(8, 2))
            ctk.CTkLabel(
                row,
                text=f"{config['priority']} | {config['budget']}",
                font=("Segoe UI", 10),
                text_color="#888",
            ).pack(anchor="w", padx=36, pady=(0, 8))

        def confirm():
            role_code = selected.get().strip()
            if not role_code:
                return
            self._set_selected_role(role_code)
            dialog.destroy()
            if on_selected:
                on_selected()

        footer = ctk.CTkFrame(dialog, fg_color="transparent")
        footer.pack(pady=(4, 16))
        ctk.CTkButton(footer, text="Confirm Role", width=140,
                      fg_color="#e94560", hover_color="#c81e45",
                      command=confirm).pack(side="left", padx=8)
        ctk.CTkButton(footer, text="Cancel", width=120,
                      fg_color="#2a2a4a", hover_color="#444",
                      command=dialog.destroy).pack(side="left", padx=8)

    @staticmethod
    def _merge_ai_recommendation(ai_rec: dict, rule_rec: dict) -> dict:
        """Keep AI item picks but preserve rule-based explanations and analysis."""
        merged = dict(rule_rec)
        merged.update(ai_rec)
        for key in ("threats", "team_analysis", "matchup_context", "reasoning"):
            merged[key] = rule_rec.get(key, merged.get(key))
        return merged

    def _enqueue_ui_call(self, callback):
        """Queue UI work so Tk is only touched from the main thread."""
        self._ui_queue.put(callback)

    def _drain_ui_queue(self):
        """Run queued UI callbacks on the Tk main thread."""
        try:
            while True:
                callback = self._ui_queue.get_nowait()
                try:
                    callback()
                except Exception as e:
                    print(f"[UI] Callback error: {e}")
                    traceback.print_exc()
        except queue.Empty:
            pass

        try:
            if self.winfo_exists():
                self.after(50, self._drain_ui_queue)
        except Exception:
            pass

    @staticmethod
    def _report_tk_callback_exception(exc_type, exc_value, exc_traceback):
        """Surface Tk callback exceptions instead of failing silently."""
        print(f"[UI] Tk callback error: {exc_value}")
        traceback.print_exception(exc_type, exc_value, exc_traceback)

    def _on_gsi_update(self, gsi_data: dict):
        """Called when GSI server receives new data (runs in server thread).

        Data source priority for enemy/ally heroes:
        1. GSI draft block (available during hero selection only)
        2. Cached draft from earlier hero selection phase
        3. OpenDota API match lookup (using player's account ID)
        4. Hero-only mode (show popular builds without draft context)
        """
        try:
            state = self.gsi_parser.parse(gsi_data)
            phase = state.get("phase", "unknown")
            my_hero = state.get("my_hero")
            my_team = state.get("my_team")
            valve_hero = state.get("my_hero_valve", my_hero)
            my_items = state.get("my_items", [])
            update_num = self.gsi_server.update_count
            # Whether this payload includes full allplayers data (for live item tracking / AI)
            has_allplayers = "allplayers" in gsi_data and isinstance(gsi_data["allplayers"], dict)

            # Debug logging
            if update_num <= 3 or update_num % 100 == 0:
                map_data = gsi_data.get("map", {})
                match_id = map_data.get("matchid", "?")
                draft_raw = gsi_data.get("draft", {})
                draft_keys = list(draft_raw.keys()) if isinstance(draft_raw, dict) else str(type(draft_raw))
                print(
                    f"[GSI] #{update_num} phase={phase} hero={my_hero} "
                    f"team={my_team} match_id={match_id} "
                    f"draft_keys={draft_keys}"
                )

            if phase == "post_game":
                self._draft_cache = {}
                self._last_enemies = []
                self._last_hero = None
                self._last_recommendation = None
                self._last_recommendation_signature = None
                self._last_overlay_items_signature = None
                self._api_lookup_cooldown_until = 0
                self._last_player_items_update = 0
                self.match_lookup.invalidate_cache()
                self._enqueue_ui_call(lambda: self.overlay.set_waiting() if self.overlay else None)
                return

            if not my_hero:
                # ═══ AI hero suggestions during draft (before hero is picked) ═══
                if phase in ("hero_selection", "strategy") and self.ai_recommender.is_available:
                    allies_draft, enemies_draft = self.gsi_parser.get_all_heroes_in_match(
                        gsi_data, my_team or "unknown"
                    )
                    if allies_draft or enemies_draft:
                        def do_hero_suggest():
                            suggestions = self.ai_recommender.recommend_hero(
                                allies_draft, enemies_draft
                            )
                            if suggestions:
                                self._enqueue_ui_call(
                                    lambda s=suggestions:
                                    self.overlay.update_hero_suggestions(s) if self.overlay else None
                                )
                        threading.Thread(target=do_hero_suggest, daemon=True).start()
                return

            # ═══ Clear hero suggestions once in game ═══
            if phase not in ("hero_selection", "strategy") and self.overlay:
                self._enqueue_ui_call(lambda: self.overlay.update_hero_suggestions([]))

            # ═══ Source 1: Try GSI draft/allheroes/allplayers data ═══
            allies, enemies = self.gsi_parser.get_all_heroes_in_match(gsi_data, my_team or "unknown")
            allies = self._normalize_hero_list(allies)
            enemies = self._normalize_hero_list(enemies)

            # Cache draft picks if we got them (they vanish after hero selection)
            if enemies:
                self._draft_cache = {"allies": allies, "enemies": enemies}
                if update_num <= 3 or enemies != self._last_enemies:
                    print(f"[GSI] Heroes found! Allies={allies} Enemies={enemies}")
            elif update_num <= 3:
                has_allheroes = "allheroes" in gsi_data
                has_allplayers = "allplayers" in gsi_data
                has_draft = "draft" in gsi_data
                print(f"[GSI] No enemies found — draft={has_draft} "
                      f"allheroes={has_allheroes} allplayers={has_allplayers} "
                      f"team={my_team}")

            # ═══ Source 2: Use cached draft from hero selection ═══
            if not enemies and self._draft_cache:
                allies = self._normalize_hero_list(self._draft_cache.get("allies", []))
                enemies = self._normalize_hero_list(self._draft_cache.get("enemies", []))
                if update_num <= 3:
                    print(f"[GSI] Using cached draft: Allies={allies} Enemies={enemies}")

            # ═══ Source 3: API lookup — Stratz (live) then OpenDota (finished) ═══
            now = time.time()
            if (not enemies and not self._api_lookup_in_progress
                    and now > self._api_lookup_cooldown_until):
                account_id = gsi_data.get("player", {}).get("accountid")
                match_id = gsi_data.get("map", {}).get("matchid")
                if my_team and (match_id or account_id):
                    self._api_lookup_in_progress = True

                    def api_lookup():
                        try:
                            result = None

                            # Step 0: Try local sources first (faster, no API dependency).
                            if match_id and account_id:
                                result = self.match_lookup.lookup_overwolf_roster(
                                    str(match_id), str(account_id), my_team, my_hero=valve_hero
                                )
                            if not result and match_id and account_id:
                                result = self.match_lookup.lookup_local_last_match(
                                    str(match_id), str(account_id), my_team
                                )

                            # Step 1: Try Stratz live match (needs match_id)
                            if not result and match_id and self.match_lookup.has_stratz_token():
                                print(f"[GSI] Trying Stratz live match {match_id}...")
                                result = self.match_lookup.lookup_live_stratz(
                                    str(match_id), my_team
                                )

                            # Step 2: Try OpenDota finished matches (needs account_id)
                            if not result and account_id:
                                print(f"[GSI] Trying OpenDota for account {account_id}...")
                                result = self.match_lookup.lookup_match_heroes(
                                    str(account_id), my_team
                                )

                            if result:
                                api_allies, api_enemies = result
                                self._draft_cache = {
                                    "allies": self._normalize_hero_list(api_allies),
                                    "enemies": self._normalize_hero_list(api_enemies),
                                }
                                self._last_enemies = []  # Force recalculation
                                self._api_lookup_cooldown_until = 0
                            else:
                                self._api_lookup_cooldown_until = time.time() + 60
                                has_stratz = self.match_lookup.has_stratz_token()
                                hint = "" if has_stratz else " (add Stratz token for live detection)"
                                print(f"[GSI] No match data found{hint} — retry in 60s")
                        except Exception as e:
                            self._api_lookup_cooldown_until = time.time() + 60
                            print(f"[GSI] API lookup error: {e} (retry in 60s)")
                        finally:
                            self._api_lookup_in_progress = False

                    threading.Thread(target=api_lookup, daemon=True).start()

            # ═══ Source 4: Generate recommendation ═══
            # Triggers when: hero changes (new match) or enemies found/changed
            rec_signature = self._build_recommendation_signature(
                my_hero=my_hero,
                allies=allies,
                enemies=enemies,
                my_items=my_items,
                game_time=state.get("game_time", 0),
                role=self.selected_role,
            )

            if rec_signature != self._last_recommendation_signature:
                self._last_recommendation_signature = rec_signature
                self._last_enemies = enemies[:] if enemies else []
                self._last_hero = my_hero
                source = "draft" if enemies else "hero-only"
                print(f"[GSI] Generating {source} build for {my_hero}"
                      + (f" vs {enemies}" if enemies else ""))

                def do_recommend():
                    try:
                        rule_rec = self.recommender.recommend(
                            my_hero=valve_hero,
                            enemies=enemies if enemies else [],
                            allies=allies if allies else [],
                            my_items=my_items,
                            role=self.selected_role,
                        )
                        rule_rec["source"] = source

                        # Try AI recommender first, but keep rule-based structure/explanations.
                        rec = None
                        if self.ai_recommender.is_available:
                            player_items_data = None
                            if has_allplayers and my_team:
                                player_items_data = self.gsi_parser.parse_all_players(gsi_data, my_team)
                            elif my_items:
                                player_items_data = {
                                    "allies": [{"hero": my_hero, "items": my_items}],
                                    "enemies": [],
                                }

                            rec = self.ai_recommender.recommend(
                                my_hero=my_hero,
                                enemies=enemies if enemies else [],
                                allies=allies if allies else [],
                                all_player_items=player_items_data,
                                game_time=state.get("game_time", 0),
                                my_items=my_items,
                                rule_based_rec=rule_rec,
                            )

                        use_ai, ai_reason = self._should_use_ai_items(
                            rec, phase, has_allplayers, my_items, self.selected_role
                        )

                        if rec is None or not use_ai:
                            if rec is not None and ai_reason:
                                print(f"[GSI] Using rule-based items: {ai_reason}")
                            rec = rule_rec
                        else:
                            rec = self._merge_ai_recommendation(rec, rule_rec)

                        self._last_recommendation = rec
                        self._enqueue_ui_call(lambda: self._update_overlay(rec))
                    except Exception as e:
                        print(f"[GSI] Recommendation error: {e}")
                        traceback.print_exc()

                threading.Thread(target=do_recommend, daemon=True).start()

            # ═══ Live player items tracking ═══
            now = time.time()
            if has_allplayers and my_team and now - self._last_player_items_update >= 5:
                self._last_player_items_update = now
                player_items = self.gsi_parser.parse_all_players(gsi_data, my_team)
                if player_items["enemies"] or player_items["allies"]:
                    my_hero_internal = state.get("my_hero", "")
                    dangers = self.item_threat_analyzer.check_dangers(
                        my_hero_internal, player_items["enemies"]
                    )
                    self._enqueue_ui_call(
                        lambda pi=player_items, d=dangers:
                        self.overlay.update_player_items(pi, d) if self.overlay else None
                    )

        except Exception as e:
            print(f"[GSI] Parse error: {e}")
            traceback.print_exc()

    def _update_overlay(self, rec: dict):
        """Update overlay with recommendation (main thread)."""
        if self.overlay:
            items_signature = (
                tuple(i.get("item", "") for i in rec.get("early_game", [])),
                tuple(i.get("item", "") for i in rec.get("mid_game", [])),
                tuple(i.get("item", "") for i in rec.get("late_game", [])),
                rec.get("source", ""),
            )
            if items_signature == self._last_overlay_items_signature:
                return
            self._last_overlay_items_signature = items_signature
            self.overlay.update_recommendation(rec)
            self.overlay.show()

    def _clear_frame(self):
        if self.current_frame:
            self.current_frame.destroy()
            self.current_frame = None

    def _show_home(self):
        """Show the home screen with mode selection."""
        self._clear_frame()
        gsi_installed = is_gsi_installed()
        self.current_frame = HomeScreen(
            self,
            on_browse=self._show_hero_select,
            on_overlay=self._start_overlay_mode,
            gsi_installed=gsi_installed,
        )
        self.current_frame.pack(fill="both", expand=True)

    def _show_hero_select(self):
        """Show the hero selection grid screen."""
        self._clear_frame()
        heroes = self.loader.get_all_heroes()
        self.current_frame = HeroSelectFrame(
            self, heroes, self.assets_dir,
            on_hero_selected=self._show_build_view
        )
        self.current_frame.pack(fill="both", expand=True)

    def _show_build_view(self, hero_data: dict):
        """Show the build detail screen for a selected hero."""
        self._clear_frame()
        self.current_frame = BuildViewFrame(
            self, hero_data, self.loader.get_all_items(), self.assets_dir,
            on_back=self._show_hero_select
        )
        self.current_frame.pack(fill="both", expand=True)

    def _start_overlay_mode(self):
        """Start the live overlay mode."""
        if not self.selected_role:
            self._prompt_role_selection(on_selected=self._start_overlay_mode)
            return

        # Check and install GSI config if needed
        if not is_gsi_installed():
            self._prompt_gsi_install()
        elif is_gsi_outdated():
            # Silently update to latest config
            success, msg = install_gsi_config()
            if success:
                print(f"[App] GSI config auto-updated: {msg}")
                print("[App] NOTE: Restart Dota 2 for the new config to take effect")

        # Create overlay window
        if self.overlay is None:
            self.overlay = OverlayWindow(
                self.assets_dir,
                self.loader.get_all_items(),
            )
            # If a recommendation was already generated (GSI arrived before overlay),
            # display it immediately instead of showing "Waiting for match..."
            if self._last_recommendation:
                self.overlay.update_recommendation(self._last_recommendation)
                print("[App] Displayed cached recommendation on new overlay")
            else:
                self.overlay.set_waiting()
        else:
            self.overlay.show()

        # Show status on main window
        self._clear_frame()
        self.current_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.current_frame.pack(fill="both", expand=True)

        ctk.CTkLabel(self.current_frame, text="LIVE OVERLAY ACTIVE",
                     font=("Segoe UI", 24, "bold"), text_color="#4CAF50").pack(pady=(80, 10))
        ctk.CTkLabel(self.current_frame, text="The overlay is running. Start a Dota 2 match!",
                     font=("Segoe UI", 14), text_color="#888").pack(pady=(0, 5))
        ctk.CTkLabel(self.current_frame, text="Press Alt+D to toggle overlay visibility",
                     font=("Segoe UI", 12), text_color="#666").pack(pady=(0, 5))

        role_frame = ctk.CTkFrame(self.current_frame, fg_color="#0f0f23",
                                  corner_radius=8, border_width=1, border_color="#2a2a4a")
        role_frame.pack(pady=(14, 4))
        ctk.CTkLabel(role_frame, text="Selected Role:",
                     font=("Segoe UI", 11), text_color="#888").pack(side="left", padx=(16, 8), pady=10)
        self._role_value_label = ctk.CTkLabel(
            role_frame,
            text=self.recommender.ROLE_CONFIGS[self.selected_role]["label"],
            font=("Segoe UI", 11, "bold"),
            text_color="#e94560",
        )
        self._role_value_label.pack(side="left", padx=(0, 14), pady=10)
        ctk.CTkButton(role_frame, text="Change Role", width=110, height=28,
                      font=("Segoe UI", 10), fg_color="#2a2a4a", hover_color="#444",
                      command=lambda: self._prompt_role_selection()).pack(side="left", padx=(0, 14))

        # Live connection status indicator
        status_frame = ctk.CTkFrame(self.current_frame, fg_color="#0f0f23",
                                    corner_radius=8, border_width=1, border_color="#2a2a4a")
        status_frame.pack(pady=(20, 5))

        ctk.CTkLabel(status_frame,
                     text=f"GSI Server: listening on port {self.gsi_server.port}",
                     font=("Segoe UI", 11), text_color="#4CAF50").pack(padx=20, pady=(10, 2))

        self._gsi_status_label = ctk.CTkLabel(
            status_frame, text="Waiting for Dota 2 data... (0 updates received)",
            font=("Segoe UI", 10), text_color="#FF9800"
        )
        self._gsi_status_label.pack(padx=20, pady=(0, 4))

        self._gsi_hint_label = ctk.CTkLabel(
            status_frame,
            text="If stuck at 0: restart Dota 2 (GSI configs are read at startup only)",
            font=("Segoe UI", 9), text_color="#666"
        )
        self._gsi_hint_label.pack(padx=20, pady=(0, 10))

        # Start polling for connection status
        self._poll_gsi_status()

        # ═══ Stratz API token setup (for live enemy detection) ═══
        stratz_frame = ctk.CTkFrame(self.current_frame, fg_color="#0f0f23",
                                     corner_radius=8, border_width=1, border_color="#2a2a4a")
        stratz_frame.pack(pady=(10, 5))

        has_token = self.match_lookup.has_stratz_token()
        if has_token:
            ctk.CTkLabel(stratz_frame, text="Stratz API: Connected (live enemy detection enabled)",
                         font=("Segoe UI", 10), text_color="#4CAF50").pack(padx=20, pady=(8, 6))
        else:
            ctk.CTkLabel(stratz_frame,
                         text="For live enemy hero detection, enter your free Stratz API token:",
                         font=("Segoe UI", 10), text_color="#FF9800").pack(padx=20, pady=(8, 2))

            token_row = ctk.CTkFrame(stratz_frame, fg_color="transparent")
            token_row.pack(padx=20, pady=(2, 4))

            token_entry = ctk.CTkEntry(token_row, width=280, height=28,
                                       placeholder_text="Paste Stratz API token here",
                                       font=("Segoe UI", 9))
            token_entry.pack(side="left", padx=(0, 5))

            def save_token():
                token = token_entry.get().strip()
                if not token:
                    return
                config_path = self.base_dir / "data" / "config.json"
                try:
                    config = {}
                    if config_path.exists():
                        with open(config_path, "r", encoding="utf-8") as f:
                            config = json.load(f)
                    config["stratz_token"] = token
                    with open(config_path, "w", encoding="utf-8") as f:
                        json.dump(config, f, indent=4)
                    self.match_lookup.reload_config(str(self.base_dir / "data"))
                    token_entry.configure(state="disabled")
                    save_btn.configure(text="Saved!", fg_color="#4CAF50")
                    print(f"[App] Stratz token saved — live enemy detection enabled")
                except Exception as e:
                    print(f"[App] Failed to save Stratz token: {e}")

            save_btn = ctk.CTkButton(token_row, text="Save", width=60, height=28,
                                     font=("Segoe UI", 10), fg_color="#e94560",
                                     hover_color="#c81e45", command=save_token)
            save_btn.pack(side="left")

            ctk.CTkLabel(stratz_frame,
                         text="Get your free token at stratz.com/api",
                         font=("Segoe UI", 9), text_color="#555").pack(padx=20, pady=(0, 6))

        # Simulate button (for testing without a live game)
        ctk.CTkButton(self.current_frame, text="Test with Sample Draft",
                      width=250, height=40,
                      font=("Segoe UI", 12),
                      fg_color="#2a2a4a", hover_color="#e94560",
                      command=self._test_sample_draft).pack(pady=(15, 5))

        ctk.CTkButton(self.current_frame, text="Back to Home",
                      width=150, height=35,
                      font=("Segoe UI", 11),
                      fg_color="#2a2a4a", hover_color="#e94560",
                      command=self._show_home).pack(pady=(10, 0))

    def _poll_gsi_status(self):
        """Poll the GSI server for connection status and update the UI."""
        if not hasattr(self, '_gsi_status_label'):
            return
        try:
            count = self.gsi_server.update_count
            if count > 0:
                self._gsi_status_label.configure(
                    text=f"Connected! ({count} updates received)",
                    text_color="#4CAF50"
                )
                self._gsi_hint_label.configure(
                    text="Dota 2 is sending data successfully",
                    text_color="#4CAF50"
                )
            else:
                self._gsi_status_label.configure(
                    text=f"Waiting for Dota 2 data... (0 updates received)",
                    text_color="#FF9800"
                )
        except Exception:
            pass
        # Poll every 2 seconds
        self.after(2000, self._poll_gsi_status)

    def _test_sample_draft(self):
        """Test the overlay with a sample draft and player items (for demo/testing)."""
        try:
            rec = self.recommender.recommend(
                my_hero="drow_ranger",
                enemies=["slardar", "antimage", "crystal_maiden", "lion", "tinker"],
                allies=["centaur", "necrolyte", "hoodwink", "shadow_shaman"],
                role=self.selected_role or "pos1",
            )
            if self.overlay:
                self.overlay.update_recommendation(rec)

                # Test player items scoreboard
                sample_players = {
                    "enemies": [
                        {"hero": "antimage", "hero_name": "Anti-Mage", "items": ["power_treads", "bfury", "manta", "basher"], "net_worth": 18500, "role_tags": ["carry"]},
                        {"hero": "tinker", "hero_name": "Tinker", "items": ["boots_of_travel", "blink", "shivas_guard", "scythe_of_vyse"], "net_worth": 16200, "role_tags": ["mid"]},
                        {"hero": "slardar", "hero_name": "Slardar", "items": ["phase_boots", "blink", "black_king_bar", "assault"], "net_worth": 12800, "role_tags": ["offlane"]},
                        {"hero": "lion", "hero_name": "Lion", "items": ["blink", "aether_lens", "aghs"], "net_worth": 8100, "role_tags": ["hard_support"]},
                        {"hero": "crystal_maiden", "hero_name": "Crystal Maiden", "items": ["tranquil_boots", "glimmer_cape", "black_king_bar"], "net_worth": 6400, "role_tags": ["hard_support"]},
                    ],
                    "allies": [
                        {"hero": "centaur", "hero_name": "Centaur Warrunner", "items": ["phase_boots", "blink", "pipe", "heart"], "net_worth": 14200, "role_tags": ["offlane"]},
                        {"hero": "necrophos", "hero_name": "Necrophos", "items": ["power_treads", "radiance", "black_king_bar"], "net_worth": 13500, "role_tags": ["mid"]},
                        {"hero": "hoodwink", "hero_name": "Hoodwink", "items": ["arcane_boots", "gleipnir", "aghs"], "net_worth": 9800, "role_tags": ["support"]},
                        {"hero": "shadow_shaman", "hero_name": "Shadow Shaman", "items": ["arcane_boots", "aether_lens", "blink"], "net_worth": 7200, "role_tags": ["hard_support"]},
                    ],
                }
                dangers = self.item_threat_analyzer.check_dangers("drow_ranger", sample_players["enemies"])
                self.overlay.update_player_items(sample_players, dangers)
                self.overlay.show()
                print(f"[Test] Sample draft + items displayed. {len(dangers)} danger alerts.")
        except Exception as e:
            print(f"[Test] Error: {e}")
            traceback.print_exc()

    def _prompt_gsi_install(self):
        """Prompt user to install GSI config."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Install GSI Config")
        dialog.geometry("550x300")
        dialog.attributes("-topmost", True)
        dialog.configure(fg_color="#0a0a1a")

        # Center on parent
        dialog.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 550) // 2
        y = self.winfo_y() + (self.winfo_height() - 300) // 2
        dialog.geometry(f"550x300+{x}+{y}")

        ctk.CTkLabel(dialog, text="GSI Setup Required",
                     font=("Segoe UI", 16, "bold"), text_color="#e94560").pack(pady=(15, 5))
        ctk.CTkLabel(dialog,
                     text="To receive live game data, a small config file\n"
                          "needs to be placed in your Dota 2 folder.\n"
                          "This is Valve's official Game State Integration — 100% safe.",
                     font=("Segoe UI", 11), text_color="#aaa").pack(pady=(0, 10))

        # Manual path input
        path_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        path_frame.pack(fill="x", padx=30, pady=(0, 5))
        ctk.CTkLabel(path_frame, text="Dota 2 path (if auto-detect fails):",
                     font=("Segoe UI", 10), text_color="#888").pack(anchor="w")
        path_entry = ctk.CTkEntry(path_frame, width=480, height=30,
                                  placeholder_text=r"e.g. G:\Steam\steamapps\common\dota 2 beta",
                                  font=("Segoe UI", 10))
        path_entry.pack(fill="x", pady=(2, 0))

        result_label = ctk.CTkLabel(dialog, text="", font=("Segoe UI", 10),
                                    wraplength=480)
        result_label.pack(pady=(8, 5))

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=5)

        def do_install():
            manual_path = path_entry.get().strip()
            if manual_path:
                from pathlib import Path as P
                dota_path = P(manual_path)
                if not dota_path.exists():
                    result_label.configure(text=f"Path does not exist: {manual_path}", text_color="#F44336")
                    return
                success, msg = install_gsi_config(dota_path)
            else:
                success, msg = install_gsi_config()
            if success:
                result_label.configure(
                    text=f"{msg}\n\nIMPORTANT: You must RESTART Dota 2 for the config to take effect!",
                    text_color="#4CAF50"
                )
            else:
                result_label.configure(text=msg, text_color="#F44336")

        ctk.CTkButton(btn_frame, text="Install", width=120, fg_color="#e94560",
                      hover_color="#c81e45", command=do_install).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="Skip", width=120, fg_color="#2a2a4a",
                      hover_color="#444", command=dialog.destroy).pack(side="left", padx=10)

    def _on_close(self):
        """Clean up on window close."""
        print("[App] Shutting down...")
        self.gsi_server.stop()
        if self._hotkey_listener:
            try:
                self._hotkey_listener.stop()
            except Exception:
                pass
        if self.overlay:
            try:
                self.overlay.destroy()
            except Exception:
                pass
        self.destroy()


def main():
    def _thread_excepthook(args):
        print(f"[Thread] Unhandled exception in {args.thread.name}: {args.exc_value}")
        traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)

    def _sys_excepthook(exc_type, exc_value, exc_traceback):
        print(f"[App] Unhandled exception: {exc_value}")
        traceback.print_exception(exc_type, exc_value, exc_traceback)

    try:
        faulthandler.enable(all_threads=True)
    except Exception:
        pass

    threading.excepthook = _thread_excepthook
    sys.excepthook = _sys_excepthook
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    app = DotaBuildApp()
    app.mainloop()


if __name__ == "__main__":
    main()
