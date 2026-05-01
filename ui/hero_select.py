"""Hero selection screen with grid of hero portraits."""
import customtkinter as ctk
from PIL import Image
from pathlib import Path
from typing import Callable, Optional


class HeroCard(ctk.CTkFrame):
    """A clickable hero portrait card."""

    def __init__(self, master, hero_data: dict, icon_path: Optional[Path], on_click: Callable, **kwargs):
        super().__init__(master, **kwargs)
        self.hero_data = hero_data
        self.on_click = on_click
        self.configure(
            corner_radius=8,
            fg_color="#1a1a2e",
            cursor="hand2",
            border_width=1,
            border_color="#2a2a4a"
        )

        # Hero icon
        if icon_path and icon_path.exists():
            try:
                img = Image.open(icon_path).resize((72, 72))
                self._photo = ctk.CTkImage(light_image=img, dark_image=img, size=(72, 72))
                icon_label = ctk.CTkLabel(self, image=self._photo, text="")
                icon_label.pack(padx=4, pady=(4, 0))
                icon_label.bind("<Button-1>", lambda e: self.on_click(self.hero_data))
            except Exception:
                self._make_placeholder()
        else:
            self._make_placeholder()

        # Hero name
        name_label = ctk.CTkLabel(
            self, text=hero_data["name"],
            font=("Segoe UI", 10),
            wraplength=80,
            text_color="#c0c0c0"
        )
        name_label.pack(padx=2, pady=(0, 4))
        name_label.bind("<Button-1>", lambda e: self.on_click(self.hero_data))

        # Make entire frame clickable
        self.bind("<Button-1>", lambda e: self.on_click(self.hero_data))

        # Hover effects
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _make_placeholder(self):
        placeholder = ctk.CTkLabel(self, text="?", font=("Segoe UI", 28), width=72, height=72,
                                   text_color="#555")
        placeholder.pack(padx=4, pady=(4, 0))
        placeholder.bind("<Button-1>", lambda e: self.on_click(self.hero_data))

    def _on_enter(self, event):
        self.configure(border_color="#e94560", fg_color="#16213e")

    def _on_leave(self, event):
        self.configure(border_color="#2a2a4a", fg_color="#1a1a2e")


class HeroSelectFrame(ctk.CTkFrame):
    """Main hero selection screen."""

    FILTER_ORDER = ["All", "Carry", "Mid", "Offlane", "Support"]

    def __init__(self, master, heroes: list[dict], assets_dir: Path, on_hero_selected: Callable, **kwargs):
        super().__init__(master, **kwargs)
        self.heroes = heroes
        self.assets_dir = assets_dir
        self.on_hero_selected = on_hero_selected
        self.current_filter = "All"
        self.configure(fg_color="transparent")

        self._build_ui()

    def _build_ui(self):
        # Title
        title = ctk.CTkLabel(self, text="DOTA 2 BUILD GENERATOR",
                             font=("Segoe UI", 28, "bold"), text_color="#e94560")
        title.pack(pady=(15, 5))

        subtitle = ctk.CTkLabel(self, text="Select a hero to view item builds",
                                font=("Segoe UI", 14), text_color="#888")
        subtitle.pack(pady=(0, 10))

        # Controls row: filter tabs + search
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(pady=(0, 10), fill="x", padx=20)

        # Role filter tabs
        filter_frame = ctk.CTkFrame(controls, fg_color="transparent")
        filter_frame.pack(side="left")

        self._filter_buttons = {}
        available_roles = {role for hero in self.heroes for role in hero.get("roles", [])}
        filter_roles = ["All"] + [role for role in self.FILTER_ORDER[1:] if role in available_roles]
        for role in filter_roles:
            btn = ctk.CTkButton(
                filter_frame, text=role, width=100, height=32,
                font=("Segoe UI", 13, "bold"),
                fg_color="#e94560" if role == "All" else "#2a2a4a",
                hover_color="#c81e45",
                command=lambda r=role: self._filter_role(r)
            )
            btn.pack(side="left", padx=4)
            self._filter_buttons[role] = btn

        # Hero count label
        self.count_label = ctk.CTkLabel(controls, text="", font=("Segoe UI", 12), text_color="#666")
        self.count_label.pack(side="left", padx=20)

        # Search bar
        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refresh_grid())
        search = ctk.CTkEntry(
            controls, textvariable=self.search_var,
            placeholder_text="Search heroes...",
            width=250, height=36,
            font=("Segoe UI", 13)
        )
        search.pack(side="right")

        # Scrollable hero grid
        self.scroll_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._refresh_grid()

    def _filter_role(self, role: str):
        self.current_filter = role
        for r, btn in self._filter_buttons.items():
            btn.configure(fg_color="#e94560" if r == role else "#2a2a4a")
        self._refresh_grid()

    def _refresh_grid(self):
        # Clear grid
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        # Filter heroes
        search_text = self.search_var.get().lower()
        filtered = self.heroes
        if self.current_filter != "All":
            filtered = [h for h in filtered if self.current_filter in h.get("roles", [])]
        if search_text:
            filtered = [h for h in filtered if search_text in h["name"].lower()]

        # Update count
        self.count_label.configure(text=f"{len(filtered)} heroes")

        # Create grid
        cols = 8
        for i, hero in enumerate(filtered):
            row, col = divmod(i, cols)
            icon_path = self.assets_dir / "hero_icons" / f"{hero['id']}.png"
            card = HeroCard(
                self.scroll_frame, hero, icon_path,
                on_click=self.on_hero_selected
            )
            card.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")

        # Configure grid weights
        for c in range(cols):
            self.scroll_frame.grid_columnconfigure(c, weight=1)
