import os

_APP_DIR = "ProductionCalcApp"


def get_local_app_dir(*parts: str) -> str:
    """Return ~\\ProductionCalcApp[\\parts...]  — the local (non-synced) app folder."""
    return os.path.join(os.path.expanduser("~"), _APP_DIR, *parts)
