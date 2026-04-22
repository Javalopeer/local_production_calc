# -*- coding: utf-8 -*-
"""
Small file logger for operational diagnostics.

Keeps a local log under %USERPROFILE%\\ProductionCalcApp\\logs\\app.log.
Logging failures are swallowed to avoid impacting app functionality.
"""

from __future__ import annotations

import os
from datetime import datetime
from sync import get_local_app_dir


_LOG_DIR = get_local_app_dir("logs")
_LOG_FILE = os.path.join(_LOG_DIR, "app.log")


def log_event(source: str, message: str, level: str = "INFO") -> None:
    """Append one structured line to the local log file."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} [{level}] [{source}] {message}\n"
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        with open(_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception as exc:
        import sys
        print(f"[app_logger] write failed: {exc}", file=sys.stderr)
