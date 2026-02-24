"""
Manages persistent app configuration (designer name, SharePoint export folder).
Config file: C:\\Users\\<user>\\ProductionCalcApp\\config.json
"""
import json
import os
import getpass

_CONFIG_PATH = os.path.join(os.path.expanduser("~"), "ProductionCalcApp", "config.json")
_DEFAULTS = {
    "designer_name": getpass.getuser(),
    "export_folder": "",   # filled by the user on first sync
}


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
    return cfg


def save_config(cfg: dict) -> None:
    """Persist the config dict to disk."""
    os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def is_configured() -> bool:
    """Return True if the export folder has been set."""
    return bool(load_config().get("export_folder", "").strip())
