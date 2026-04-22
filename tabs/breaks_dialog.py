# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTimeEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QLineEdit, QComboBox, QFrame, QCheckBox,
)
from PySide6.QtCore import Qt, QTime
from PySide6.QtGui import QFont
from db.database import get_connection

_DEFAULT = "default"


# ── DB helpers ────────────────────────────────────────────────────────────────

def init_breaks_table():
    """Create/migrate breaks tables."""
    conn = get_connection()
    cur = conn.cursor()

    # Core breaks table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS breaks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            hora_inicio TEXT,
            hora_fin TEXT,
            schedule_group TEXT DEFAULT 'default'
        )
    """)
    # Add schedule_group column if upgrading from older schema
    cur.execute("PRAGMA table_info(breaks)")
    cols = {r[1] for r in cur.fetchall()}
    if "schedule_group" not in cols:
        cur.execute("ALTER TABLE breaks ADD COLUMN schedule_group TEXT DEFAULT 'default'")

    # Named schedule groups (non-default)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS break_schedule_groups (
            name TEXT PRIMARY KEY,
            is_active INTEGER DEFAULT 0
        )
    """)

    # Break attendance (unchanged)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS break_attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT,
            break_id INTEGER,
            took_break INTEGER DEFAULT 1,
            UNIQUE(fecha, break_id)
        )
    """)
    conn.commit()
    conn.close()


def get_breaks(schedule_group: str = _DEFAULT):
    """Return breaks for a given schedule as (id, name, start, end)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, hora_inicio, hora_fin FROM breaks "
        "WHERE schedule_group = ? ORDER BY hora_inicio",
        (schedule_group,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_schedule_groups():
    """Return list of (name, is_active) for all non-default schedules."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, is_active FROM break_schedule_groups ORDER BY name")
    rows = cur.fetchall()
    conn.close()
    return rows


def add_schedule_group(name: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO break_schedule_groups (name, is_active) VALUES (?, 0)",
        (name,),
    )
    conn.commit()
    conn.close()


def set_schedule_active(name: str, active: bool):
    conn = get_connection()
    cur = conn.cursor()
    if active:
        # Keep only one conditional schedule active at a time.
        cur.execute("UPDATE break_schedule_groups SET is_active = 0")
        cur.execute(
            "UPDATE break_schedule_groups SET is_active = 1 WHERE name = ?",
            (name,),
        )
    else:
        cur.execute(
            "UPDATE break_schedule_groups SET is_active = 0 WHERE name = ?",
            (name,),
        )
    conn.commit()
    conn.close()


def delete_schedule_group(name: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM breaks WHERE schedule_group = ?", (name,))
    cur.execute("DELETE FROM break_schedule_groups WHERE name = ?", (name,))
    conn.commit()
    conn.close()


def get_active_schedule() -> str:
    """Return the name of the first active non-default schedule, or 'default'."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM break_schedule_groups WHERE is_active = 1 LIMIT 1"
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else _DEFAULT


# ── Attendance helpers (unchanged) ────────────────────────────────────────────

def get_break_attendance(fecha: str, break_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT took_break FROM break_attendance WHERE fecha = ? AND break_id = ?",
        (fecha, break_id),
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def set_break_attendance(fecha: str, break_id: int, took_break: bool):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO break_attendance (fecha, break_id, took_break) VALUES (?, ?, ?)",
        (fecha, break_id, 1 if took_break else 0),
    )
    conn.commit()
    conn.close()


def get_breaks_taken_today(fecha: str) -> set:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT break_id FROM break_attendance WHERE fecha = ? AND took_break = 1",
        (fecha,),
    )
    ids = {r[0] for r in cur.fetchall()}
    conn.close()
    return ids


def get_breaks_answered_today(fecha: str) -> set:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT break_id FROM break_attendance WHERE fecha = ?", (fecha,))
    ids = {r[0] for r in cur.fetchall()}
    conn.close()
    return ids


