"""Build detail view showing items, skills, strategy, counters."""
import customtkinter as ctk
from PIL import Image
from pathlib import Path
from typing import Callable, Optional


class ItemSlot(ctk.CTkFrame):
    """Single item display with icon and name."""

    def __init__(self, master, item_data: dict, item_info: Optional[dict], icon_path: Optional[Path], **kwargs):
        super().__init__(master, **kwargs)
        self.configure(fg_color="#1a1a2e", corner_radius=6, border_width=1, border_color="#2a2a4a",
                       width=90, height=110)
        self.grid_propagate(False)
        self.pack_propagate(False)

        if icon_path and icon_path.exists():
            try:
                img = Image.open(icon_path).resize((48, 36))
                self._photo = ctk.CTkImage(light_image=img, dark_image=img, size=(48, 36))
                ctk.CTkLabel(self, image=self._photo, text="").pack(padx=4, pady=(6, 2))
            except Exception:
                ctk.CTkLabel(self, text="?", font=("Segoe UI", 18), width=48, height=36,
                             text_color="#555").pack(padx=4, pady=(6, 2))
        else:
            ctk.CTkLabel(self, text="?", font=("Segoe UI", 18), width=48, height=36,
                         text_color="#555").pack(padx=4, pady=(6, 2))

        item_name = item_info["name"] if item_info else item_data.get("item", "?")
        ctk.CTkLabel(self, text=item_name, font=("Segoe UI", 8), text_color="#bbb",
                     wraplength=80).pack(padx=2, pady=(0, 1))

        note = item_data.get("note", "")
        if note:
            ctk.CTkLabel(self, text=note, font=("Segoe UI", 7), text_color="#666",
                         wraplength=80).pack(padx=2, pady=(0, 3))


class PhasePanel(ctk.CTkFrame):
    """Panel showing 6 items for a game phase."""

    PHASE_COLORS = {
        "EARLY GAME": "#4CAF50",
        "MID GAME": "#FF9800",
        "LATE GAME": "#F44336",
    }

    def __init__(self, master, phase_name: str, items: list[dict],
                 all_items: dict, assets_dir: Path, **kwargs):
        super().__init__(master, **kwargs)
        phase_color = self.PHASE_COLORS.get(phase_name, "#888")
        self.configure(fg_color="#0f0f23", corner_radius=10, border_width=2, border_color=phase_color)

        # Phase header
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=10, pady=(8, 4))

        ctk.CTkLabel(header_frame, text=phase_name, font=("Segoe UI", 14, "bold"),
                     text_color=phase_color).pack(side="left")

        # Arrow indicator
        if phase_name != "LATE GAME":
            ctk.CTkLabel(header_frame, text="→", font=("Segoe UI", 16, "bold"),
                         text_color="#444").pack(side="right")

        # Items grid (2 rows x 3 cols)
        items_frame = ctk.CTkFrame(self, fg_color="transparent")
        items_frame.pack(padx=8, pady=(0, 8))

        for i, item_data in enumerate(items):
            item_id = item_data.get("item", "")
            item_info = all_items.get(item_id)
            icon_path = assets_dir / "item_icons" / f"{item_id}.png"

            row, col = divmod(i, 3)
            slot = ItemSlot(items_frame, item_data, item_info, icon_path)
            slot.grid(row=row, column=col, padx=3, pady=3)


