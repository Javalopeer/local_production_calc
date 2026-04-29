import sqlite3
import os
import sys
import time
from sync.app_logger import log_event

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
CURRENT_SCHEMA_VERSION = 4


def _get_legacy_db_candidates() -> list:
    """Return all possible legacy DB paths, in priority order.

    Different versions of the app placed cases.db in different locations:
      1. %LOCALAPPDATA%\\ProductionCalcApp\\data\\cases.db   (self-installer era)
      2. %USERPROFILE%\\ProductionCalcApp\\cases.db          (config-folder era)
      3. %APPDATA%\\ProductionCalcApp\\cases.db              (AppData fallback)
      4. <exe folder>\\data\\cases.db                        (very first versions)
      5. <exe folder>\\cases.db                              (manual copy in app root)
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
    candidates.append(    os.path.join(get_base_path(), "cases.db"))

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
    except Exception as exc:
        log_event("db", f"_db_has_data({path}): {exc}", level="WARN")
    return False


def _get_table_columns(cursor, table: str) -> set:
    """Return the set of column names that exist in *table* on this connection."""
    cursor.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def _merge_from(legacy: str) -> dict:
    """Insert rows from *legacy* that don't already exist in DB_PATH.

    Only columns present in BOTH the source and destination table are copied;
    extra columns in the old DB are silently ignored, and missing columns in
    the old DB fall back to the destination's DEFAULT values.

    Returns counts dict {cases, ot_cases, downtimes}.
    """
    counts = {"cases": 0, "ot_cases": 0, "downtimes": 0}
    src = sqlite3.connect(legacy)
    dst = sqlite3.connect(DB_PATH)
    try:
        src.row_factory = sqlite3.Row
        src_cur = src.cursor()
        dst_cur = dst.cursor()

        for table in ("cases", "ot_cases"):
            try:
                src_cur.execute(f"SELECT * FROM {table}")
            except sqlite3.OperationalError:
                continue  # table absent in old DB
            dst_cols = _get_table_columns(dst_cur, table)
            for row in src_cur.fetchall():
                r = dict(row)
                dst_cur.execute(
                    f"SELECT 1 FROM {table} WHERE case_id=? AND fecha=? AND hora_inicio=?",
                    (r.get("case_id"), r.get("fecha"), r.get("hora_inicio")),
                )
                if dst_cur.fetchone():
                    continue
                # Only keep columns that exist in the destination (skip unknown extras)
                cols = [k for k in r if k != "id" and k in dst_cols]
                dst_cur.execute(
                    f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?'*len(cols))})",
                    [r[c] for c in cols],
                )
                counts[table] += 1

        try:
            src_cur.execute("SELECT * FROM downtimes")
            dst_cols = _get_table_columns(dst_cur, "downtimes")
            for row in src_cur.fetchall():
                r = dict(row)
                dst_cur.execute(
                    "SELECT 1 FROM downtimes WHERE fecha=? AND hora_inicio=?",
                    (r.get("fecha"), r.get("hora_inicio")),
                )
                if dst_cur.fetchone():
                    continue
                cols = [k for k in r if k != "id" and k in dst_cols]
                dst_cur.execute(
                    f"INSERT INTO downtimes ({', '.join(cols)}) VALUES ({', '.join('?'*len(cols))})",
                    [r[c] for c in cols],
                )
                counts["downtimes"] += 1
        except sqlite3.OperationalError:
            pass  # downtimes table absent in legacy DB — skip

        dst.commit()
    finally:
        try:
            src.close()
        except Exception:
            pass
        try:
            dst.close()
        except Exception:
            pass
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


def _windows_drive_roots() -> list:
    """Return existing Windows drive roots like C:\\, D:\\, ..."""
    roots = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        if os.path.exists(root):
            roots.append(root)
    return roots


def _discover_cases_db_candidates(max_seconds: int = 30) -> list:
    """Best-effort background discovery of cases.db files across common roots.

    The search is time-bounded and skips heavy/system folders to avoid UI impact.
    """
    started = time.time()
    user = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    roots = [
        os.path.join(user, "OneDrive"),
        os.path.join(user, "Desktop"),
        os.path.join(user, "Documents"),
        os.path.join(user, "Downloads"),
        os.path.join(user, "Escritorio"),
        os.environ.get("LOCALAPPDATA", ""),
        os.environ.get("APPDATA", ""),
    ]
    roots.extend(_windows_drive_roots())

    # Deduplicate and keep existing roots only
    seen_roots = set()
    scan_roots = []
    for r in roots:
        if not r:
            continue
        ar = os.path.abspath(r)
        key = os.path.normcase(ar)
        if key in seen_roots:
            continue
        seen_roots.add(key)
        if os.path.isdir(ar):
            scan_roots.append(ar)

    skip_dirs = {
        "$Recycle.Bin",
        "System Volume Information",
        "Windows",
        "Program Files",
        "Program Files (x86)",
        "ProgramData",
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        "venv",
    }

    found = []
    seen_paths = set()
    db_norm = os.path.normcase(os.path.abspath(DB_PATH))

    for root in scan_roots:
        if time.time() - started > max_seconds:
            break
        for cur, dirs, files in os.walk(root, topdown=True, onerror=lambda _e: None):
            if time.time() - started > max_seconds:
                break
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith("$")]
            for name in files:
                if name.lower() != "cases.db":
                    continue
                p = os.path.join(cur, name)
                ap = os.path.abspath(p)
                nk = os.path.normcase(ap)
                if nk == db_norm or nk in seen_paths:
                    continue
                seen_paths.add(nk)
                found.append(ap)

    # Prefer app-looking paths first
    found.sort(key=lambda p: ("productioncalcapp" not in p.lower(), len(p)))
    return found


def discover_and_merge_background_dbs(max_seconds: int = 30) -> str:
    """Discover external cases.db files and merge data into DB_PATH.

    Safe to run repeatedly; duplicate rows are skipped by _merge_from checks.
    Returns a short summary string.
    """
    import shutil

    discovered = _discover_cases_db_candidates(max_seconds=max_seconds)
    candidates = [p for p in discovered if os.path.exists(p) and _db_has_data(p)]
    if not candidates:
        return ""

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    merged_sources = 0
    total_cases = 0
    total_ot = 0
    total_dt = 0

    for legacy in candidates:
        if not os.path.exists(DB_PATH) or not _db_has_data(DB_PATH):
            try:
                shutil.copy2(legacy, DB_PATH)
                merged_sources += 1
            except Exception as exc:
                log_event("db", f"discover copy failed from {legacy}: {exc}", level="WARN")
            continue

        try:
            counts = _merge_from(legacy)
            added = sum(counts.values())
            if added > 0:
                merged_sources += 1
                total_cases += counts.get("cases", 0)
                total_ot += counts.get("ot_cases", 0)
                total_dt += counts.get("downtimes", 0)
        except Exception as exc:
            log_event("db", f"discover merge failed from {legacy}: {exc}", level="WARN")

    if merged_sources == 0:
        return ""
    return (
        f"Auto-merge: {merged_sources} source(s), "
        f"+{total_cases} cases, +{total_ot} OT, +{total_dt} downtimes."
    )


def _table_exists(cursor, table_name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
    if not _table_exists(cursor, table_name):
        return False
    cursor.execute(f"PRAGMA table_info({table_name})")
    return any(row[1] == column_name for row in cursor.fetchall())


def _ensure_column(cursor, table_name: str, column_name: str, ddl: str) -> None:
    """Add a column if it's missing. Safe and idempotent."""
    if not _column_exists(cursor, table_name, column_name):
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")