def calculate_break_overlap(start_str: str, end_str: str, fecha: str = None) -> float:
    """Overlap minutes between a case and the currently active break schedule.

    If a conditional schedule is active, its breaks are used instead of Default.
    """
    active = get_active_schedule()
    breaks = get_breaks(active)
    if not breaks:
        return 0.0

    case_start = _to_minutes(start_str)
    case_end = _to_minutes(end_str)
    if case_end <= case_start:
        return 0.0

    if fecha:
        taken_ids = get_breaks_taken_today(fecha)
        answered_ids = get_breaks_answered_today(fecha)
    else:
        taken_ids = set()
        answered_ids = set()

    total = 0.0
    for bid, _, b_start_str, b_end_str in breaks:
        if fecha and bid in answered_ids and bid not in taken_ids:
            continue
        b_start = _to_minutes(b_start_str)
        b_end = _to_minutes(b_end_str)
        overlap_start = max(case_start, b_start)
        overlap_end = min(case_end, b_end)
        if overlap_end > overlap_start:
            total += overlap_end - overlap_start

    return total


def _to_minutes(time_str: str) -> float:
    parts = time_str.split(":")
    return int(parts[0]) * 60 + int(parts[1])


# ── Dialog ────────────────────────────────────────────────────────────────────

class BreaksDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Break Times Configuration")
        self.setMinimumWidth(460)
        self.setMinimumHeight(400)
        self._current_group = _DEFAULT
        self._build_ui()
        self._refresh_selector()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Title
        title = QLabel("Configure Your Break Times")
        title.setFont(QFont("", 11, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Break time will be subtracted from case duration automatically.")
        subtitle.setStyleSheet("color: #888; font-size: 10px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        # ── Schedule selector row ─────────────────────────────────────────
        sel_row = QHBoxLayout()
        sel_row.addWidget(QLabel("Schedule:"))

        self._sel = QComboBox()
        self._sel.setMinimumWidth(140)
        self._sel.currentIndexChanged.connect(self._on_schedule_changed)
        sel_row.addWidget(self._sel)

        self._btn_new_sched = QPushButton("+ New")
        self._btn_new_sched.setFixedWidth(55)
        self._btn_new_sched.setToolTip("Create a new conditional schedule (e.g. Site Day)")
        self._btn_new_sched.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #388BFD;"
            " color: #388BFD; border-radius: 4px; font-size: 11px; font-weight: 600; padding: 2px 6px; }"
            " QPushButton:hover { background: #1C2D4F; }"
        )
        self._btn_new_sched.clicked.connect(self._add_schedule)
        sel_row.addWidget(self._btn_new_sched)

        self._btn_del_sched = QPushButton("Delete")
        self._btn_del_sched.setFixedWidth(60)
        self._btn_del_sched.setToolTip("Delete this conditional schedule and all its breaks")
        self._btn_del_sched.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #F85149;"
            " color: #F85149; border-radius: 4px; font-size: 11px; font-weight: 600; padding: 2px 6px; }"
            " QPushButton:hover { background: #3D1A1A; }"
        )
        self._btn_del_sched.clicked.connect(self._delete_schedule)
        sel_row.addWidget(self._btn_del_sched)
        sel_row.addStretch()
        layout.addLayout(sel_row)

        # ── Active toggle (only visible for non-default schedules) ────────
        self._active_row = QFrame()
        active_layout = QHBoxLayout(self._active_row)
        active_layout.setContentsMargins(0, 0, 0, 0)
        self._active_chk = QCheckBox("Enable this schedule (replaces Default breaks)")
        self._active_chk.setStyleSheet("color: #F0883E; font-weight: 600; font-size: 11px;")
        self._active_chk.toggled.connect(self._on_active_toggled)
        active_layout.addWidget(self._active_chk)
        active_layout.addStretch()
        self._active_row.setVisible(False)
        layout.addWidget(self._active_row)

        # ── Divider ───────────────────────────────────────────────────────
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("color: #30363D;")
        layout.addWidget(div)

        # ── Add break form ────────────────────────────────────────────────
        form = QHBoxLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Name (e.g. Lunch)")
        self.name_input.setFixedWidth(120)
        form.addWidget(self.name_input)

        form.addWidget(QLabel("From:"))
        self.start_input = QTimeEdit()
        self.start_input.setDisplayFormat("HH:mm")
        self.start_input.setTime(QTime(12, 0))
        form.addWidget(self.start_input)

        form.addWidget(QLabel("To:"))
        self.end_input = QTimeEdit()
        self.end_input.setDisplayFormat("HH:mm")
        self.end_input.setTime(QTime(12, 30))
        form.addWidget(self.end_input)

        btn_add = QPushButton("Add")
        btn_add.setStyleSheet(
            "background: #238636; color: white; font-weight: bold;"
            " padding: 4px 12px; border-radius: 3px;"
        )
        btn_add.clicked.connect(self._add_break)
        form.addWidget(btn_add)
        layout.addLayout(form)

        # ── Breaks table ──────────────────────────────────────────────────
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Name", "Start", "End", "Duration"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)          # no row numbers
        self.table.setAlternatingRowColors(False)
        layout.addWidget(self.table)

        # ── Bottom buttons ────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_del = QPushButton("Delete Selected")
        btn_del.setStyleSheet(
            "background: #E74C3C; color: white; font-weight: bold;"
            " padding: 4px 12px; border-radius: 3px;"
        )
        btn_del.clicked.connect(self._delete_selected)
        btn_row.addWidget(btn_del)
        layout.addLayout(btn_row)

    # ── Data helpers ─────────────────────────────────────────────────────────

    def _refresh_selector(self):
        """Rebuild the schedule combo box and restore selection."""
        self._sel.blockSignals(True)
        prev = self._current_group
        self._sel.clear()
        self._sel.addItem("Default", _DEFAULT)
        for name, is_active in get_schedule_groups():
            label = f"{name}  {'[ON]' if is_active else '[OFF]'}"
            self._sel.addItem(label, name)

        # Restore previous selection
        for i in range(self._sel.count()):
            if self._sel.itemData(i) == prev:
                self._sel.setCurrentIndex(i)
                break
        self._sel.blockSignals(False)
        self._on_schedule_changed()

    def _on_schedule_changed(self):
        idx = self._sel.currentIndex()
        if idx < 0:
            return
        group = self._sel.itemData(idx)
        self._current_group = group or _DEFAULT

        is_default = self._current_group == _DEFAULT
        self._active_row.setVisible(not is_default)
        self._btn_del_sched.setEnabled(not is_default)

        if not is_default:
            groups = {n: a for n, a in get_schedule_groups()}
            active = bool(groups.get(self._current_group, 0))
            self._active_chk.blockSignals(True)
            self._active_chk.setChecked(active)
            self._active_chk.blockSignals(False)

        self._load_breaks()

    def _on_active_toggled(self, checked: bool):
        if self._current_group == _DEFAULT:
            return
        set_schedule_active(self._current_group, checked)
        self._refresh_selector()

    def _load_breaks(self):
        breaks = get_breaks(self._current_group)
        self.table.setRowCount(len(breaks))
        self._break_ids = []
        for i, (bid, name, start, end) in enumerate(breaks):
            self._break_ids.append(bid)
            self.table.setItem(i, 0, QTableWidgetItem(name or ""))
            self.table.setItem(i, 1, QTableWidgetItem(start))
            self.table.setItem(i, 2, QTableWidgetItem(end))
            dur = _to_minutes(end) - _to_minutes(start)
            self.table.setItem(i, 3, QTableWidgetItem(f"{dur:.0f} min"))
            for col in range(4):
                item = self.table.item(i, col)
                if item:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

    # ── Actions ──────────────────────────────────────────────────────────────

    def _add_schedule(self):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "New Schedule", "Schedule name (e.g. Site Day):"
        )
        name = name.strip()
        if not ok or not name or name.lower() == _DEFAULT:
            return
        add_schedule_group(name)
        self._current_group = name
        self._refresh_selector()

    def _delete_schedule(self):
        if self._current_group == _DEFAULT:
            return
        reply = QMessageBox.question(
            self, "Delete Schedule",
            f"Delete schedule '{self._current_group}' and all its breaks?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        delete_schedule_group(self._current_group)
        self._current_group = _DEFAULT
        self._refresh_selector()

    def _add_break(self):
        name = self.name_input.text().strip() or "Break"
        start = self.start_input.time().toString("HH:mm")
        end = self.end_input.time().toString("HH:mm")

        if _to_minutes(end) <= _to_minutes(start):
            QMessageBox.warning(self, "Invalid", "End time must be after start time.")
            return

        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO breaks (name, hora_inicio, hora_fin, schedule_group) VALUES (?, ?, ?, ?)",
            (name, start, end, self._current_group),
        )
        conn.commit()
        conn.close()
        self.name_input.clear()
        self._load_breaks()

    def _delete_selected(self):
        rows = {idx.row() for idx in self.table.selectedIndexes()}
        if not rows:
            return
        conn = get_connection()
        cur = conn.cursor()
        for r in sorted(rows, reverse=True):
            if r < len(self._break_ids):
                cur.execute("DELETE FROM breaks WHERE id = ?", (self._break_ids[r],))
        conn.commit()
        conn.close()
        self._load_breaks()
