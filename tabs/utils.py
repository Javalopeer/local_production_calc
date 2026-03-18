"""
Shared utilities for all tabs.

Centralises:
  - get_resource_path / get_writable_path  (were copy-pasted in every tab)
  - calculate_case_value                   (was duplicated in register + overtime)
  - load_units_eq_data / get_units_per_case (were duplicated in 4 tabs, re-read disk each time)
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Dict

# ── Path helpers ──────────────────────────────────────────────────────────────

def get_resource_path(relative_path: str) -> str:
    """Absolute path to a read-only resource (works in dev and frozen .exe)."""
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        candidate = os.path.join(exe_dir, relative_path)
        if os.path.exists(candidate):
            return candidate
        # PyInstaller bundles data in _MEIPASS
        return os.path.join(sys._MEIPASS, relative_path)  # type: ignore[attr-defined]
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)


def get_writable_path(relative_path: str) -> str:
    """Absolute path for files that must be writable (config, data, etc.)."""
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        return os.path.join(exe_dir, relative_path)
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)


# ── Production formula ────────────────────────────────────────────────────────

DAILY_BASE_MINUTES: float = 408.3  # single source of truth for the base
DAILY_TARGET_EQ_UNITS: float = 15.0


def calculate_case_value(std_time: float) -> float:
    """Convert a standard time (minutes) to a production % value.

    Formula: (std_time / 408.3) * 100
    """
    if not std_time:
        return 0.0
    return (std_time / DAILY_BASE_MINUTES) * 100


def calculate_downtime_equivalent_units(
    downtime_minutes: float,
    target_daily_units: float = DAILY_TARGET_EQ_UNITS,
) -> float:
    """Convert downtime minutes to equivalent units.

    Formula: (downtime_minutes / DAILY_BASE_MINUTES) * target_daily_units
    """
    try:
        minutes = float(downtime_minutes or 0.0)
    except (TypeError, ValueError):
        minutes = 0.0
    if minutes <= 0:
        return 0.0
    return (minutes / DAILY_BASE_MINUTES) * float(target_daily_units)


# ── Units Equivalent data (module-level cache) ────────────────────────────────

_units_eq_cache: Dict[str, Dict[str, float]] | None = None


def load_units_eq_data(force: bool = False) -> Dict[str, Dict[str, float]]:
    """Load units_eq.json once and cache in memory.

    Call with force=True after the user saves changes in the Standards tab
    so every tab picks up the fresh values without restarting the app.
    """
    global _units_eq_cache
    if _units_eq_cache is None or force:
        path = get_resource_path(os.path.join("data", "units_eq.json"))
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                _units_eq_cache = json.load(fh)
        except Exception as exc:
            print(f"[utils] Could not load units_eq.json: {exc}")
            _units_eq_cache = {}
    return _units_eq_cache


def _norm(s: str) -> str:
    """Normalise a region name for fuzzy matching (lower-case, alphanum only)."""
    return re.sub(r"[^a-z0-9]", "", s.lower()) if s else ""


def get_units_per_case(
    units_eq: Dict[str, Dict[str, float]],
    region: str,
    case_type: str | None,
) -> float:
    """Return the UE value for one case given its region and case type.

    Lookup order:
      1. Exact region + exact case_type
      2. Exact region + first available type  (fallback)
      3. Fuzzy region match + exact case_type
      4. Fuzzy region match + first available type
      5. 0.0

    Args:
        units_eq:  The loaded dict (from load_units_eq_data()).
        region:    Region string stored in the database.
        case_type: Case type string (e.g. "Primary", "Stage RX CR").
    """
    if not region:
        return 0.0

    def _lookup(reg_dict: Dict[str, float]) -> float:
        if case_type and case_type in reg_dict:
            return reg_dict[case_type]
        if reg_dict:
            return next(iter(reg_dict.values()))
        return 0.0

    # 1 & 2 — exact region key
    if region in units_eq:
        return _lookup(units_eq[region])

    # 3 & 4 — tolerant matching (remove common suffixes, then fuzzy)
    alt = region.replace(" & Canada", "").replace("Regions ", "").strip()
    rnorm = _norm(region)

    for key, reg_dict in units_eq.items():
        key_alt = key.replace("Regions ", "").strip()
        if key_alt == alt or key == alt:
            return _lookup(reg_dict)

    for key, reg_dict in units_eq.items():
        knorm = _norm(key)
        if knorm and (knorm in rnorm or rnorm in knorm):
            return _lookup(reg_dict)

    return 0.0


def _safe_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_region_units(
    units_eq: Dict[str, Dict[str, float]],
    region: str,
) -> Dict[str, float] | None:
    if not region:
        return None

    if region in units_eq and isinstance(units_eq[region], dict):
        return units_eq[region]

    alt = region.replace(" & Canada", "").replace("Regions ", "").strip()
    rnorm = _norm(region)

    for key, reg_dict in units_eq.items():
        if not isinstance(reg_dict, dict):
            continue
        key_alt = key.replace("Regions ", "").strip()
        if key_alt == alt or key == alt:
            return reg_dict

    for key, reg_dict in units_eq.items():
        if not isinstance(reg_dict, dict):
            continue
        knorm = _norm(key)
        if knorm and (knorm in rnorm or rnorm in knorm):
            return reg_dict

    return None


def calculate_equivalent_units(
    units_eq: Dict[str, Dict[str, float]],
    region: str,
    case_type: str | None,
    case_value: float,
    count: int = 1,
) -> float:
    """Calculate equivalent units supporting both UE models.

    Supported models:
      1) Legacy base-rate model: region has keys like "100", "95", ...
         UE = case_value% * base_rate / 100
      2) Per-case model: region has explicit keys by type (e.g. "Primary": 1.15)
         UE = count * per_case_ue
    """
    reg_dict = _resolve_region_units(units_eq, region)
    if not reg_dict:
        return 0.0

    safe_count = max(1, int(count or 1))

    if case_type and case_type in reg_dict:
        explicit = _safe_float(reg_dict.get(case_type))
        if explicit is not None:
            return safe_count * explicit

    base_rate = _safe_float(reg_dict.get("100"))
    if base_rate is None:
        fallback = get_units_per_case(units_eq, region, case_type)
        base_rate = _safe_float(fallback) or 0.0

    cv = _safe_float(case_value) or 0.0
    return safe_count * cv * base_rate / 100.0
