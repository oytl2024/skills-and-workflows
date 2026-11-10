"""Read-only, offline desktop host inventory. Never imports GUI hosts or starts services."""
from __future__ import annotations

from importlib import metadata
import json
import os
from pathlib import Path
import platform
import struct
import sys


PACKAGES = ("pywebview", "pythonnet", "clr-loader", "pyinstaller", "nuitka", "PySide6", "PyQt6")
REQUIRED_PACKAGES = ("pywebview", "pythonnet", "pyinstaller")
MAX_REGISTRY_CLIENTS = 64


def webview2_inventory() -> list[dict]:
    """Input: none. Output: list[dict]. Read bounded WebView2 registration, not browser profiles."""
    if os.name != "nt":
        return []
    import winreg
    found = []
    for hive, scope in ((winreg.HKEY_CURRENT_USER, "user"), (winreg.HKEY_LOCAL_MACHINE, "machine")):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\EdgeUpdate\Clients", 0,
                                    winreg.KEY_READ | view) as clients:
                    for index in range(min(winreg.QueryInfoKey(clients)[0], MAX_REGISTRY_CLIENTS)):
                        try:
                            with winreg.OpenKey(clients, winreg.EnumKey(clients, index)) as client:
                                name = winreg.QueryValueEx(client, "name")[0]
                                version = winreg.QueryValueEx(client, "pv")[0]
                            if (isinstance(name, str) and "webview2" in name.lower()
                                    and valid_version(version)):
                                item = {"scope": scope, "version": version}
                                if item not in found:
                                    found.append(item)
                        except OSError:
                            continue
            except OSError:
                continue
    return found


def valid_version(value: object) -> bool:
    """Input: arbitrary registry value. Output: bool. Reject empty/zero/non-numeric runtime versions."""
    return (isinstance(value, str) and value.isascii() and len(value) <= 64 and 1 < len(value.split(".")) <= 4
            and all(part.isdigit() for part in value.split("."))
            and any(int(part) > 0 for part in value.split(".")))


def dotnet_inventory() -> dict:
    """Input: none. Output: dict. Read .NET Framework release registration without loading CLR."""
    if os.name == "nt":
        import winreg
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                    r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full", 0,
                                    winreg.KEY_READ | view) as key:
                    release = winreg.QueryValueEx(key, "Release")[0]
                if isinstance(release, int):
                    return {"status": "registered", "release": release, "load_verified": False}
            except OSError:
                continue
    return {"status": "unavailable", "load_verified": False}


def assess_host(inventory: dict) -> dict:
    """Input: local inventory dict. Output: dict. Separate candidate dependencies from build acceptance."""
    packages = inventory.get("packages", {})
    missing = [name for name in REQUIRED_PACKAGES if not packages.get(name)]
    if not any(isinstance(item, dict) and valid_version(item.get("version"))
               for item in inventory.get("webview2", [])):
        missing.append("WebView2")
    dotnet = inventory.get("dotnet", {})
    if dotnet.get("status") != "registered" or not isinstance(dotnet.get("release"), int) or dotnet["release"] <= 0:
        missing.append(".NET Framework")
    return {
        "candidate": "pywebview + PyInstaller + system WebView2",
        "candidate_status": "provisional; dependency/stack approval and runtime/build smoke still required",
        "missing": missing,
        "dependencies_present": inventory.get("system") == "Windows" and not missing,
        "runtime_load_verified": False,
        "packaged_exe_verified": False,
        "no_admin": "Per-user/portable deployment candidate only; not deployment proof. Existing WebView2/.NET required.",
        "download": {"performed": False, "size_bytes": None,
                     "approval": "Resolve exact pinned wheels, transitive native DLLs and sizes before installation; offline size unknown."},
        "packaged_entry": {
            "current": "Source python -m wqb.cli launch-console requires installed Python; not a frozen entry.",
            "required": "Explicit frozen --backend dispatch to existing CLI in same EXE, or bundled backend helper; never EXE -m.",
            "implemented": False,
        },
    }


def validate_launch(application_root: Path, asset: str, command: list[str], *,
                    frozen: bool, expected: dict, health: dict) -> dict:
    """Input: fixture root/asset/argv, mode bool, identity dicts. Output: dict. Validate proposed launch only."""
    root = application_root.resolve()
    path = (root / asset).resolve()
    assets_valid = (not Path(asset).is_absolute() and path.is_relative_to(root) and path.is_file())
    identity_keys = ("app", "workflow_root", "knowledge_root", "runs_root", "code_revision")
    owned = expected.get("app") == "BrainWorkflow" and all(
        isinstance(expected.get(key), str) and bool(expected[key])
        and health.get(key) == expected[key] for key in identity_keys)
    owned = owned and isinstance(health.get("server_revision"), str) and bool(health["server_revision"].strip())
    if frozen:
        entry = (len(command) >= 2 and Path(command[0]).suffix.lower() == ".exe"
                 and Path(command[0]).name.lower() not in {"python.exe", "pythonw.exe"}
                 and command[1] == "--backend" and "-m" not in command)
    else:
        entry = len(command) >= 4 and command[1:4] == ["-m", "wqb.cli", "launch-console"]
    return {"assets_valid": assets_valid, "health_owned": bool(owned), "entry_valid": entry,
            "packaged_exe_verified": False}


def probe_host() -> dict:
    """Input: none. Output: JSON-safe dict. Inventory current Python/host metadata without imports or launch."""
    packages = {}
    versions = {}
    for name in PACKAGES:
        try:
            version = metadata.version(name)
            packages[name] = {"status": "installed", "version": version}
            versions[name] = version
        except Exception:
            # Exception text may contain private paths; absence and broken metadata both fail closed.
            packages[name] = {"status": "unavailable"}
    inventory = {"schema_version": 1, "system": platform.system(),
                 "python": {"version": platform.python_version(), "bits": struct.calcsize("P") * 8,
                            "executable_exists": Path(sys.executable).is_file(),
                            "frozen": bool(getattr(sys, "frozen", False))},
                 "packages": packages, "webview2": webview2_inventory(), "dotnet": dotnet_inventory(),
                 "safety": {"offline": True, "host_imports": False, "processes_started": False,
                            "installs": False, "writes": False, "secrets_read": False}}
    inventory["assessment"] = assess_host(dict(inventory, packages=versions))
    return inventory


if __name__ == "__main__":
    print(json.dumps(probe_host(), indent=2, ensure_ascii=True))
