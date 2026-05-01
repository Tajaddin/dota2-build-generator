"""Transparent overlay window for displaying in-game recommendations."""
import customtkinter as ctk
from PIL import Image
from pathlib import Path
from typing import Optional


class OverlayWindow(ctk.CTkToplevel):
    """Semi-transparent always-on-top overlay for build recommendations.

    Features:
    - Toggle visibility with hotkey (Alt+D)
    - Draggable (click and drag anywhere)
    - Shows: threats, recommended items, reasoning, team gaps, enemy overview
    - Auto-updates when new recommendation data arrives
    """

    def __init__(self, assets_dir: Path, all_items: dict, **kwargs):
        super().__init__(**kwargs)
        self.assets_dir = assets_dir
        self.all_items = all_items

        # Window config
        self.title("Dota 2 Build Overlay")
        self.geometry("400x720")
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.90)
        self.configure(fg_color="#0a0a1a")
        self.overrideredirect(True)  # Remove title bar for clean look

        # Position on right side of screen
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        self.geometry(f"400x720+{screen_w - 420}+40")

        # Draggable window
        self._drag_data = {"x": 0, "y": 0}
        self.bind("<Button-1>", self._start_drag)
        self.bind("<B1-Motion>", self._do_drag)

        self._visible = True
        self._build_ui()

    def _start_drag(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _do_drag(self, event):
        x = self.winfo_x() + event.x - self._drag_data["x"]
        y = self.winfo_y() + event.y - self._drag_data["y"]
        self.geometry(f"+{x}+{y}")

    def toggle(self):
        """Toggle overlay visibility (called by hotkey)."""
        if self._visible:
            self.withdraw()
            self._visible = False
        else:
            self.deiconify()
            self._visible = True

    def show(self):
        """Show the overlay."""
        if not self._visible:
            self.deiconify()
            self._visible = True

    def hide(self):
        """Hide the overlay."""
        if self._visible:
            self.withdraw()
            self._visible = False

    def _build_ui(self):
        """Build the overlay layout."""
        # Main scrollable area
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                              scrollbar_button_color="#2a2a4a")
        self.scroll.pack(fill="both", expand=True, padx=6, pady=6)

        # ═══ Header ═══
        header_frame = ctk.CTkFrame(self.scroll, fg_color="#12122a", corner_radius=8)
        header_frame.pack(fill="x", pady=(0, 4))

        self.header_label = ctk.CTkLabel(
            header_frame, text="DOTA 2 BUILD ADVISOR",
            font=("Segoe UI", 15, "bold"), text_color="#e94560"
        )
        self.header_label.pack(pady=(6, 2))

        self.status_label = ctk.CTkLabel(
            header_frame, text="Waiting for match...",
            font=("Segoe UI", 10), text_color="#666"
        )
        self.status_label.pack(pady=(0, 6))

        # ═══ Hero Suggestions Section (draft phase only) ═══
        self.hero_suggest_frame = ctk.CTkFrame(self.scroll, fg_color="#0f0f23", corner_radius=6,
                                                border_width=1, border_color="#4CAF50")
        self.hero_suggest_frame.pack(fill="x", pady=3)
        self.hero_suggest_frame.pack_forget()  # Hidden until draft phase

        ctk.CTkLabel(self.hero_suggest_frame, text="HERO SUGGESTIONS",
                     font=("Segoe UI", 10, "bold"), text_color="#4CAF50").pack(
            anchor="w", padx=10, pady=(6, 2))

        self.hero_suggest_content = ctk.CTkLabel(
            self.hero_suggest_frame, text="",
            font=("Segoe UI", 9), text_color="#aaa", wraplength=370, justify="left"
        )
        self.hero_suggest_content.pack(anchor="w", padx=10, pady=(0, 6))

        # ═══ Threats Section ═══
        self.threats_frame = ctk.CTkFrame(self.scroll, fg_color="#0f0f23", corner_radius=6,
                                          border_width=1, border_color="#331111")
        self.threats_frame.pack(fill="x", pady=3)

        ctk.CTkLabel(self.threats_frame, text="THREATS",
                     font=("Segoe UI", 10, "bold"), text_color="#F44336").pack(
            anchor="w", padx=10, pady=(6, 2))

        self.threats_content = ctk.CTkLabel(
            self.threats_frame, text="No threats detected",
            font=("Segoe UI", 9), text_color="#888", wraplength=370, justify="left"
        )
        self.threats_content.pack(anchor="w", padx=10, pady=(0, 6))

        # ═══ Recommended Build Section ═══
        self.items_frame = ctk.CTkFrame(self.scroll, fg_color="#0f0f23", corner_radius=6,
                                        border_width=1, border_color="#2a2a4a")
        self.items_frame.pack(fill="x", pady=3)

        ctk.CTkLabel(self.items_frame, text="RECOMMENDED BUILD",
                     font=("Segoe UI", 10, "bold"), text_color="#e94560").pack(
            anchor="w", padx=10, pady=(6, 2))

        self.starting_label = ctk.CTkLabel(
            self.items_frame, text="STARTING ITEMS: --",
            font=("Segoe UI", 9), text_color="#81C784", wraplength=370, justify="left"
        )
        self.starting_label.pack(anchor="w", padx=10, pady=1)

        self.early_label = ctk.CTkLabel(
            self.items_frame, text="EARLY: --",
            font=("Segoe UI", 9), text_color="#4CAF50", wraplength=370, justify="left"
        )
        self.early_label.pack(anchor="w", padx=10, pady=1)

        self.mid_label = ctk.CTkLabel(
            self.items_frame, text="MID: --",
            font=("Segoe UI", 9), text_color="#FF9800", wraplength=370, justify="left"
        )
        self.mid_label.pack(anchor="w", padx=10, pady=1)

        self.late_label = ctk.CTkLabel(
            self.items_frame, text="LATE: --",
            font=("Segoe UI", 9), text_color="#F44336", wraplength=370, justify="left"
        )
        self.late_label.pack(anchor="w", padx=10, pady=1)

        self.situational_label = ctk.CTkLabel(
            self.items_frame, text="SITUATIONAL: --",
            font=("Segoe UI", 9), text_color="#64B5F6", wraplength=370, justify="left"
        )
        self.situational_label.pack(anchor="w", padx=10, pady=1)

        self.timings_label = ctk.CTkLabel(
            self.items_frame, text="TIMINGS: --",
            font=("Segoe UI", 9), text_color="#B39DDB", wraplength=370, justify="left"
        )
        self.timings_label.pack(anchor="w", padx=10, pady=(1, 6))

        # ═══ Reasoning Section ═══
        self.reason_frame = ctk.CTkFrame(self.scroll, fg_color="#0f0f23", corner_radius=6,
                                         border_width=1, border_color="#1a1a3a")
        self.reason_frame.pack(fill="x", pady=3)

        ctk.CTkLabel(self.reason_frame, text="WHY THIS BUILD",
                     font=("Segoe UI", 10, "bold"), text_color="#e94560").pack(
            anchor="w", padx=10, pady=(6, 2))

        self.reason_content = ctk.CTkLabel(
            self.reason_frame, text="--",
            font=("Segoe UI", 9), text_color="#aaa", wraplength=370, justify="left"
        )
        self.reason_content.pack(anchor="w", padx=10, pady=(0, 6))

        # ═══ Team Analysis Section ═══
        self.team_frame = ctk.CTkFrame(self.scroll, fg_color="#0f0f23", corner_radius=6,
                                       border_width=1, border_color="#1a1a3a")
        self.team_frame.pack(fill="x", pady=3)

        ctk.CTkLabel(self.team_frame, text="TEAM ANALYSIS",
                     font=("Segoe UI", 10, "bold"), text_color="#e94560").pack(
            anchor="w", padx=10, pady=(6, 2))

        self.team_content = ctk.CTkLabel(
            self.team_frame, text="--",
            font=("Segoe UI", 9), text_color="#888", wraplength=370, justify="left"
        )
        self.team_content.pack(anchor="w", padx=10, pady=(0, 6))

        # ═══ Enemy Overview Section ═══
        self.enemy_frame = ctk.CTkFrame(self.scroll, fg_color="#0f0f23", corner_radius=6,
                                        border_width=1, border_color="#1a1a3a")
        self.enemy_frame.pack(fill="x", pady=3)

        ctk.CTkLabel(self.enemy_frame, text="ENEMY OVERVIEW",
                     font=("Segoe UI", 10, "bold"), text_color="#e94560").pack(
            anchor="w", padx=10, pady=(6, 2))

        self.enemy_content = ctk.CTkLabel(
            self.enemy_frame, text="--",
            font=("Segoe UI", 9), text_color="#888", wraplength=370, justify="left"
        )
        self.enemy_content.pack(anchor="w", padx=10, pady=(0, 6))

        # ═══ Danger Alerts Section ═══
        self.danger_frame = ctk.CTkFrame(self.scroll, fg_color="#0f0f23", corner_radius=6,
                                          border_width=1, border_color="#cc3300")
        self.danger_frame.pack(fill="x", pady=3)
        self.danger_frame.pack_forget()  # Hidden by default

        ctk.CTkLabel(self.danger_frame, text="DANGER ALERTS",
                     font=("Segoe UI", 10, "bold"), text_color="#FF6600").pack(
            anchor="w", padx=10, pady=(6, 2))

        self.danger_content = ctk.CTkLabel(
            self.danger_frame, text="",
            font=("Segoe UI", 9), text_color="#FF8844", wraplength=370, justify="left"
        )
        self.danger_content.pack(anchor="w", padx=10, pady=(0, 6))

        # ═══ Enemy Items Scoreboard Section ═══
        self.enemy_items_frame = ctk.CTkFrame(self.scroll, fg_color="#0f0f23", corner_radius=6,
                                               border_width=1, border_color="#1a1a3a")
        self.enemy_items_frame.pack(fill="x", pady=3)
        self.enemy_items_frame.pack_forget()  # Hidden until data arrives

        ctk.CTkLabel(self.enemy_items_frame, text="ENEMY ITEMS",
                     font=("Segoe UI", 10, "bold"), text_color="#F44336").pack(
            anchor="w", padx=10, pady=(6, 2))

        self.enemy_items_content = ctk.CTkLabel(
            self.enemy_items_frame, text="",
            font=("Segoe UI", 9), text_color="#ccc", wraplength=370, justify="left"
        )
        self.enemy_items_content.pack(anchor="w", padx=10, pady=(0, 6))

        # ═══ Ally Items Scoreboard Section ═══
        self.ally_items_frame = ctk.CTkFrame(self.scroll, fg_color="#0f0f23", corner_radius=6,
                                              border_width=1, border_color="#1a1a3a")
        self.ally_items_frame.pack(fill="x", pady=3)
        self.ally_items_frame.pack_forget()  # Hidden until data arrives

        ctk.CTkLabel(self.ally_items_frame, text="ALLY ITEMS",
                     font=("Segoe UI", 10, "bold"), text_color="#4CAF50").pack(
            anchor="w", padx=10, pady=(6, 2))

        self.ally_items_content = ctk.CTkLabel(
            self.ally_items_frame, text="",
            font=("Segoe UI", 9), text_color="#aaa", wraplength=370, justify="left"
        )
        self.ally_items_content.pack(anchor="w", padx=10, pady=(0, 6))

        # ═══ Hotkey hint ═══
        ctk.CTkLabel(self.scroll, text="Alt+D to hide  |  Drag to move",
                     font=("Segoe UI", 8), text_color="#333").pack(pady=(6, 2))

    @staticmethod
    def _show_frame(frame, **pack_kwargs):
        """Pack a frame only when its visibility actually changes."""
        if not frame.winfo_manager():
            frame.pack(**pack_kwargs)

    @staticmethod
    def _hide_frame(frame):
        """Hide a frame only if it is currently visible."""
        if frame.winfo_manager():
            frame.pack_forget()

    @staticmethod
    def _configure_if_changed(widget, **kwargs):
        """Avoid redundant text/color updates that cause visible churn."""
        changed = {}
        for key, value in kwargs.items():
            try:
                if widget.cget(key) != value:
                    changed[key] = value
            except Exception:
                changed[key] = value
        if changed:
            widget.configure(**changed)

    def _format_items(self, items: list, start_index: int = 1) -> str:
        """Format item list into readable string."""
        if not items:
            return "--"
        names = []
        for idx, i in enumerate(items, start=start_index):
            item_id = i.get("item", "")
            info = self.all_items.get(item_id, {})
            name = info.get("name", item_id.replace("_", " ").title())
            names.append(f"{idx}. {name}")
        return "\n".join(names)

    @staticmethod
    def _format_section(title: str, body: str) -> str:
        return f"{title}:\n{body}"

    def update_recommendation(self, rec: dict):
        """Update the overlay with a new recommendation from the engine."""
        # Header
        hero_name = rec.get("hero_name", rec.get("hero", "Unknown"))
        source = rec.get("source", "draft")
        role_label = rec.get("role_label", "")
        self._configure_if_changed(self.header_label, text=f"{hero_name.upper()} BUILD")
        if source == "ai":
            confidence = rec.get("confidence", 0)
            if confidence > 0.7:
                color = "#4CAF50"
                text = f"AI recommendation (confidence: {confidence:.0%})"
            elif confidence > 0.4:
                color = "#FF9800"
                text = f"AI recommendation (confidence: {confidence:.0%})"
            else:
                color = "#F44336"
                # Avoid discouraging "0%" display for very low but non-zero scores.
                if confidence <= 0.05:
                    text = "AI recommendation (experimental / low data)"
                else:
                    text = f"AI recommendation (low confidence: {confidence:.0%})"
            if role_label:
                text = f"{text} | {role_label}"
            self._configure_if_changed(self.status_label, text=text, text_color=color)
        elif source == "hero-only":
            self._configure_if_changed(
                self.status_label,
                text=f"Popular build (no enemy draft data){' | ' + role_label if role_label else ''}",
                text_color="#FF9800"
            )
        else:
            self._configure_if_changed(
                self.status_label,
                text=f"Draft-aware recommendation{' | ' + role_label if role_label else ''}",
                text_color="#4CAF50"
            )

        # Threats
        threats = rec.get("threats", {})
        warnings = threats.get("warnings", [])
        if warnings:
            self._configure_if_changed(
                self.threats_content,
                text="\n".join(f"! {w}" for w in warnings),
                text_color="#E57373"
            )
        else:
            self._configure_if_changed(
                self.threats_content,
                text="No major threats detected",
                text_color="#888"
            )

        # Items
        starting_items = rec.get("starting_items", [])
        early_items = rec.get("early_game", [])
        mid_items = rec.get("mid_game", [])
        late_items = rec.get("late_game", [])
        situational = rec.get("situational_swaps", [])
        timings = rec.get("key_item_timings", [])

        self._configure_if_changed(
            self.starting_label,
            text=self._format_section("STARTING ITEMS", self._format_items(starting_items))
        )
        self._configure_if_changed(
            self.early_label,
            text=self._format_section("EARLY", self._format_items(early_items, start_index=1))
        )
        mid_start = len(early_items) + 1
        self._configure_if_changed(
            self.mid_label,
            text=self._format_section("MID", self._format_items(mid_items, start_index=mid_start))
        )
        late_start = len(early_items) + len(mid_items) + 1
        self._configure_if_changed(
            self.late_label,
            text=self._format_section("LATE", self._format_items(late_items, start_index=late_start))
        )
        self._configure_if_changed(
            self.situational_label,
            text=self._format_section("SITUATIONAL", "\n".join(situational) if situational else "--")
        )
        self._configure_if_changed(
            self.timings_label,
            text=self._format_section("TIMINGS", "\n".join(key for key in timings) if timings else "--")
        )

        # Reasoning
        reasoning = rec.get("reasoning", [])
        if reasoning:
            self._configure_if_changed(
                self.reason_content,
                text="\n".join(f"* {r}" for r in reasoning)
            )
        else:
            self._configure_if_changed(self.reason_content, text="Standard build recommended")

        # Team analysis
        team = rec.get("team_analysis", {})
        summary = team.get("summary", {})
        strengths = summary.get("strengths", [])
        weaknesses = summary.get("weaknesses", [])
        team_lines = []
        if strengths:
            team_lines.append(f"+ {', '.join(strengths[:5])}")
        if weaknesses:
            team_lines.append(f"- {', '.join(weaknesses[:4])}")
        self._configure_if_changed(
            self.team_content,
            text="\n".join(team_lines) if team_lines else "--"
        )

        # Enemy overview
        hero_details = threats.get("hero_details", [])
        enemy_lines = []
        for h in hero_details:
            tags_str = ", ".join(h.get("tags", [])[:3])
            dmg_str = "/".join(h.get("damage_types", []))
            disables = ", ".join(h.get("disables", [])[:2])
            line = f"{h['name']}  [{dmg_str}]  {tags_str}"
            if disables:
                line += f"  ({disables})"
            enemy_lines.append(line)
        self._configure_if_changed(
            self.enemy_content,
            text="\n".join(enemy_lines) if enemy_lines else "--"
        )

    def update_hero_suggestions(self, suggestions: list):
        """Show hero pick suggestions during draft phase."""
        if suggestions:
            self._show_frame(self.hero_suggest_frame, fill="x", pady=3, before=self.threats_frame)
            lines = []
            for i, s in enumerate(suggestions[:5]):
                score_pct = f"{s['score']:.0%}" if s.get('score') else ""
                lines.append(f"{i+1}. {s['hero_name']}  {score_pct}")
            self._configure_if_changed(self.hero_suggest_content, text="\n".join(lines))
        else:
            self._hide_frame(self.hero_suggest_frame)

    def update_player_items(self, player_data: dict, danger_alerts: list):
        """Update scoreboard and danger alerts with live player item data.

        Args:
            player_data: {"allies": [...], "enemies": [...]} from parse_all_players
            danger_alerts: List of alert dicts from ItemThreatAnalyzer
        """
        # Danger Alerts
        if danger_alerts:
            self._show_frame(self.danger_frame, fill="x", pady=3, before=self.enemy_items_frame)
            alert_lines = []
            for alert in danger_alerts[:6]:
                prefix = "!!" if alert["severity"] == "high" else "!"
                alert_lines.append(f"{prefix} {alert['message']}")
            self._configure_if_changed(self.danger_content, text="\n".join(alert_lines))
        else:
            self._hide_frame(self.danger_frame)

        # Enemy Items
        enemies = player_data.get("enemies", [])
        if enemies:
            self._show_frame(self.enemy_items_frame, fill="x", pady=3)
            lines = []
            for p in enemies:
                hero_name = p.get("hero_name", "Unknown")
                nw = p.get("net_worth", 0)
                nw_str = f"${nw // 1000}.{(nw % 1000) // 100}k" if nw >= 1000 else f"${nw}"
                items = p.get("items", [])
                item_names = []
                for item_id in items:
                    info = self.all_items.get(item_id, {})
                    item_names.append(info.get("name", item_id.replace("_", " ").title()))
                items_str = " > ".join(item_names) if item_names else "no items"
                role_str = f" [{'/'.join(r.capitalize() for r in p.get('role_tags', [])[:2])}]" if p.get('role_tags') else ""
                lines.append(f"{hero_name}{role_str}  {nw_str}\n  {items_str}")
            self._configure_if_changed(self.enemy_items_content, text="\n".join(lines))
        else:
            self._hide_frame(self.enemy_items_frame)

        # Ally Items
        allies = player_data.get("allies", [])
        if allies:
            self._show_frame(self.ally_items_frame, fill="x", pady=3)
            lines = []
            for p in allies:
                hero_name = p.get("hero_name", "Unknown")
                nw = p.get("net_worth", 0)
                nw_str = f"${nw // 1000}.{(nw % 1000) // 100}k" if nw >= 1000 else f"${nw}"
                items = p.get("items", [])
                item_names = []
                for item_id in items:
                    info = self.all_items.get(item_id, {})
                    item_names.append(info.get("name", item_id.replace("_", " ").title()))
                items_str = " > ".join(item_names) if item_names else "no items"
                role_str = f" [{'/'.join(r.capitalize() for r in p.get('role_tags', [])[:2])}]" if p.get('role_tags') else ""
                lines.append(f"{hero_name}{role_str}  {nw_str}\n  {items_str}")
            self._configure_if_changed(self.ally_items_content, text="\n".join(lines))
        else:
            self._hide_frame(self.ally_items_frame)

    def set_waiting(self, status_text: str = "Waiting for match..."):
        """Reset overlay to waiting-for-match state."""
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self._configure_if_changed(self.header_label, text="DOTA 2 BUILD ADVISOR")
        self._configure_if_changed(self.status_label, text=status_text, text_color="#666")
        self._configure_if_changed(self.threats_content, text="No threats detected", text_color="#888")
        self._configure_if_changed(self.starting_label, text=self._format_section("STARTING ITEMS", "--"))
        self._configure_if_changed(self.early_label, text=self._format_section("EARLY", "--"))
        self._configure_if_changed(self.mid_label, text=self._format_section("MID", "--"))
        self._configure_if_changed(self.late_label, text=self._format_section("LATE", "--"))
        self._configure_if_changed(self.situational_label, text=self._format_section("SITUATIONAL", "--"))
        self._configure_if_changed(self.timings_label, text=self._format_section("TIMINGS", "--"))
        self._configure_if_changed(self.reason_content, text="--")
        self._configure_if_changed(self.team_content, text="--")
        self._configure_if_changed(self.enemy_content, text="--")
        self._hide_frame(self.hero_suggest_frame)
        self._hide_frame(self.danger_frame)
        self._hide_frame(self.enemy_items_frame)
        self._hide_frame(self.ally_items_frame)
