"""User settings, stored as JSON in the user folder.

Secrets (the GSI token, the LAN token, an OpenDota API key) live here too, outside the repository.
``public_view`` masks them before anything is sent to the UI.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from d2bg import paths

RankBucket = Literal["1-2", "3-4", "5-6", "7-8", "all"]
PoolMode = Literal["off", "boost", "only"]


def _token() -> str:
    return secrets.token_urlsafe(24)


class TimerPrefs(BaseModel):
    enabled: dict[str, bool] = Field(default_factory=dict)
    voice: bool = True
    lead_seconds: int = Field(default=15, ge=0, le=120)


class Settings(BaseModel):
    account_id: int | None = Field(default=None, ge=1)
    rank_bucket: RankBucket = "all"
    positions: list[int] = Field(default_factory=list)
    hero_pool: list[int] = Field(default_factory=list)
    pool_mode: PoolMode = "off"
    blacklist: list[int] = Field(default_factory=list)
    whitelist: list[int] = Field(default_factory=list)
    synergy_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    timers: TimerPrefs = Field(default_factory=TimerPrefs)
    record_gsi: bool = True
    keep_recordings: int = Field(default=20, ge=1, le=500)
    auto_post_game: bool = True
    request_parse: bool = False
    lan_mode: bool = False
    theme: Literal["dark", "light"] = "dark"
    opendota_api_key: str | None = None
    gsi_token: str = Field(default_factory=_token)
    lan_token: str = Field(default_factory=_token)

    def public_view(self) -> dict[str, Any]:
        data = self.model_dump()
        data["opendota_api_key"] = "set" if self.opendota_api_key else None
        data.pop("gsi_token")
        data.pop("lan_token")
        return data


# Fields the UI may change. Tokens are managed by the app itself.
EDITABLE = set(Settings.model_fields) - {"gsi_token", "lan_token"}


class SettingsStore:
    """Thread-safe load and save. A corrupt file is kept aside, never silently overwritten."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.settings_file()
        self._lock = threading.Lock()
        self._settings = self._load()

    def _load(self) -> Settings:
        if not self.path.exists():
            settings = Settings()
            self._write(settings)
            return settings
        try:
            return Settings.model_validate(json.loads(self.path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValidationError, OSError):
            backup = self.path.with_suffix(".corrupt.json")
            os.replace(self.path, backup)
            settings = Settings()
            self._write(settings)
            return settings

    def _write(self, settings: Settings) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self) -> Settings:
        with self._lock:
            return self._settings.model_copy(deep=True)

    def update(self, changes: dict[str, Any]) -> Settings:
        unknown = set(changes) - EDITABLE
        if unknown:
            raise ValueError(f"not editable: {', '.join(sorted(unknown))}")
        with self._lock:
            merged = self._settings.model_dump()
            merged.update(changes)
            settings = Settings.model_validate(merged)
            self._write(settings)
            self._settings = settings
            return settings.model_copy(deep=True)

    def set_account_if_missing(self, account_id: int) -> bool:
        """Remember the account seen in GSI; never replaces one he typed in."""
        with self._lock:
            if self._settings.account_id is not None or account_id <= 0:
                return False
            settings = self._settings.model_copy(update={"account_id": account_id})
            self._write(settings)
            self._settings = settings
            return True
