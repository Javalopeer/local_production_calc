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


# Teams webhook + adaptive-card response polling were removed when the flow
# migrated to manual copy-paste approval. Their tests were deleted with them.
