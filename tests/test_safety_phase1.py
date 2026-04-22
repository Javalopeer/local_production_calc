import json
import os
import shutil
import sqlite3
import sys
import uuid
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _setup_dt_db(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS downtimes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT,
            hora_inicio TEXT,
            hora_fin TEXT,
            razon TEXT,
            duracion REAL,
            status TEXT DEFAULT 'pending',
            detalle TEXT DEFAULT '',
            responded_by TEXT DEFAULT '',
            responded_at TEXT DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        INSERT INTO downtimes (id, fecha, hora_inicio, hora_fin, razon, duracion, status, detalle, responded_by, responded_at)
        VALUES (1, '2026-04-15', '11:00', '11:05', 'CMS Down', 5, 'pending', '', '', '')
        """
    )
    conn.commit()


def _mk_temp_base() -> Path:
    base = Path(ROOT) / "tests_tmp_phase1" / f"run_{uuid.uuid4().hex}"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _mem_uri(name: str) -> str:
    return f"file:{name}?mode=memory&cache=shared"


def test_teams_notify_payload_contract(monkeypatch):
    import sync.teams_notify as tn

    monkeypatch.setattr(tn, "get_teams_webhook_url", lambda: "https://example.test/hook")

    captured = {}

    class _Resp:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["body"] = req.data
        return _Resp()

    monkeypatch.setattr(tn.urllib.request, "urlopen", _fake_urlopen)

    ok = tn.notify_downtime_submitted(
        designer="Ana",
        fecha="2026-04-15",
        start="11:00",
        end="11:05",
        duration=5,
        reason="CMS Down",
        detalle="test detail",
        dt_id=99,
    )

    assert ok is True
    assert captured["url"] == "https://example.test/hook"
    assert captured["timeout"] == 10

    payload = json.loads(captured["body"].decode("utf-8"))
    assert set(payload.keys()) == {
        "designer",
        "fecha",
        "start",
        "end",
        "duration",
        "reason",
        "detalle",
        "dt_id",
        "summary",
        "time_range",
    }
    assert payload["designer"] == "Ana"
    assert payload["dt_id"] == 99
    assert payload["reason"] == "CMS Down"


def test_poll_teams_responses_updates_pending(monkeypatch):
    import sync.downtime_approval as da

    base = _mk_temp_base()
    keepalive = None
    try:
        mem_name = f"dt_{uuid.uuid4().hex}"
        uri = _mem_uri(mem_name)
        keepalive = sqlite3.connect(uri, uri=True)
        _setup_dt_db(keepalive)

        root = base / "export"
        responses = root / "responses"
        responses.mkdir(parents=True, exist_ok=True)
        (responses / "response_1.json").write_text(
            json.dumps(
                {
                    "dt_id": 1,
                    "decision": "✅ Approve",
                    "designer": "Ana",
                    "responded_by": "Supervisor",
                    "responded_at": "2026-04-15T12:00:00Z",
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(da, "_get_downtime_dir", lambda: str(root))
        monkeypatch.setattr(da, "get_connection", lambda: sqlite3.connect(uri, uri=True))
        monkeypatch.setattr(da, "_processed_response_files", set())
        monkeypatch.setattr(da, "_save_processed_responses", lambda processed: None)

        updated = da._poll_teams_responses("Ana")
        assert updated == 1

        conn = sqlite3.connect(uri, uri=True)
        row = conn.execute(
            "SELECT status, responded_by, responded_at FROM downtimes WHERE id = 1"
        ).fetchone()
        conn.close()
        assert row[0] == "approved"
        assert row[1] == "Supervisor"
        assert "2026-04-15" in row[2]
    finally:
        if keepalive is not None:
            keepalive.close()
        shutil.rmtree(base, ignore_errors=True)


def test_poll_teams_responses_respects_designer_filter(monkeypatch):
    import sync.downtime_approval as da

    base = _mk_temp_base()
    keepalive = None
    try:
        mem_name = f"dt_{uuid.uuid4().hex}"
        uri = _mem_uri(mem_name)
        keepalive = sqlite3.connect(uri, uri=True)
        _setup_dt_db(keepalive)

        root = base / "export"
        responses = root / "responses"
        responses.mkdir(parents=True, exist_ok=True)
        (responses / "response_1.json").write_text(
            json.dumps(
                {
                    "dt_id": 1,
                    "decision": "approved",
                    "designer": "OtherDesigner",
                    "responded_by": "Supervisor",
                    "responded_at": "2026-04-15T12:00:00Z",
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(da, "_get_downtime_dir", lambda: str(root))
        monkeypatch.setattr(da, "get_connection", lambda: sqlite3.connect(uri, uri=True))
        monkeypatch.setattr(da, "_processed_response_files", set())
        monkeypatch.setattr(da, "_save_processed_responses", lambda processed: None)

        updated = da._poll_teams_responses("Ana")
        assert updated == 0

        conn = sqlite3.connect(uri, uri=True)
        status = conn.execute("SELECT status FROM downtimes WHERE id = 1").fetchone()[0]
        conn.close()
        assert status == "pending"
    finally:
        if keepalive is not None:
            keepalive.close()
        shutil.rmtree(base, ignore_errors=True)