class SkillBuildBar(ctk.CTkFrame):
    """Visual skill build order for levels 1-20."""

    SKILL_COLORS = {
        "Q": "#4CAF50",
        "W": "#2196F3",
        "E": "#FF9800",
        "R": "#F44336",
        "T": "#9C27B0",
    }

    SKILL_LABELS = {
        "Q": "Q",
        "W": "W",
        "E": "E",
        "R": "Ult",
        "T": "Talent",
    }

    def __init__(self, master, skill_build: dict, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(fg_color="#0f0f23", corner_radius=8, border_width=1, border_color="#2a2a4a")

        order = skill_build.get("order", [])
        notes = skill_build.get("notes", "")

        # Header
        header = ctk.CTkLabel(self, text="SKILL BUILD ORDER",
                              font=("Segoe UI", 12, "bold"), text_color="#e94560")
        header.pack(pady=(8, 4))

        # Level bar
        bar_frame = ctk.CTkFrame(self, fg_color="transparent")
        bar_frame.pack(padx=10, pady=4)

        for i, skill in enumerate(order):
            color = self.SKILL_COLORS.get(skill, "#555")
            level_frame = ctk.CTkFrame(bar_frame, fg_color=color, corner_radius=4,
                                       width=36, height=40)
            level_frame.grid(row=0, column=i, padx=1)
            level_frame.grid_propagate(False)

            # Level number
            ctk.CTkLabel(level_frame, text=str(i + 1), font=("Segoe UI", 7),
                         text_color="#ddd").place(relx=0.5, y=2, anchor="n")
            # Skill letter
            ctk.CTkLabel(level_frame, text=skill, font=("Segoe UI", 12, "bold"),
                         text_color="white").place(relx=0.5, rely=0.6, anchor="center")

        # Legend
        legend_frame = ctk.CTkFrame(self, fg_color="transparent")
        legend_frame.pack(pady=(4, 2))
        for key in ["Q", "W", "E", "R", "T"]:
            color = self.SKILL_COLORS[key]
            label_text = self.SKILL_LABELS[key]
            ctk.CTkLabel(legend_frame, text=f" {label_text} ", font=("Segoe UI", 10, "bold"),
                         text_color=color).pack(side="left", padx=6)

        # Notes
        if notes:
            ctk.CTkLabel(self, text=notes, font=("Segoe UI", 10), text_color="#888",
                         wraplength=700, justify="left").pack(padx=12, pady=(2, 8))


class CountersPanel(ctk.CTkFrame):
    """Matchup information panel."""

    def __init__(self, master, hero: dict, assets_dir: Path, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(fg_color="#0f0f23", corner_radius=8, border_width=1, border_color="#2a2a4a")

        ctk.CTkLabel(self, text="MATCHUPS", font=("Segoe UI", 12, "bold"),
                     text_color="#e94560").pack(anchor="w", padx=12, pady=(8, 6))

        matchup_grid = ctk.CTkFrame(self, fg_color="transparent")
        matchup_grid.pack(fill="x", padx=12, pady=(0, 10))
        matchup_grid.grid_columnconfigure(0, weight=1)
        matchup_grid.grid_columnconfigure(1, weight=1)

        # Good against (left column)
        good_frame = ctk.CTkFrame(matchup_grid, fg_color="#0a1a0a", corner_radius=6)
        good_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        ctk.CTkLabel(good_frame, text="✓ GOOD AGAINST", font=("Segoe UI", 11, "bold"),
                     text_color="#4CAF50").pack(anchor="w", padx=8, pady=(6, 4))
        for hero_name in hero.get("good_against", []):
            ctk.CTkLabel(good_frame, text=f"  {hero_name}", font=("Segoe UI", 10),
                         text_color="#81C784").pack(anchor="w", padx=8, pady=1)
        # padding at bottom
        ctk.CTkLabel(good_frame, text="").pack(pady=(0, 6))

        # Countered by (right column)
        bad_frame = ctk.CTkFrame(matchup_grid, fg_color="#1a0a0a", corner_radius=6)
        bad_frame.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        ctk.CTkLabel(bad_frame, text="✗ COUNTERED BY", font=("Segoe UI", 11, "bold"),
                     text_color="#F44336").pack(anchor="w", padx=8, pady=(6, 4))
        for hero_name in hero.get("counters", []):
            ctk.CTkLabel(bad_frame, text=f"  {hero_name}", font=("Segoe UI", 10),
                         text_color="#E57373").pack(anchor="w", padx=8, pady=1)
        ctk.CTkLabel(bad_frame, text="").pack(pady=(0, 6))


class BuildViewFrame(ctk.CTkFrame):
    """Full build detail view for a selected hero."""

    def __init__(self, master, hero: dict, all_items: dict, assets_dir: Path,
                 on_back: Callable, **kwargs):
        super().__init__(master, **kwargs)
        self.hero = hero
        self.all_items = all_items
        self.assets_dir = assets_dir
        self.on_back = on_back
        self.configure(fg_color="transparent")

        self.current_build_key = list(hero["builds"].keys())[0]
        self._build_label_to_key = {v["label"]: k for k, v in hero["builds"].items()}

        self._build_ui()

    def _build_ui(self):
        # ═══ Top bar ═══
        top = ctk.CTkFrame(self, fg_color="#0f0f23", corner_radius=0, height=70)
        top.pack(fill="x", padx=0, pady=0)
        top.pack_propagate(False)

        # Back button
        back_btn = ctk.CTkButton(top, text="← Back", width=80, height=36,
                                 fg_color="#2a2a4a", hover_color="#e94560",
                                 font=("Segoe UI", 12, "bold"),
                                 command=self.on_back)
        back_btn.pack(side="left", padx=12, pady=17)

        # Hero icon + name + roles
        info_frame = ctk.CTkFrame(top, fg_color="transparent")
        info_frame.pack(side="left", padx=10, pady=10)

        hero_icon_path = self.assets_dir / "hero_icons" / f"{self.hero['id']}.png"
        if hero_icon_path.exists():
            try:
                img = Image.open(hero_icon_path).resize((50, 50))
                self._hero_photo = ctk.CTkImage(light_image=img, dark_image=img, size=(50, 50))
                ctk.CTkLabel(info_frame, image=self._hero_photo, text="").pack(side="left", padx=(0, 10))
            except Exception:
                pass

        name_roles = ctk.CTkFrame(info_frame, fg_color="transparent")
        name_roles.pack(side="left")
        ctk.CTkLabel(name_roles, text=self.hero["name"],
                     font=("Segoe UI", 20, "bold"), text_color="white").pack(anchor="w")

        roles_text = " | ".join(self.hero.get("roles", []))
        attr_text = self.hero.get("primary_attr", "").upper()
        ctk.CTkLabel(name_roles, text=f"{roles_text}  •  {attr_text}",
                     font=("Segoe UI", 11), text_color="#e94560").pack(anchor="w")
        if self.hero.get("auto_generated"):
            ctk.CTkLabel(name_roles, text="Auto-generated meta build",
                         font=("Segoe UI", 10), text_color="#888").pack(anchor="w")

        # Build selector (right side)
        selector_frame = ctk.CTkFrame(top, fg_color="transparent")
        selector_frame.pack(side="right", padx=12)

        ctk.CTkLabel(selector_frame, text="Build:", font=("Segoe UI", 12),
                     text_color="#888").pack(side="left", padx=(0, 6))

        build_labels = [v["label"] for v in self.hero["builds"].values()]
        self.build_selector = ctk.CTkComboBox(
            selector_frame,
            values=build_labels,
            width=280, height=34,
            font=("Segoe UI", 12),
            dropdown_font=("Segoe UI", 12),
            command=self._on_build_changed
        )
        self.build_selector.set(build_labels[0])
        self.build_selector.pack(side="left")

        # ═══ Scrollable content ═══
        self.content = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=10, pady=8)

        self._render_build()

    def _on_build_changed(self, selected_label: str):
        key = self._build_label_to_key.get(selected_label)
        if key:
            self.current_build_key = key
            self._render_build()

    def _render_build(self):
        # Clear content
        for widget in self.content.winfo_children():
            widget.destroy()

        build = self.hero["builds"][self.current_build_key]

        # Build description
        desc = build.get("description", "")
        if desc:
            desc_frame = ctk.CTkFrame(self.content, fg_color="#12122a", corner_radius=6)
            desc_frame.pack(fill="x", pady=(0, 8))
            ctk.CTkLabel(desc_frame, text=desc, font=("Segoe UI", 12),
                         text_color="#aaa", wraplength=900, justify="left").pack(padx=12, pady=8)

        # ═══ Item Phases ═══
        phases_frame = ctk.CTkFrame(self.content, fg_color="transparent")
        phases_frame.pack(fill="x", pady=4)
        phases_frame.grid_columnconfigure(0, weight=1)
        phases_frame.grid_columnconfigure(1, weight=1)
        phases_frame.grid_columnconfigure(2, weight=1)

        phases = [
            ("EARLY GAME", build.get("early_game", [])),
            ("MID GAME", build.get("mid_game", [])),
            ("LATE GAME", build.get("late_game", [])),
        ]

        for i, (name, items) in enumerate(phases):
            panel = PhasePanel(phases_frame, name, items, self.all_items, self.assets_dir)
            panel.grid(row=0, column=i, padx=4, sticky="nsew")

        # ═══ Skill Build ═══
        skill_build = build.get("skill_build")
        if skill_build:
            skill_bar = SkillBuildBar(self.content, skill_build)
            skill_bar.pack(fill="x", pady=8)

        # ═══ Strategy ═══
        strategy = build.get("strategy", "")
        if strategy:
            strat_frame = ctk.CTkFrame(self.content, fg_color="#0f0f23", corner_radius=8,
                                       border_width=1, border_color="#2a2a4a")
            strat_frame.pack(fill="x", pady=4)
            ctk.CTkLabel(strat_frame, text="STRATEGY",
                         font=("Segoe UI", 12, "bold"), text_color="#e94560").pack(
                anchor="w", padx=12, pady=(8, 4))
            ctk.CTkLabel(strat_frame, text=strategy, font=("Segoe UI", 11),
                         text_color="#ccc", wraplength=900, justify="left").pack(
                anchor="w", padx=12, pady=(0, 10))

        # ═══ Counters ═══
        counters = CountersPanel(self.content, self.hero, self.assets_dir)
        counters.pack(fill="x", pady=4)
