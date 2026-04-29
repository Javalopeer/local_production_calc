import os
import sqlite3
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _mem_uri() -> str:
    return f"file:dbmig_{uuid.uuid4().hex}?mode=memory&cache=shared"


def _connect(uri: str):
    return sqlite3.connect(uri, uri=True)


def _create_v1_db(conn):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE db_metadata (
            key TEXT PRIMARY KEY,
            version INTEGER
        )
        """
    )
    cur.execute(
        "INSERT INTO db_metadata (key, version) VALUES ('schema_version', 1)"
    )
    cur.execute(
        """
        CREATE TABLE downtimes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT,
            hora_inicio TEXT,
            hora_fin TEXT,
            razon TEXT,
            duracion REAL,
            status TEXT DEFAULT 'approved',
            detalle TEXT DEFAULT '',
            responded_by TEXT DEFAULT '',
            responded_at TEXT DEFAULT ''
        )
        """
    )
    cur.execute(
        """
        INSERT INTO downtimes (
            fecha, hora_inicio, hora_fin, razon, duracion, status, detalle, responded_by, responded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("2026-04-15", "10:00", "10:05", "CMS Down", 5.0, "pending", "legacy-detail", "", ""),
    )
    conn.commit()


def _column_exists(conn, table: str, column: str) -> bool:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def _index_exists(conn, index_name: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
        (index_name,),
    )
    return cur.fetchone() is not None


def test_migration_v1_to_v2_preserves_rows(monkeypatch):
    import db.database as dbmod

    uri = _mem_uri()
    keepalive = _connect(uri)
    try:
        _create_v1_db(keepalive)

        monkeypatch.setattr(dbmod, "DB_PATH", uri)
        monkeypatch.setattr(dbmod, "get_connection", lambda: _connect(uri))

        dbmod.init_db()

        assert dbmod.get_db_version() == dbmod.CURRENT_SCHEMA_VERSION
        assert _column_exists(keepalive, "downtimes", "downtime_case_id")
        assert _index_exists(keepalive, "idx_downtimes_status_fecha")
        assert _index_exists(keepalive, "idx_downtimes_case_id")

        row = keepalive.execute(
            "SELECT razon, status, detalle, downtime_case_id FROM downtimes LIMIT 1"
        ).fetchone()
        assert row[0] == "CMS Down"
        # v4 backlog cleanup auto-approves any DT left in 'pending' from the
        # retired Power Automate flow, so the legacy row ends up as 'approved'.
        assert row[1] == "approved"
        assert row[2] == "legacy-detail"
        assert row[3] in ("", None)
    finally:
        keepalive.close()


def test_init_db_migration_is_idempotent(monkeypatch):
    import db.database as dbmod

    uri = _mem_uri()
    keepalive = _connect(uri)
    try:
        _create_v1_db(keepalive)

        monkeypatch.setattr(dbmod, "DB_PATH", uri)
        monkeypatch.setattr(dbmod, "get_connection", lambda: _connect(uri))

        dbmod.init_db()
        dbmod.init_db()

        assert dbmod.get_db_version() == dbmod.CURRENT_SCHEMA_VERSION
        assert _column_exists(keepalive, "downtimes", "downtime_case_id")
    finally:
        keepalive.close()
