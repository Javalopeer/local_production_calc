import sqlite3
import os
import sys

def get_base_path():
    """Get the base path for data files - works for both dev and PyInstaller exe"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_data_path():
    """Resolve the canonical DB folder: %OneDrive%\\ProductionCalcApp\\

    OneDrive syncs this folder automatically, so the same cases.db is
    accessible from every machine (work PC, home PC, .exe, dev script).

    Fallback chain (in case OneDrive env var is missing):
      1. %OneDrive%\\ProductionCalcApp
      2. %USERPROFILE%\\OneDrive\\ProductionCalcApp
      3. %APPDATA%\\ProductionCalcApp   (last resort, non-synced)

    The folder is created if it doesn't exist, but the DB file itself is
    NEVER deleted or overwritten — only opened/read/written by SQLite.
    """
    onedrive = (
        os.environ.get("OneDrive")
        or os.path.join(os.environ.get("USERPROFILE", ""), "OneDrive")
    )
    data_dir = os.path.join(onedrive, "ProductionCalcApp")
    try:
        os.makedirs(data_dir, exist_ok=True)
    except OSError:
        # Absolute fallback: use AppData if OneDrive is unavailable
        data_dir = os.path.join(os.environ.get("APPDATA", get_base_path()), "ProductionCalcApp")
        os.makedirs(data_dir, exist_ok=True)
    return data_dir

DB_PATH = os.path.join(get_data_path(), "cases.db")

# Current schema version - increment when making DB changes
CURRENT_SCHEMA_VERSION = 1


def _get_legacy_db_candidates() -> list:
    """Return all possible legacy DB paths, in priority order.

    Different versions of the app placed cases.db in different locations:
      1. %LOCALAPPDATA%\\ProductionCalcApp\\data\\cases.db   (self-installer era)
      2. %USERPROFILE%\\ProductionCalcApp\\cases.db          (config-folder era)
      3. %APPDATA%\\ProductionCalcApp\\cases.db              (AppData fallback)
      4. <exe folder>\\data\\cases.db                        (very first versions, run from desktop)
    """
    candidates = []
    local_app   = os.environ.get("LOCALAPPDATA", "")
    user_profile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    app_data    = os.environ.get("APPDATA", "")

    if local_app:
        candidates.append(os.path.join(local_app,   "ProductionCalcApp", "data", "cases.db"))
    candidates.append(    os.path.join(user_profile, "ProductionCalcApp", "cases.db"))
    if app_data:
        candidates.append(os.path.join(app_data,    "ProductionCalcApp", "cases.db"))
    candidates.append(    os.path.join(get_base_path(), "data", "cases.db"))

    # Remove duplicates while preserving order, and skip DB_PATH itself
    seen = set()
    result = []
    for p in candidates:
        norm = os.path.normcase(os.path.abspath(p))
        if norm not in seen and norm != os.path.normcase(os.path.abspath(DB_PATH)):
            seen.add(norm)
            result.append(p)
    return result


def _db_has_data(path: str) -> bool:
    """Return True if the SQLite file at *path* contains at least one row
    in 'cases', 'ot_cases', or 'downtimes'."""
    try:
        conn = sqlite3.connect(path)
        cur  = conn.cursor()
        for table in ("cases", "ot_cases", "downtimes"):
            try:
                cur.execute(f"SELECT 1 FROM {table} LIMIT 1")
                if cur.fetchone():
                    conn.close()
                    return True
            except sqlite3.OperationalError:
                pass  # table doesn't exist yet — not an error
        conn.close()
    except Exception:
        pass
    return False


def _merge_from(legacy: str) -> dict:
    """Insert rows from *legacy* that don't already exist in DB_PATH.
    Returns counts dict {cases, ot_cases, downtimes}."""
    counts = {"cases": 0, "ot_cases": 0, "downtimes": 0}
    src = sqlite3.connect(legacy)
    dst = sqlite3.connect(DB_PATH)
    src.row_factory = sqlite3.Row
    src_cur = src.cursor()
    dst_cur = dst.cursor()

    for table in ("cases", "ot_cases"):
        try:
            src_cur.execute(f"SELECT * FROM {table}")
        except sqlite3.OperationalError:
            continue
        for row in src_cur.fetchall():
            r = dict(row)
            dst_cur.execute(
                f"SELECT 1 FROM {table} WHERE case_id=? AND fecha=? AND hora_inicio=?",
                (r.get("case_id"), r.get("fecha"), r.get("hora_inicio"))
            )
            if dst_cur.fetchone():
                continue
            cols = [k for k in r if k != "id"]
            dst_cur.execute(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?'*len(cols))})",
                [r[c] for c in cols]
            )
            counts[table] += 1

    try:
        src_cur.execute("SELECT * FROM downtimes")
        for row in src_cur.fetchall():
            r = dict(row)
            dst_cur.execute(
                "SELECT 1 FROM downtimes WHERE fecha=? AND hora_inicio=?",
                (r.get("fecha"), r.get("hora_inicio"))
            )
            if dst_cur.fetchone():
                continue
            cols = [k for k in r if k != "id"]
            dst_cur.execute(
                f"INSERT INTO downtimes ({', '.join(cols)}) VALUES ({', '.join('?'*len(cols))})",
                [r[c] for c in cols]
            )
            counts["downtimes"] += 1
    except sqlite3.OperationalError:
        pass

    dst.commit()
    src.close()
    dst.close()
    return counts


def migrate_legacy_db() -> str:
    """Migrate or merge any legacy cases.db files into the current DB_PATH.

    Checks all known legacy locations in priority order and merges each one
    that has data.  Safe to run on every startup — already-migrated rows are
    skipped via duplicate detection.

    Returns a human-readable message describing what happened (empty string
    if nothing was done).
    """
    import shutil

    candidates = [p for p in _get_legacy_db_candidates()
                  if os.path.exists(p) and _db_has_data(p)]
    if not candidates:
        return ""

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    messages = []

    for legacy in candidates:
        # ── Scenario A: new DB is empty → fast file copy ─────────────────────
        if not os.path.exists(DB_PATH) or not _db_has_data(DB_PATH):
            try:
                shutil.copy2(legacy, DB_PATH)
                messages.append(
                    f"Datos copiados desde:\n  {legacy}"
                )
            except Exception as exc:
                messages.append(
                    f"Datos encontrados en:\n  {legacy}\n"
                    f"No se pudieron copiar automáticamente ({exc}).\n"
                    f"Copia manualmente a:\n  {DB_PATH}"
                )
            continue

        # ── Scenario B: both have data → row-level merge ──────────────────────
        try:
            counts = _merge_from(legacy)
            total = sum(counts.values())
            if total > 0:
                messages.append(
                    f"Datos combinados desde:\n  {legacy}\n"
                    f"  • Casos regulares: {counts['cases']}\n"
                    f"  • Casos OT: {counts['ot_cases']}\n"
                    f"  • Downtimes: {counts['downtimes']}"
                )
        except Exception as exc:
            messages.append(
                f"Datos encontrados en:\n  {legacy}\n"
                f"No se pudo hacer el merge automáticamente ({exc}).\n"
                f"Contacta al administrador para combinarlo manualmente."
            )

    if not messages:
        return ""

    header = "Migración de datos completada\n" + "─" * 40 + "\n\n"
    footer = f"\n\nDestino: {DB_PATH}\n(sincronizado con OneDrive automáticamente)"
    return header + "\n\n".join(messages) + footer


def get_connection():
    return sqlite3.connect(DB_PATH)

def get_db_version():
    """Get the current database schema version"""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT version FROM db_metadata WHERE key='schema_version'")
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0
    except Exception as _e:
        print(f"[db] get_db_version failed: {_e}")
        conn.close()
        return 0

def set_db_version(version):
    """Set the database schema version"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO db_metadata (key, version) VALUES ('schema_version', ?)" , (version,))
    conn.commit()
    conn.close()

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Create metadata table for version tracking
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS db_metadata (
            key TEXT PRIMARY KEY,
            version INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT,
            region TEXT,
            tipo_caso TEXT,
            doctor TEXT,
            fecha TEXT,
            hora_inicio TEXT,
            hora_fin TEXT,
            tiempo_real REAL,
            std_time REAL,
            efficiency REAL,
            estado TEXT,
            case_value REAL,
            count_production INTEGER DEFAULT 1,
            comments TEXT DEFAULT ''
        )
    """)
    
    # Add columns if they don't exist (for existing databases)
    try:
        cursor.execute("ALTER TABLE cases ADD COLUMN count_production INTEGER DEFAULT 1")
    except Exception as _e:
        print(f"[db] migration skipped (already applied): {_e}")
    try:
        cursor.execute("ALTER TABLE cases ADD COLUMN comments TEXT DEFAULT ''")
    except Exception as _e:
        print(f"[db] migration skipped (already applied): {_e}")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS downtimes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT,
            hora_inicio TEXT,
            hora_fin TEXT,
            razon TEXT,
            duracion REAL,
            status TEXT DEFAULT 'approved'
        )
    """)
    # Migrate existing DBs that lack the status or detalle columns
    try:
        cursor.execute("ALTER TABLE downtimes ADD COLUMN status TEXT DEFAULT 'approved'")
    except Exception as _e:
        print(f"[db] migration skipped (already applied): {_e}")
    try:
        cursor.execute("ALTER TABLE downtimes ADD COLUMN detalle TEXT DEFAULT ''")
    except Exception as _e:
        print(f"[db] migration skipped (already applied): {_e}")
    try:
        cursor.execute("ALTER TABLE downtimes ADD COLUMN responded_by TEXT DEFAULT ''")
    except Exception as _e:
        print(f"[db] migration skipped (already applied): {_e}")
    try:
        cursor.execute("ALTER TABLE downtimes ADD COLUMN responded_at TEXT DEFAULT ''")
    except Exception as _e:
        print(f"[db] migration skipped (already applied): {_e}")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ot_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT,
            region TEXT,
            tipo_caso TEXT,
            doctor TEXT,
            fecha TEXT,
            hora_inicio TEXT,
            hora_fin TEXT,
            tiempo_real REAL,
            std_time REAL,
            efficiency REAL,
            estado TEXT,
            case_value REAL,
            count_production INTEGER DEFAULT 1,
            comments TEXT DEFAULT ''
        )
    """)
    
    # Add columns if they don't exist (for existing databases)
    try:
        cursor.execute("ALTER TABLE ot_cases ADD COLUMN count_production INTEGER DEFAULT 1")
    except Exception as _e:
        print(f"[db] migration skipped (already applied): {_e}")
    try:
        cursor.execute("ALTER TABLE ot_cases ADD COLUMN comments TEXT DEFAULT ''")
    except Exception as _e:
        print(f"[db] migration skipped (already applied): {_e}")
    
    # Indexes for the most common query patterns (fecha, region+tipo)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cases_fecha ON cases(fecha)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cases_region_tipo ON cases(region, tipo_caso)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ot_cases_fecha ON ot_cases(fecha)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_downtimes_fecha ON downtimes(fecha)")

    # Update schema version
    cursor.execute("INSERT OR REPLACE INTO db_metadata (key, version) VALUES ('schema_version', ?)", (CURRENT_SCHEMA_VERSION,))

    conn.commit()
    conn.close()
    
    print(f"Database initialized - Schema version: {CURRENT_SCHEMA_VERSION}")
