# -*- coding: utf-8 -*-
"""
Automatic cleanup of old Excel export files.

Runs once at app startup.  Deletes export files older than 6 months.
NEVER touches the SQLite database — only Excel files in the export folder.

What gets cleaned:
  - Daily production files:  Productions/YYYY-MM/Week-NN/YYYY-MM-DD/*.xlsx
  - Dashboard snapshots:     Productions/Dashboards/_Dashboard_*.xlsx
  - Empty date/week/month folders left behind after file deletion
"""

import os
import shutil
import time
from datetime import datetime, timedelta

from sync.app_config import load_config
from sync.app_logger import log_event

# Files older than this are deleted
RETENTION_DAYS = 180  # ~6 months

# Marker file so we only run cleanup once per day, not every app restart
_CLEANUP_MARKER = ".last_cleanup"


def _get_designer_dir(export_folder: str) -> str:
    """Return the per-designer folder inside Productions/ for cleanup marker."""
    cfg = load_config()
    designer = cfg.get("designer_name", "Designer").strip() or "Designer"
    safe_name = designer.replace(" ", "_").replace("/", "-")
    designer_dir = os.path.join(export_folder, "Productions", safe_name)
    os.makedirs(designer_dir, exist_ok=True)
    return designer_dir


def _should_run(export_folder: str) -> bool:
    """Return True if cleanup hasn't run today yet."""
    designer_dir = _get_designer_dir(export_folder)
    marker = os.path.join(designer_dir, _CLEANUP_MARKER)
    # Also check old location for migration
    old_marker = os.path.join(export_folder, _CLEANUP_MARKER)
    for m in (marker, old_marker):
        if os.path.exists(m):
            try:
                mtime = os.path.getmtime(m)
                last_run = datetime.fromtimestamp(mtime).date()
                if last_run >= datetime.now().date():
                    return False
            except Exception as exc:
                log_event("cleanup", f"_should_run marker check ({m}): {exc}", level="WARN")
    return True


def _mark_done(export_folder: str):
    """Touch the marker file in the per-designer folder."""
    designer_dir = _get_designer_dir(export_folder)
    marker = os.path.join(designer_dir, _CLEANUP_MARKER)
    try:
        with open(marker, "w") as f:
            f.write(datetime.now().isoformat())
    except Exception as exc:
        log_event("cleanup", f"_mark_done write ({marker}): {exc}", level="WARN")
    # Remove old root-level marker if it exists
    old_marker = os.path.join(export_folder, _CLEANUP_MARKER)
    try:
        if os.path.exists(old_marker):
            os.remove(old_marker)
    except Exception as exc:
        log_event("cleanup", f"_mark_done remove old marker: {exc}", level="WARN")


def _cleanup_daily_productions(productions_dir: str, cutoff: datetime) -> int:
    """Delete daily production Excel files older than cutoff.

    Structure: Productions/YYYY-MM/Week-NN/YYYY-MM-DD/<Designer>_Production_*.xlsx

    After deleting files, removes empty date/week/month folders.
    Returns number of files deleted.
    """
    deleted = 0
    if not os.path.isdir(productions_dir):
        return 0

    for month_folder in os.listdir(productions_dir):
        month_path = os.path.join(productions_dir, month_folder)
        # Skip non-date folders and special files
        if not os.path.isdir(month_path) or month_folder.startswith("_"):
            continue
        # Expect YYYY-MM format
        if len(month_folder) != 7 or month_folder[4] != "-":
            continue

        for week_folder in os.listdir(month_path):
            week_path = os.path.join(month_path, week_folder)
            if not os.path.isdir(week_path):
                continue

            for date_folder in os.listdir(week_path):
                date_path = os.path.join(week_path, date_folder)
                if not os.path.isdir(date_path):
                    continue

                # Parse date from folder name (YYYY-MM-DD)
                try:
                    folder_date = datetime.strptime(date_folder, "%Y-%m-%d")
                except ValueError:
                    continue

                if folder_date < cutoff:
                    # Delete all files in this date folder
                    try:
                        for f in os.listdir(date_path):
                            fp = os.path.join(date_path, f)
                            if os.path.isfile(fp) and fp.endswith(".xlsx"):
                                os.remove(fp)
                                deleted += 1
                        # Remove empty date folder
                        if not os.listdir(date_path):
                            os.rmdir(date_path)
                    except Exception as exc:
                        print(f"[cleanup] Error cleaning {date_path}: {exc}")

            # Remove empty week folder
            try:
                if os.path.isdir(week_path) and not os.listdir(week_path):
                    os.rmdir(week_path)
            except Exception as exc:
                log_event("cleanup", f"rmdir week ({week_path}): {exc}", level="WARN")

        # Remove empty month folder
        try:
            if os.path.isdir(month_path) and not os.listdir(month_path):
                os.rmdir(month_path)
        except Exception as exc:
            log_event("cleanup", f"rmdir month ({month_path}): {exc}", level="WARN")

    return deleted


def _cleanup_dashboard_snapshots(productions_dir: str, cutoff: datetime) -> int:
    """Delete old _Dashboard_YYYY-MM-DD.xlsx snapshots.
    Returns number of files deleted.
    """
    dashboards_dir = os.path.join(productions_dir, "Dashboards")
    if not os.path.isdir(dashboards_dir):
        return 0

    deleted = 0
    for f in os.listdir(dashboards_dir):
        if not f.startswith("_Dashboard_") or not f.endswith(".xlsx"):
            continue
        # Extract date from _Dashboard_YYYY-MM-DD.xlsx
        try:
            date_str = f[len("_Dashboard_"):-len(".xlsx")]
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        if file_date < cutoff:
            try:
                os.remove(os.path.join(dashboards_dir, f))
                deleted += 1
            except Exception as exc:
                print(f"[cleanup] Error deleting {f}: {exc}")

    return deleted


def run_cleanup() -> str:
    """Run cleanup of old Excel export files.

    Called at app startup. Only runs once per day.
    NEVER touches the database.

    Returns a summary message (empty string if skipped).
    """
    cfg = load_config()
    export_folder = cfg.get("export_folder", "").strip()
    if not export_folder or not os.path.isdir(export_folder):
        return ""

    if not _should_run(export_folder):
        return ""

    productions_dir = os.path.join(export_folder, "Productions")
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)

    total_deleted = 0

    # Clean daily production files
    total_deleted += _cleanup_daily_productions(productions_dir, cutoff)

    # Clean dashboard snapshots
    total_deleted += _cleanup_dashboard_snapshots(productions_dir, cutoff)

    _mark_done(export_folder)

    if total_deleted > 0:
        msg = f"[cleanup] Removed {total_deleted} Excel file(s) older than {RETENTION_DAYS} days."
        print(msg)
        return msg
    return ""
