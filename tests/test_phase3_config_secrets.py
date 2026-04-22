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


def test_get_teams_webhook_env_priority(monkeypatch):
    import sync.app_config as ac

    monkeypatch.setenv(ac.ENV_TEAMS_WEBHOOK, "https://env.example/hook")
    monkeypatch.setattr(ac, "load_config", lambda: {"teams_webhook": "https://local.example/hook"})
    assert ac.get_teams_webhook_url() == "https://env.example/hook"


def test_get_teams_webhook_local_then_shared(monkeypatch):
    import sync.app_config as ac

    monkeypatch.delenv(ac.ENV_TEAMS_WEBHOOK, raising=False)

    local_cfg = {"teams_webhook": "https://local.example/hook", "export_folder": "X"}
    monkeypatch.setattr(ac, "load_config", lambda: local_cfg)
    monkeypatch.setattr(ac, "_load_shared_config", lambda _: {"teams_webhook": "https://shared.example/hook"})
    assert ac.get_teams_webhook_url() == "https://local.example/hook"

    local_cfg_empty = {"teams_webhook": "", "export_folder": "X"}
    monkeypatch.setattr(ac, "load_config", lambda: local_cfg_empty)
    assert ac.get_teams_webhook_url() == "https://shared.example/hook"


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
        ok = ac.save_shared_config({"teams_webhook": "https://shared.example/hook"})
        assert ok is True

        shared_file = base / "_shared_config.json"
        assert shared_file.exists()
        data = json.loads(shared_file.read_text(encoding="utf-8"))
        assert data["teams_webhook"] == "https://shared.example/hook"
    finally:
        shutil.rmtree(base, ignore_errors=True)
