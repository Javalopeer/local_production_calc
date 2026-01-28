from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTimeEdit, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QComboBox
)
from PySide6.QtCore import QTime, QDate
from db.database import get_connection
from datetime import datetime


class DowntimeManager(QWidget):
    def __init__(self, parent=None, on_update_callback=None):
        super().__init__(parent)
        self.on_update_callback = on_update_callback
        self.init_ui()
        self.load_downtimes()

    def init_ui(self):
        main_layout = QVBoxLayout()

        # Title
        title = QLabel("Downtime Management")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        main_layout.addWidget(title)

        # Input section
        input_layout = QHBoxLayout()

        input_layout.addWidget(QLabel("Start:"))
        self.downtime_start = QTimeEdit()
        self.downtime_start.setTime(QTime.currentTime())
        self.downtime_start.setMaximumWidth(100)
        input_layout.addWidget(self.downtime_start)

        input_layout.addWidget(QLabel("End:"))
        self.downtime_end = QTimeEdit()
        self.downtime_end.setTime(QTime.currentTime())
        self.downtime_end.setMaximumWidth(100)
        input_layout.addWidget(self.downtime_end)

        input_layout.addWidget(QLabel("Reason:"))
        self.downtime_reason = QComboBox()
        self.downtime_reason.addItems([
            "Break",
            "Lunch",
            "Equipment Issue",
            "Meeting",
            "Other"
        ])
        self.downtime_reason.setMaximumWidth(150)
        input_layout.addWidget(self.downtime_reason)

        add_btn = QPushButton("Add")
        add_btn.setMaximumWidth(80)
        add_btn.clicked.connect(self.add_downtime)
        input_layout.addWidget(add_btn)

        input_layout.addStretch()
        main_layout.addLayout(input_layout)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Start", "End", "Duration (min)", "Reason"])
        self.table.setMaximumHeight(200)
        main_layout.addWidget(self.table)

        # Delete button
        delete_btn = QPushButton("Delete Selected")
        delete_btn.setMaximumWidth(150)
        delete_btn.clicked.connect(self.delete_downtime)
        main_layout.addWidget(delete_btn)

        main_layout.addStretch()
        self.setLayout(main_layout)

    def add_downtime(self):
        start = self.downtime_start.time().toString("HH:mm")
        end = self.downtime_end.time().toString("HH:mm")
        reason = self.downtime_reason.currentText()

        # Calculate duration
        start_mins = self.downtime_start.time().hour() * 60 + self.downtime_start.time().minute()
        end_mins = self.downtime_end.time().hour() * 60 + self.downtime_end.time().minute()
        duration = end_mins - start_mins
        if duration < 0:
            duration += 24 * 60

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO downtimes (fecha, hora_inicio, hora_fin, razon, duracion)
            VALUES (?, ?, ?, ?, ?)
        """, (
            datetime.now().strftime("%Y-%m-%d"),
            start,
            end,
            reason,
            duration
        ))

        conn.commit()
        conn.close()

        self.load_downtimes()
        self.downtime_start.setTime(QTime.currentTime())
        self.downtime_end.setTime(QTime.currentTime())
        
        # Trigger callback to update production
        if self.on_update_callback:
            self.on_update_callback()

    def load_downtimes(self):
        conn = get_connection()
        cursor = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")

        cursor.execute("""
            SELECT id, hora_inicio, hora_fin, duracion, razon
            FROM downtimes
            WHERE fecha = ?
            ORDER BY hora_inicio DESC
        """, (today,))

        rows = cursor.fetchall()
        conn.close()

        self.table.setRowCount(len(rows))
        self.row_ids = []

        for idx, row in enumerate(rows):
            self.table.setItem(idx, 0, QTableWidgetItem(str(row[1])))
            self.table.setItem(idx, 1, QTableWidgetItem(str(row[2])))
            self.table.setItem(idx, 2, QTableWidgetItem(str(row[3])))
            self.table.setItem(idx, 3, QTableWidgetItem(str(row[4])))
            self.row_ids.append(row[0])

    def delete_downtime(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return

        for row in selected_rows:
            row_id = self.row_ids[row.row()]
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM downtimes WHERE id = ?", (row_id,))
            conn.commit()
            conn.close()

        self.load_downtimes()
        
        # Trigger callback to update production
        if self.on_update_callback:
            self.on_update_callback()