def _ensure_base_tables(cursor) -> None:
    """Create core tables if absent, with latest schema for new installs."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS db_metadata (
            key TEXT PRIMARY KEY,
            version INTEGER
        )
        """
    )

    cursor.execute(
        """
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
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS downtimes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT,
            hora_inicio TEXT,
            hora_fin TEXT,
            razon TEXT,
            duracion REAL,
            status TEXT DEFAULT 'approved',
            detalle TEXT DEFAULT '',
            responded_by TEXT DEFAULT '',
            responded_at TEXT DEFAULT '',
            downtime_case_id TEXT DEFAULT '',
            client_uid TEXT DEFAULT '',
            synced_to_excel INTEGER DEFAULT 0,
            synced_to_teams INTEGER DEFAULT 0,
            sync_attempts INTEGER DEFAULT 0,
            last_sync_error TEXT DEFAULT ''
        )
        """
    )

    cursor.execute(
        """
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
        """
    )


def _migration_v1(cursor) -> None:
    """Bring schema to v1 shape (legacy-compatible baseline)."""
    _ensure_base_tables(cursor)

    _ensure_column(cursor, "cases", "count_production", "count_production INTEGER DEFAULT 1")
    _ensure_column(cursor, "cases", "comments", "comments TEXT DEFAULT ''")

    _ensure_column(cursor, "downtimes", "status", "status TEXT DEFAULT 'approved'")
    _ensure_column(cursor, "downtimes", "detalle", "detalle TEXT DEFAULT ''")
    _ensure_column(cursor, "downtimes", "responded_by", "responded_by TEXT DEFAULT ''")
    _ensure_column(cursor, "downtimes", "responded_at", "responded_at TEXT DEFAULT ''")

    _ensure_column(cursor, "ot_cases", "count_production", "count_production INTEGER DEFAULT 1")
    _ensure_column(cursor, "ot_cases", "comments", "comments TEXT DEFAULT ''")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cases_fecha ON cases(fecha)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cases_region_tipo ON cases(region, tipo_caso)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ot_cases_fecha ON ot_cases(fecha)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_downtimes_fecha ON downtimes(fecha)")


