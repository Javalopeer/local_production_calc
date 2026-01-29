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

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

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
            case_value REAL
        )
    """)

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

    conn.commit()
    conn.close()
