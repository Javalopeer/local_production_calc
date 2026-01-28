import sqlite3
import os

DB_PATH = os.path.join("data", "cases.db")

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