def _migration_v2(cursor) -> None:
    """Schema hardening upgrade (non-destructive)."""
    # Defensive: some v1 DBs in the wild never got these columns added before
    # their version marker was bumped. Re-ensure before indexing.
    _ensure_column(cursor, "downtimes", "status", "status TEXT DEFAULT 'approved'")
    _ensure_column(cursor, "downtimes", "detalle", "detalle TEXT DEFAULT ''")
    _ensure_column(cursor, "downtimes", "responded_by", "responded_by TEXT DEFAULT ''")
    _ensure_column(cursor, "downtimes", "responded_at", "responded_at TEXT DEFAULT ''")
    _ensure_column(cursor, "downtimes", "downtime_case_id", "downtime_case_id TEXT DEFAULT ''")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_downtimes_status_fecha ON downtimes(status, fecha)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_downtimes_case_id ON downtimes(downtime_case_id)")


def _migration_v3(cursor) -> None:
    """Sync-tracking columns for the resilient downtime queue.

    - client_uid: client-side UUID for idempotent retries across machines/restarts.
    - synced_to_excel: 1 once the row reached the shared per-designer xlsx.
    - synced_to_teams: legacy flag from the retired webhook flow; always 1 now.
    - sync_attempts / last_sync_error: diagnostics for the retry worker.
    """
    _ensure_column(cursor, "downtimes", "client_uid",       "client_uid TEXT DEFAULT ''")
    _ensure_column(cursor, "downtimes", "synced_to_excel",  "synced_to_excel INTEGER DEFAULT 0")
    _ensure_column(cursor, "downtimes", "synced_to_teams",  "synced_to_teams INTEGER DEFAULT 0")
    _ensure_column(cursor, "downtimes", "sync_attempts",    "sync_attempts INTEGER DEFAULT 0")
    _ensure_column(cursor, "downtimes", "last_sync_error",  "last_sync_error TEXT DEFAULT ''")
    # Backfill: rows that already existed before v3 are assumed synced (they were
    # created and exported under the old code path). Resending them now would
    # duplicate work and might re-fire Teams cards for ancient DTs.
    cursor.execute(
        "UPDATE downtimes SET synced_to_excel = 1, synced_to_teams = 1 "
        "WHERE synced_to_excel = 0 AND synced_to_teams = 0"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_downtimes_unsynced "
                   "ON downtimes(synced_to_excel, synced_to_teams, status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_downtimes_client_uid "
                   "ON downtimes(client_uid)")


def _migration_v4(cursor) -> None:
    """One-time backlog cleanup after switching to the manual approval flow.

    Power Automate / Teams webhook approvals were retired. Any DT still sitting
    in 'pending' from the old flow will never get a supervisor decision, so we
    flip them all to 'approved' once. New DTs always start pending and the
    user marks them Approved/Rejected in-app after pasting to Teams.
    """
    cursor.execute(
        "UPDATE downtimes SET status = 'approved' WHERE status = 'pending'"
    )


def _get_db_version_from_cursor(cursor) -> int:
    if not _table_exists(cursor, "db_metadata"):
        return 0
    cursor.execute("SELECT version FROM db_metadata WHERE key='schema_version'")
    row = cursor.fetchone()
    return int(row[0]) if row else 0


def _set_db_version_from_cursor(cursor, version: int) -> None:
    cursor.execute(
        "INSERT OR REPLACE INTO db_metadata (key, version) VALUES ('schema_version', ?)",
        (version,),
    )


def _run_schema_migrations(conn) -> int:
    """
    Run schema migrations inside a single transaction.

    Returns final schema version.
    """
    cursor = conn.cursor()
    _ensure_base_tables(cursor)
    version = _get_db_version_from_cursor(cursor)

    if version < 1:
        _migration_v1(cursor)
        _set_db_version_from_cursor(cursor, 1)
        version = 1

    if version < 2:
        _migration_v2(cursor)
        _set_db_version_from_cursor(cursor, 2)
        version = 2

    if version < 3:
        _migration_v3(cursor)
        _set_db_version_from_cursor(cursor, 3)
        version = 3

    if version < 4:
        _migration_v4(cursor)
        _set_db_version_from_cursor(cursor, 4)
        version = 4

    return version


_WAL_INIT_DONE = False


def _ensure_wal_mode(conn: sqlite3.Connection) -> None:
    """Enable WAL mode + busy timeout once per process. Cheap to re-run."""
    global _WAL_INIT_DONE
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=15000")
        _WAL_INIT_DONE = True
    except Exception as _e:
        # OneDrive-hosted DBs can occasionally reject WAL — fall back silently
        print(f"[db] WAL init skipped: {_e}")


def get_connection():
    """Open a SQLite connection with a generous timeout so OneDrive
    file-locking does not freeze the UI thread.

    `timeout=30` lets SQLite retry for up to 30 s when the file is
    momentarily locked by the SharePoint sync thread. WAL mode is enabled
    on the first connection of the process for better concurrent reads.
    """
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    if not _WAL_INIT_DONE:
        _ensure_wal_mode(conn)
    return conn

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
    try:
        conn.execute("BEGIN")
        final_version = _run_schema_migrations(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"Database initialized - Schema version: {final_version}")
