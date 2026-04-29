# -*- coding: utf-8 -*-
"""
Tests for daily_performance core logic.
"""
import os
import sqlite3
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ── helpers ───────────────────────────────────────────────────────────────────

def _mem_db():
    uri = f"file:dp_{uuid.uuid4().hex}?mode=memory&cache=shared"
    keepalive = sqlite3.connect(uri, uri=True)
    return uri, keepalive


def _patched_conn(uri):
    return lambda: sqlite3.connect(uri, uri=True)


# ── sync.daily_performance ────────────────────────────────────────────────────

def test_get_daily_metrics_empty_db(monkeypatch):
    import db.database as dbmod
    from sync import daily_performance as dp

    uri, keepalive = _mem_db()
    try:
        monkeypatch.setattr(dbmod, "DB_PATH", uri)
        monkeypatch.setattr(dbmod, "get_connection", _patched_conn(uri))
        monkeypatch.setattr(dp, "get_connection", _patched_conn(uri))
        monkeypatch.setattr(dp, "load_units_eq_data", lambda: {})
        dbmod.init_db()
        dp.init_performance_table()

        m = dp.get_daily_metrics("2026-04-15")
        assert m["production_pct"] == 0.0
        assert m["total_cases"] == 0
        assert m["met_target"] is False
    finally:
        keepalive.close()


def test_get_daily_metrics_with_cases(monkeypatch):
    import db.database as dbmod
    from sync import daily_performance as dp

    uri, keepalive = _mem_db()
    try:
        monkeypatch.setattr(dbmod, "DB_PATH", uri)
        monkeypatch.setattr(dbmod, "get_connection", _patched_conn(uri))
        monkeypatch.setattr(dp, "get_connection", _patched_conn(uri))
        monkeypatch.setattr(dp, "load_units_eq_data", lambda: {})
        dbmod.init_db()
        dp.init_performance_table()

        conn = sqlite3.connect(uri, uri=True)
        for i in range(5):
            conn.execute(
                "INSERT INTO cases (case_id, region, tipo_caso, fecha, hora_inicio, hora_fin, "
                "tiempo_real, std_time, efficiency, estado, case_value) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"C{i:03}", "ICON", "Primary", "2026-04-15", "09:00", "09:30", 30, 25, 120, "OK", 20.0),
            )
        conn.commit()
        conn.close()

        m = dp.get_daily_metrics("2026-04-15")
        assert m["cases_pct"] == 100.0  # 5 × 20 = 100
        assert m["total_cases"] == 5
        assert m["met_target"] is True
    finally:
        keepalive.close()


def test_has_pending_justification_none_when_empty(monkeypatch):
    import db.database as dbmod
    from sync import daily_performance as dp

    uri, keepalive = _mem_db()
    try:
        monkeypatch.setattr(dbmod, "DB_PATH", uri)
        monkeypatch.setattr(dbmod, "get_connection", _patched_conn(uri))
        monkeypatch.setattr(dp, "get_connection", _patched_conn(uri))
        dbmod.init_db()
        dp.init_performance_table()

        assert dp.has_pending_justification() is None
    finally:
        keepalive.close()


def test_has_pending_justification_skips_weekend(monkeypatch):
    import db.database as dbmod
    from sync import daily_performance as dp
    from datetime import date

    uri, keepalive = _mem_db()
    try:
        monkeypatch.setattr(dbmod, "DB_PATH", uri)
        monkeypatch.setattr(dbmod, "get_connection", _patched_conn(uri))
        monkeypatch.setattr(dp, "get_connection", _patched_conn(uri))
        dbmod.init_db()
        dp.init_performance_table()

        # Insert a Saturday row with missed target
        conn = sqlite3.connect(uri, uri=True)
        conn.execute(
            "INSERT INTO daily_performance (fecha, production_pct, equivalent_units, met_target, "
            "justification_submitted) VALUES (?,?,?,?,?)",
            ("2026-04-11", 50.0, 5.0, 0, 0),  # Saturday
        )
        conn.commit()
        conn.close()

        assert dp.has_pending_justification() is None
    finally:
        keepalive.close()


def test_has_pending_justification_returns_weekday(monkeypatch):
    import db.database as dbmod
    from sync import daily_performance as dp

    uri, keepalive = _mem_db()
    try:
        monkeypatch.setattr(dbmod, "DB_PATH", uri)
        monkeypatch.setattr(dbmod, "get_connection", _patched_conn(uri))
        monkeypatch.setattr(dp, "get_connection", _patched_conn(uri))
        dbmod.init_db()
        dp.init_performance_table()

        conn = sqlite3.connect(uri, uri=True)
        conn.execute(
            "INSERT INTO daily_performance (fecha, production_pct, equivalent_units, met_target, "
            "justification_submitted) VALUES (?,?,?,?,?)",
            ("2026-04-14", 50.0, 5.0, 0, 0),  # Tuesday
        )
        conn.commit()
        conn.close()

        result = dp.has_pending_justification()
        assert result == "2026-04-14"
    finally:
        keepalive.close()


def test_production_target_constants():
    from sync.daily_performance import PRODUCTION_TARGET_PCT, UE_TARGET
    assert PRODUCTION_TARGET_PCT == 95.0
    assert UE_TARGET == 14.0
