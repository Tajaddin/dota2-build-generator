"""Install GSI config into Dota 2 game folder."""
import os
import re
import secrets
from pathlib import Path
from typing import Optional

# This install's GSI token, created on first use. Dota sends it with every update.
TOKEN_FILE = Path(__file__).resolve().parent.parent / "data" / "gsi_token"


def load_or_create_token(path: Optional[Path] = None) -> str:
    """Read this install's GSI token, creating a random one the first time."""
    path = path or TOKEN_FILE
    try:
        token = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        token = ""
    if not token:
        token = secrets.token_urlsafe(24)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token, encoding="utf-8")
    return token


GSI_CONFIG = '''"dota2-build-generator"
{
    "uri"               "http://127.0.0.1:4001/"
    "timeout"           "5.0"
    "buffer"            "0.1"
    "throttle"          "0.5"
    "heartbeat"         "30.0"
    "auth"
    {
        "token"         "__BUILDGEN_AUTH_TOKEN__"
    }
    "data"
    {
        "provider"      "1"
        "map"           "1"
        "player"        "1"
        "hero"          "1"
        "abilities"     "1"
        "items"         "1"
        "draft"         "1"
        "allplayers"    "1"
        "allheroes"     "1"
    }
}
'''

CONFIG_FILENAME = "gamestate_integration_buildgen.cfg"

# Common Dota 2 install paths on Windows
COMMON_PATHS = [
    Path(r"C:\Program Files (x86)\Steam\steamapps\common\dota 2 beta"),
    Path(r"C:\Program Files\Steam\steamapps\common\dota 2 beta"),
    Path(r"D:\Steam\steamapps\common\dota 2 beta"),
    Path(r"D:\SteamLibrary\steamapps\common\dota 2 beta"),
    Path(r"E:\Steam\steamapps\common\dota 2 beta"),
    Path(r"E:\SteamLibrary\steamapps\common\dota 2 beta"),
    Path(r"F:\Steam\steamapps\common\dota 2 beta"),
    Path(r"F:\SteamLibrary\steamapps\common\dota 2 beta"),
    Path(r"G:\Steam\steamapps\common\dota 2 beta"),
    Path(r"G:\SteamLibrary\steamapps\common\dota 2 beta"),
]


def find_dota2_path() -> Optional[Path]:
    """Try to find the Dota 2 installation directory."""
    for p in COMMON_PATHS:
        if p.exists():
            return p

    # Try reading Steam's libraryfolders.vdf
    steam_paths_to_try = [
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Steam",
        Path(os.environ.get("ProgramFiles", "")) / "Steam",
    ]
    # Also check Steam on all drive letters
    for drive in "CDEFGH":
        steam_paths_to_try.append(Path(f"{drive}:\\Steam"))
        steam_paths_to_try.append(Path(f"{drive}:\\SteamLibrary"))

    for steam_path in steam_paths_to_try:
        vdf_path = steam_path / "steamapps" / "libraryfolders.vdf"
        if vdf_path.exists():
            try:
                with open(vdf_path, "r") as f:
                    content = f.read()
                paths = re.findall(r'"path"\s+"([^"]+)"', content)
                for lib_path in paths:
                    dota_path = Path(lib_path) / "steamapps" / "common" / "dota 2 beta"
                    if dota_path.exists():
                        return dota_path
            except Exception:
                pass

    return None


def install_gsi_config(dota2_path: Optional[Path] = None) -> tuple[bool, str]:
    """Install the GSI config file.

    Returns:
        (success, message) tuple
    """
    if dota2_path is None:
        dota2_path = find_dota2_path()

    if dota2_path is None:
        return False, "Could not find Dota 2 installation. Please provide the path manually."

    cfg_dir = dota2_path / "game" / "dota" / "cfg" / "gamestate_integration"
    try:
        cfg_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        return False, f"Permission denied creating directory: {cfg_dir}"

    cfg_file = cfg_dir / CONFIG_FILENAME
    try:
        with open(cfg_file, "w", encoding="utf-8") as f:
            f.write(GSI_CONFIG.replace("__BUILDGEN_AUTH_TOKEN__", load_or_create_token()))
    except PermissionError:
        return False, f"Permission denied writing file: {cfg_file}"

    return True, f"GSI config installed to {cfg_file}"


def is_gsi_installed(dota2_path: Optional[Path] = None) -> bool:
    """Check if GSI config is already installed."""
    if dota2_path is None:
        dota2_path = find_dota2_path()
    if dota2_path is None:
        return False
    cfg_file = dota2_path / "game" / "dota" / "cfg" / "gamestate_integration" / CONFIG_FILENAME
    return cfg_file.exists()


def is_gsi_outdated(dota2_path: Optional[Path] = None) -> bool:
    """Check if installed GSI config is missing required fields from latest template,
    or carries another token than this install's."""
    if dota2_path is None:
        dota2_path = find_dota2_path()
    if dota2_path is None:
        return False
    cfg_file = dota2_path / "game" / "dota" / "cfg" / "gamestate_integration" / CONFIG_FILENAME
    if not cfg_file.exists():
        return False
    try:
        content = cfg_file.read_text(encoding="utf-8")
        required_fields = [
            '"auth"',
            '"buffer"            "0.1"',
            '"allplayers"',
            '"allheroes"',
            f'"{load_or_create_token()}"',
        ]
        return any(field not in content for field in required_fields)
    except Exception:
        return False
