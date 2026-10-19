"""Find Dota 2 and write (or remove) this app's Game State Integration config.

This is the only module that writes inside the Dota 2 folder, and it only ever touches one file:
``game/dota/cfg/gamestate_integration/gamestate_integration_d2bg.cfg``. Finding Dota reads Steam's
``libraryfolders.vdf`` and, on Windows, the ``SteamPath`` registry value; both are read only.
"""

from __future__ import annotations

import contextlib
import os
import re
import sys
from pathlib import Path

CONFIG_NAME = "gamestate_integration_d2bg.cfg"
CFG_SUBDIR = Path("game") / "dota" / "cfg" / "gamestate_integration"
DOTA_DIR = Path("steamapps") / "common" / "dota 2 beta"

# Blocks requested from the game. While playing, Dota sends only the local player's data; the
# spectator-only blocks are simply absent.
DATA_BLOCKS = (
    "provider",
    "map",
    "player",
    "hero",
    "abilities",
    "items",
    "draft",
    "events",
    "buildings",
    "wearables",
    "league",
    "roshan",
    "couriers",
    "neutralitems",
    "minimap",
)


def render_config(port: int, token: str, throttle: float = 0.25) -> str:
    data = "\n".join(f'        "{b}"{" " * max(1, 16 - len(b))}"1"' for b in DATA_BLOCKS)
    return (
        '"d2bg"\n'
        "{\n"
        f'    "uri"               "http://127.0.0.1:{port}/gsi"\n'
        '    "timeout"           "5.0"\n'
        '    "buffer"            "0.1"\n'
        f'    "throttle"          "{throttle}"\n'
        '    "heartbeat"         "10.0"\n'
        '    "auth"\n'
        "    {\n"
        f'        "token"         "{token}"\n'
        "    }\n"
        '    "data"\n'
        "    {\n"
        f"{data}\n"
        "    }\n"
        "}\n"
    )


def _registry_steam_path() -> Path | None:
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            value, _ = winreg.QueryValueEx(key, "SteamPath")
            return Path(str(value))
    except OSError:
        return None


def steam_roots() -> list[Path]:
    roots: list[Path] = []
    reg = _registry_steam_path()
    if reg:
        roots.append(reg)
    for env in ("ProgramFiles(x86)", "ProgramFiles"):
        if os.environ.get(env):
            roots.append(Path(os.environ[env]) / "Steam")
    roots.append(Path.home() / ".steam" / "steam")
    roots.append(Path.home() / ".local" / "share" / "Steam")
    seen, out = set(), []
    for r in roots:
        key = str(r).lower()
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def library_folders(vdf_text: str) -> list[Path]:
    return [Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', vdf_text)]


def find_dota(extra_roots: list[Path] | None = None) -> Path | None:
    """The ``dota 2 beta`` folder, from Steam's library list."""
    candidates: list[Path] = []
    for root in [*(extra_roots or []), *steam_roots()]:
        candidates.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            with contextlib.suppress(OSError):
                candidates.extend(library_folders(vdf.read_text(encoding="utf-8", errors="replace")))
    for lib in candidates:
        dota = lib / DOTA_DIR
        if (dota / "game" / "dota").is_dir():
            return dota
    return None


def config_path(dota: Path) -> Path:
    return dota / CFG_SUBDIR / CONFIG_NAME


def install(dota: Path, port: int, token: str) -> Path:
    if not (dota / "game" / "dota").is_dir():
        raise FileNotFoundError(f"{dota} does not look like a Dota 2 install (no game/dota folder)")
    target = config_path(dota)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_config(port, token), encoding="utf-8")
    return target


def remove(dota: Path) -> bool:
    target = config_path(dota)
    if target.is_file():
        target.unlink()
        return True
    return False


def status(dota: Path | None, port: int, token: str) -> dict[str, object]:
    if dota is None:
        return {"dota_found": False, "installed": False, "current": False, "path": None}
    target = config_path(dota)
    installed = target.is_file()
    current = installed and target.read_text(encoding="utf-8", errors="replace") == render_config(port, token)
    return {
        "dota_found": True,
        "dota_path": str(dota),
        "installed": installed,
        "current": current,
        "path": str(target),
    }
