"""Where the app reads and writes files.

- The committed data snapshot (read only): ``data/snapshot`` in a checkout, or the copy bundled in the
  wheel. ``D2BG_SNAPSHOT_DIR`` overrides it.
- Curated knowledge files (read only): ``data/knowledge``.
- The user folder (settings, API cache, refreshed data, GSI recordings): ``%LOCALAPPDATA%\\d2bg`` on
  Windows. ``D2BG_HOME`` overrides it, which is what the tests use.
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_dir

_PACKAGE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE_DIR.parent.parent


def repo_root() -> Path:
    return _REPO_ROOT


def snapshot_dir() -> Path:
    env = os.environ.get("D2BG_SNAPSHOT_DIR")
    if env:
        return Path(env)
    in_repo = _REPO_ROOT / "data" / "snapshot"
    if in_repo.is_dir():
        return in_repo
    return _PACKAGE_DIR / "_snapshot"


def knowledge_dir() -> Path:
    env = os.environ.get("D2BG_KNOWLEDGE_DIR")
    if env:
        return Path(env)
    return snapshot_dir().parent / "knowledge"


def user_dir() -> Path:
    env = os.environ.get("D2BG_HOME")
    path = Path(env) if env else Path(user_data_dir("d2bg", appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sub(name: str) -> Path:
    path = user_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def refreshed_data_dir() -> Path:
    return _sub("data")


def cache_dir() -> Path:
    return _sub("cache")


def recordings_dir() -> Path:
    return _sub("recordings")


def settings_file() -> Path:
    return user_dir() / "settings.json"


def web_dist_dir() -> Path:
    """The built UI. ``npm run build`` in ``web/`` writes it here."""
    return _PACKAGE_DIR / "static"
