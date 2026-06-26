"""Auto-restart main.py whenever a Python source file changes.

Usage:
    python tools/dev_watch.py

Watches main.py, tabs/, db/, sync/ for .py changes. On any save, kills the
running app and relaunches. Cross-platform, no external deps.

Hit Ctrl+C in the terminal to stop watching.
"""
import os
import sys
import signal
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WATCH_DIRS = ["tabs", "db", "sync"]
WATCH_FILES = ["main.py"]
POLL_INTERVAL = 0.6  # seconds


def snapshot() -> dict:
    """Return {path: mtime} for every watched .py file."""
    snap = {}
    for rel in WATCH_FILES:
        p = ROOT / rel
        if p.exists():
            snap[str(p)] = p.stat().st_mtime
    for d in WATCH_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            try:
                snap[str(p)] = p.stat().st_mtime
            except OSError:
                pass
    return snap


def launch() -> subprocess.Popen:
    print("\n[dev-watch] starting main.py …", flush=True)
    return subprocess.Popen(
        [sys.executable, str(ROOT / "main.py")],
        cwd=str(ROOT),
    )


def kill(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    print("[dev-watch] reloading …", flush=True)
    try:
        if os.name == "nt":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            pass


def diff(old: dict, new: dict) -> list:
    """Return list of files whose mtime changed (or are added/removed)."""
    changed = []
    keys = set(old) | set(new)
    for k in keys:
        if old.get(k) != new.get(k):
            changed.append(k)
    return changed


def main():
    print(f"[dev-watch] root = {ROOT}")
    print(f"[dev-watch] watching {WATCH_FILES} + {WATCH_DIRS}/**/*.py")
    print("[dev-watch] save any .py file to trigger reload. Ctrl+C to stop.\n")

    last = snapshot()
    proc = launch()

    try:
        while True:
            time.sleep(POLL_INTERVAL)
            # auto-relaunch if app crashed or user closed the window
            if proc.poll() is not None:
                print("[dev-watch] app exited — waiting for next file change to restart.", flush=True)
                # block here until something changes (don't spin restart on crash)
                while True:
                    time.sleep(POLL_INTERVAL)
                    cur = snapshot()
                    if diff(last, cur):
                        last = cur
                        proc = launch()
                        break
                continue

            cur = snapshot()
            changed = diff(last, cur)
            if changed:
                shown = ", ".join(os.path.relpath(c, ROOT) for c in changed[:3])
                more = f" (+{len(changed)-3} more)" if len(changed) > 3 else ""
                print(f"[dev-watch] change detected: {shown}{more}", flush=True)
                last = cur
                kill(proc)
                proc = launch()
    except KeyboardInterrupt:
        print("\n[dev-watch] stopping.")
        kill(proc)


if __name__ == "__main__":
    main()
