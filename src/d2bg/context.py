"""Everything the app knows, built once from the data files and shared by the API, the live engine and the CLI."""

from __future__ import annotations

import threading
from functools import cached_property
from typing import Any

from d2bg.datastore import DataStore
from d2bg.draft.model import WinModel
from d2bg.draft.positions import hero_positions, playable
from d2bg.knowledge.counters import CounterRule
from d2bg.knowledge.timers import TimerRule
from d2bg.knowledge.traits import TraitIndex
from d2bg.opendota import OpenDotaClient
from d2bg.settings import SettingsStore

TIMER_FILE = "timers-7.41.json"


class AppContext:
    def __init__(
        self,
        data: DataStore | None = None,
        settings: SettingsStore | None = None,
        client: OpenDotaClient | None = None,
    ) -> None:
        self.data = data or DataStore()
        self.settings = settings or SettingsStore()
        self._client = client
        self._lock = threading.Lock()

    @property
    def client(self) -> OpenDotaClient:
        with self._lock:
            if self._client is None:
                self._client = OpenDotaClient(api_key=self.settings.get().opendota_api_key)
            return self._client

    def reset_client(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.close()
            self._client = None

    def reload(self) -> None:
        """Pick up refreshed data files."""
        self.data.reload()
        for prop in ("traits", "positions", "playable", "win_model", "counter_rules", "timer_rules"):
            self.__dict__.pop(prop, None)

    @cached_property
    def traits(self) -> TraitIndex:
        return TraitIndex(self.data.heroes, self.data.knowledge_file("trait_overrides.json"))

    @cached_property
    def positions(self) -> dict[int, dict[str, Any]]:
        roles = {h.id: h.roles for h in self.data.heroes}
        return hero_positions(self.data.load("pro_builds.json"), self.data.load("lane_roles.json"), roles)

    @cached_property
    def playable(self) -> dict[int, set[int]]:
        return playable(self.positions)

    @cached_property
    def win_model(self) -> WinModel | None:
        doc = self.data.load("draft_model.json")
        return WinModel(doc) if doc else None

    @cached_property
    def counter_rules(self) -> list[CounterRule]:
        return CounterRule.load(self.data.knowledge_file("counter_items.json"))

    @cached_property
    def timer_rules(self) -> list[TimerRule]:
        return TimerRule.load(self.data.knowledge_file(TIMER_FILE))

    @property
    def timer_patch(self) -> str:
        return str(self.data.knowledge_file(TIMER_FILE)["patch"])
