"""Enforces docs/SAFETY.md: no process, input, capture or Windows-API code in the app, and only the
GSI installer writes into the Dota folder."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import d2bg

SRC = Path(d2bg.__file__).resolve().parent
FORBIDDEN_MODULES = {
    "ctypes",
    "pymem",
    "pynput",
    "pyautogui",
    "keyboard",
    "mouse",
    "scapy",
    "pyshark",
    "win32api",
    "win32gui",
    "win32process",
    "win32con",
    "pywinauto",
    "mss",
    "PIL.ImageGrab",
    "psutil",
    "frida",
    "pydivert",
    "interception",
}
FORBIDDEN_CALLS = re.compile(
    r"ReadProcessMemory|WriteProcessMemory|OpenProcess|SendInput|keybd_event|mouse_event|"
    r"SetWindowsHookEx|CreateRemoteThread|VirtualAllocEx|-condebug|coreinit|localconfig\.vdf|"
    r"console\.log|autoexec\.cfg"
)


def _py_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def test_no_forbidden_imports():
    for file in _py_files():
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            for name in names:
                root = name.split(".")[0]
                assert root not in FORBIDDEN_MODULES and name not in FORBIDDEN_MODULES, (
                    f"{file.name}: imports {name}"
                )


def test_no_forbidden_calls_or_files():
    for file in _py_files():
        text = file.read_text(encoding="utf-8")
        if file.name == "test_safety.py":
            continue
        found = FORBIDDEN_CALLS.findall(text)
        assert not found, f"{file.relative_to(SRC)} mentions {found}"


def test_only_the_installer_knows_the_dota_folder():
    for file in _py_files():
        text = file.read_text(encoding="utf-8")
        if "dota 2 beta" in text or "gamestate_integration" in text:
            assert file.name in {"installer.py", "cli.py"}, (
                f"{file.relative_to(SRC)} references the Dota folder"
            )


def test_installer_writes_exactly_one_file_name():
    text = (SRC / "gsi" / "installer.py").read_text(encoding="utf-8")
    assert text.count(".write_text(") == 1
    assert text.count(".unlink(") == 1
    assert 'CONFIG_NAME = "gamestate_integration_d2bg.cfg"' in text


def test_winreg_is_read_only():
    text = (SRC / "gsi" / "installer.py").read_text(encoding="utf-8")
    assert "winreg.SetValue" not in text and "winreg.CreateKey" not in text and "winreg.DeleteKey" not in text
    for file in _py_files():
        if file.name != "installer.py":
            assert "winreg" not in file.read_text(encoding="utf-8"), file.name
