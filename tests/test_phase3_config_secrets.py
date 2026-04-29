import json
import os
import shutil
import sys
import uuid
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _mk_temp_base() -> Path:
    base = Path(ROOT) / "tests_tmp_phase3" / f"run_{uuid.uuid4().hex}"
    base.mkdir(parents=True, exist_ok=True)
    return base


# Teams webhook config was removed when the manual copy-paste flow replaced
# the Power Automate / Adaptive Card approval pipeline.


def test_get_excel_sheet_password_fallback_chain(monkeypatch):
    import sync.app_config as ac

    monkeypatch.delenv(ac.ENV_EXCEL_SHEET_PASSWORD, raising=False)
    monkeypatch.setattr(ac, "_load_shared_config", lambda _: {"excel_sheet_password": "shared_pw"})

    monkeypatch.setattr(ac, "load_config", lambda: {"excel_sheet_password": "local_pw", "export_folder": "X"})
    assert ac.get_excel_sheet_password() == "local_pw"

    monkeypatch.setattr(ac, "load_config", lambda: {"excel_sheet_password": "", "export_folder": "X"})
    assert ac.get_excel_sheet_password() == "shared_pw"

    monkeypatch.setattr(ac, "_load_shared_config", lambda _: {})
    assert ac.get_excel_sheet_password() == ""  # no password configured → empty string

    monkeypatch.setenv(ac.ENV_EXCEL_SHEET_PASSWORD, "env_pw")
    assert ac.get_excel_sheet_password() == "env_pw"


def test_save_shared_config_uses_loaded_export_folder(monkeypatch):
    import sync.app_config as ac

    base = _mk_temp_base()
    try:
        monkeypatch.setattr(ac, "load_config", lambda: {"export_folder": str(base)})
        ok = ac.save_shared_config({"excel_sheet_password": "shared_pw"})
        assert ok is True

        shared_file = base / "_shared_config.json"
        assert shared_file.exists()
        data = json.loads(shared_file.read_text(encoding="utf-8"))
        assert data["excel_sheet_password"] == "shared_pw"
    finally:
        shutil.rmtree(base, ignore_errors=True)
