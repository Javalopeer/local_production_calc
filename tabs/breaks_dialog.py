from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTimeEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QLineEdit,
)
from PySide6.QtCore import Qt, QTime
from PySide6.QtGui import QFont, QColor
from db.database import get_connection


def init_breaks_table():
    """Create the breaks table if it doesn't exist."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS breaks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            hora_inicio TEXT,
            hora_fin TEXT
        )
    """)
    cursor.execute("""
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


def get_breaks():
    """Return all configured breaks as list of (id, name, start, end)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, hora_inicio, hora_fin FROM breaks ORDER BY hora_inicio")
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_break_attendance(fecha: str, break_id: int):
    """Return took_break value for a specific break on a date, or None if not answered."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT took_break FROM break_attendance WHERE fecha = ? AND break_id = ?",
        (fecha, break_id),
    )
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def set_break_attendance(fecha: str, break_id: int, took_break: bool):
    """Record whether the user took a specific break on a date."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO break_attendance (fecha, break_id, took_break) VALUES (?, ?, ?)",
        (fecha, break_id, 1 if took_break else 0),
    )
    conn.commit()
    conn.close()


def get_breaks_taken_today(fecha: str) -> set:
    """Return set of break_ids that the user confirmed they took on this date."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT break_id FROM break_attendance WHERE fecha = ? AND took_break = 1",
        (fecha,),
    )
    ids = {row[0] for row in cursor.fetchall()}
    conn.close()
    return ids


def get_breaks_answered_today(fecha: str) -> set:
    """Return set of break_ids that have been answered (yes or no) today."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT break_id FROM break_attendance WHERE fecha = ?",
        (fecha,),
    )
    ids = {row[0] for row in cursor.fetchall()}
    conn.close()
    return ids


def calculate_break_overlap(start_str: str, end_str: str, fecha: str = None) -> float:
    """Calculate total break minutes that overlap with a case time range.

    Only subtracts breaks the user confirmed they took (via break_attendance).
    If fecha is None or a break hasn't been answered yet, that break is
    assumed taken (backward-compatible default).

    Parameters:
        start_str: case start time "HH:mm" or "HH:MM"
        end_str:   case end time   "HH:mm" or "HH:MM"
        fecha:     date string "YYYY-MM-DD" to check attendance

    Returns:
        Total minutes of break time to subtract.
    """
    breaks = get_breaks()
    if not breaks:
        return 0.0

    case_start = _to_minutes(start_str)
    case_end = _to_minutes(end_str)
    if case_end <= case_start:
        return 0.0

    # Load attendance for today
    if fecha:
        taken_ids = get_breaks_taken_today(fecha)
        answered_ids = get_breaks_answered_today(fecha)
    else:
        taken_ids = set()
        answered_ids = set()

    total_overlap = 0.0
    for bid, _, b_start_str, b_end_str in breaks:
        # If we have a fecha and the user answered "no" for this break, skip it
        if fecha and bid in answered_ids and bid not in taken_ids:
            continue
        b_start = _to_minutes(b_start_str)
        b_end = _to_minutes(b_end_str)
        # Calculate overlap
        overlap_start = max(case_start, b_start)
        overlap_end = min(case_end, b_end)
        if overlap_end > overlap_start:
            total_overlap += overlap_end - overlap_start

    return total_overlap


def _to_minutes(time_str: str) -> float:
    """Convert 'HH:mm' to minutes since midnight."""
    parts = time_str.split(":")
    return int(parts[0]) * 60 + int(parts[1])


class BreaksDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Break Times Configuration")
        self.setMinimumWidth(420)
        self.setMinimumHeight(350)
        self._build_ui()
        self._load_breaks()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Title
        title = QLabel("Configure Your Break Times")
        title.setFont(QFont("", 11, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Break time will be subtracted from case duration automatically.")
        subtitle.setStyleSheet("color: #888; font-size: 10px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(8)

        # Add break form
        form_layout = QHBoxLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Name (e.g. Lunch)")
        self.name_input.setFixedWidth(120)
        form_layout.addWidget(self.name_input)

        form_layout.addWidget(QLabel("From:"))
        self.start_input = QTimeEdit()
        self.start_input.setDisplayFormat("HH:mm")
        self.start_input.setTime(QTime(12, 0))
        form_layout.addWidget(self.start_input)

        form_layout.addWidget(QLabel("To:"))
        self.end_input = QTimeEdit()
        self.end_input.setDisplayFormat("HH:mm")
        self.end_input.setTime(QTime(12, 30))
        form_layout.addWidget(self.end_input)

        btn_add = QPushButton("Add")
        btn_add.setStyleSheet("background: #4CAF50; color: white; font-weight: bold; padding: 4px 12px; border-radius: 3px;")
        btn_add.clicked.connect(self._add_break)
        form_layout.addWidget(btn_add)

        layout.addLayout(form_layout)
        layout.addSpacing(8)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Name", "Start", "End", "Duration"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        # Delete button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_del = QPushButton("Delete Selected")
        btn_del.setStyleSheet("background: #e74c3c; color: white; font-weight: bold; padding: 4px 12px; border-radius: 3px;")
        btn_del.clicked.connect(self._delete_selected)
        btn_layout.addWidget(btn_del)
        layout.addLayout(btn_layout)

    def _load_breaks(self):
        breaks = get_breaks()
        self.table.setRowCount(len(breaks))
        self._break_ids = []
        for i, (bid, name, start, end) in enumerate(breaks):
            self._break_ids.append(bid)
            self.table.setItem(i, 0, QTableWidgetItem(name or ""))
            self.table.setItem(i, 1, QTableWidgetItem(start))
            self.table.setItem(i, 2, QTableWidgetItem(end))
            # Duration
            dur = _to_minutes(end) - _to_minutes(start)
            self.table.setItem(i, 3, QTableWidgetItem(f"{dur:.0f} min"))

    def _add_break(self):
        name = self.name_input.text().strip() or "Break"
        start = self.start_input.time().toString("HH:mm")
        end = self.end_input.time().toString("HH:mm")

        if _to_minutes(end) <= _to_minutes(start):
            QMessageBox.warning(self, "Invalid", "End time must be after start time.")
            return

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO breaks (name, hora_inicio, hora_fin) VALUES (?, ?, ?)",
                        (name, start, end))
        conn.commit()
        conn.close()

        self.name_input.clear()
        self._load_breaks()

    def _delete_selected(self):
        rows = set(idx.row() for idx in self.table.selectedIndexes())
        if not rows:
            return
        conn = get_connection()
        cursor = conn.cursor()
        for r in sorted(rows, reverse=True):
            bid = self._break_ids[r]
            cursor.execute("DELETE FROM breaks WHERE id = ?", (bid,))
        conn.commit()
        conn.close()
        self._load_breaks()
