"""
Manages persistent app configuration (designer name, SharePoint export folder).
Config file: C:\\Users\\<user>\\ProductionCalcApp\\config.json
"""
import json
import os
import getpass

_CONFIG_PATH = os.path.join(os.path.expanduser("~"), "ProductionCalcApp", "config.json")

def get_windows_display_name() -> str:
    """Return the Windows full display name (e.g. 'Gerardo Gomez').
    Falls back to the login username if not available."""
    try:
        import ctypes
        GetUserNameEx = ctypes.windll.secur32.GetUserNameExW
        NameDisplay = 3
        size = ctypes.pointer(ctypes.c_ulong(0))
        GetUserNameEx(NameDisplay, None, size)
        buf = ctypes.create_unicode_buffer(size.contents.value)
        if GetUserNameEx(NameDisplay, buf, size) and buf.value:
            return buf.value
    except Exception:
        pass
    return getpass.getuser()
def _default_export_folder() -> str:
    """Try to auto-detect the Teams/SharePoint-synced Reports folder.

    The Teams sync folder is always directly under C:\\Users\\<user>\\<OrgName>\\
    and does NOT contain 'OneDrive' in its path — that would be the personal
    OneDrive which is the wrong target.
    """
    import glob
    user = getpass.getuser()

    # Explicit known patterns for Teams SharePoint sync (no OneDrive in path)
    candidates = [
        os.path.join("C:\\Users", user, "Envista", "SPARK-GLB-OPS-ICON - Reports"),
        os.path.join("C:\\Users", user, "Envista", "SPARK-GLB-OPS-ICON - Daily Production", "Reports"),
    ]


    for pattern in [
        os.path.join("C:\\Users", user, "Envista", "*Reports*"),
        os.path.join("C:\\Users", user, "Envista", "*", "Reports"),
    ]:
        for p in glob.glob(pattern):
            if "onedrive" not in p.lower():
                candidates.append(p)

    for path in candidates:
        if "onedrive" not in path.lower() and os.path.isdir(path):
            return path
    return ""


_DEFAULTS = {
    "designer_name": "",        
    "name_confirmed": False,   
    "export_folder": "",
    "auto_sync_hours": 0,
    "teams_webhook": "",
}


def _load_shared_config(export_folder: str) -> dict:
    """Read _shared_config.json from the shared Reports folder.
    This file contains team-wide settings like the webhook URL."""
    if not export_folder:
        return {}
    shared_path = os.path.join(export_folder, "_shared_config.json")
    if os.path.exists(shared_path):
        try:
            with open(shared_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_shared_config(cfg: dict) -> bool:
    """Save team-wide settings to _shared_config.json in the shared folder."""
    export_folder = cfg.get("export_folder", "").strip()
    if not export_folder or not os.path.isdir(export_folder):
        return False
    shared_path = os.path.join(export_folder, "_shared_config.json")
    try:
        with open(shared_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def load_config() -> dict:
    """Return the config dict (merged with defaults for any missing keys)."""
    cfg = dict(_DEFAULTS)
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                stored = json.load(f)
            cfg.update(stored)
        except Exception:
            pass
    # Auto-detect export folder if not set yet
    if not cfg.get("export_folder"):
        cfg["export_folder"] = _default_export_folder()
    # Pre-fill designer name from Windows if never set
    if not cfg.get("designer_name"):
        cfg["designer_name"] = get_windows_display_name()
    # Auto-load teams_webhook from shared config if not set locally
    if not cfg.get("teams_webhook"):
        shared = _load_shared_config(cfg.get("export_folder", ""))
        if shared.get("teams_webhook"):
            cfg["teams_webhook"] = shared["teams_webhook"]
    return cfg


def save_config(cfg: dict) -> None:
    """Persist the config dict to disk."""
    os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def is_configured() -> bool:
    """Return True if the export folder has been set."""
    return bool(load_config().get("export_folder", "").strip())
