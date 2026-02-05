import sqlite3
import os
import sys

def get_base_path():
    """Get the base path for data files - works for both dev and PyInstaller exe"""
    if getattr(sys, 'frozen', False):
        # Running as compiled exe
        return os.path.dirname(sys.executable)
    else:
        # Running as script
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_data_path():
    """Get the data directory path, creating it if needed"""
    base = get_base_path()
    data_dir = os.path.join(base, "data")
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    return data_dir

DB_PATH = os.path.join(get_data_path(), "cases.db")

# Current schema version - increment when making DB changes
CURRENT_SCHEMA_VERSION = 1

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
    except:
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
    except:
        pass
    try:
        cursor.execute("ALTER TABLE cases ADD COLUMN comments TEXT DEFAULT ''")
    except:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS downtimes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT,
            hora_inicio TEXT,
            hora_fin TEXT,
            razon TEXT,
            duracion REAL
        )
    """)

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
    except:
        pass
    try:
        cursor.execute("ALTER TABLE ot_cases ADD COLUMN comments TEXT DEFAULT ''")
    except:
        pass
    
    # Update schema version
    cursor.execute("INSERT OR REPLACE INTO db_metadata (key, version) VALUES ('schema_version', ?)", (CURRENT_SCHEMA_VERSION,))

    conn.commit()
    conn.close()
    
    print(f"Database initialized - Schema version: {CURRENT_SCHEMA_VERSION}")
