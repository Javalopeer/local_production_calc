from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTimeEdit, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QComboBox, QMessageBox
)
from PySide6.QtCore import QTime, QDate
from db.database import get_connection
from datetime import datetime


class DowntimeManager(QWidget):
    def __init__(self, parent=None, on_update_callback=None):
        super().__init__(parent)
        self.on_update_callback = on_update_callback
        self.delete_mode = False
        self.init_ui()
        self.load_downtimes()

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Input section
        input_layout = QHBoxLayout()

        input_layout.addWidget(QLabel("Start:"))
        self.downtime_start = QTimeEdit()
        self.downtime_start.setTime(QTime.currentTime())
        self.downtime_start.setMaximumWidth(90)
        input_layout.addWidget(self.downtime_start)

        input_layout.addWidget(QLabel("End:"))
        self.downtime_end = QTimeEdit()
        self.downtime_end.setTime(QTime.currentTime())
        self.downtime_end.setMaximumWidth(90)
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
        self.downtime_reason.setMaximumWidth(135)
        input_layout.addWidget(self.downtime_reason)

        add_btn = QPushButton("Add")
        add_btn.setMaximumWidth(75)
        add_btn.setMinimumHeight(23)
        add_btn.clicked.connect(self.add_downtime)
        input_layout.addWidget(add_btn)

        input_layout.addStretch()
        main_layout.addLayout(input_layout)

        # Table
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Start", "End", "Duration (min)", "Reason"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.cellClicked.connect(self.on_cell_clicked)
        main_layout.addWidget(self.table)

        # Buttons layout - centered
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setMaximumWidth(85)
        self.delete_btn.clicked.connect(self.delete_downtime)
        buttons_layout.addWidget(self.delete_btn)
        
        buttons_layout.addStretch()
        main_layout.addLayout(buttons_layout)

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
        
        # Set column widths with better spacing
        self.table.setColumnWidth(0, 80)  # Start
        self.table.setColumnWidth(1, 80)  # End
        self.table.setColumnWidth(2, 110) # Duration
        self.table.horizontalHeader().setStretchLastSection(True) # Reason takes remaining space

    def on_cell_clicked(self, row, column):
        """Handle cell click - delete if in delete mode"""
        if self.delete_mode:
            # If in delete mode, delete with confirmation
            self.delete_downtime_at_row(row)

    def load_edit_data(self, row):
        """Load downtime data into edit fields"""
        start_text = self.table.item(row, 0).text()
        end_text = self.table.item(row, 1).text()
        reason_text = self.table.item(row, 3).text()
        
        self.downtime_start.setTime(QTime.fromString(start_text, "HH:mm"))
        self.downtime_end.setTime(QTime.fromString(end_text, "HH:mm"))
        
        index = self.downtime_reason.findText(reason_text)
        if index >= 0:
            self.downtime_reason.setCurrentIndex(index)
        
        self.current_edit_row = row
        self.update_button_colors()

    def edit_downtime(self):
        """Toggle edit mode"""
        self.edit_mode = not self.edit_mode
        
        if self.edit_mode:
            # Entering edit mode - deactivate delete mode
            self.delete_mode = False
        
        self.update_button_colors()
        
        if not self.edit_mode:
            # If exiting edit mode, clear fields
            self.downtime_start.setTime(QTime.currentTime())
            self.downtime_end.setTime(QTime.currentTime())
            self.downtime_reason.setCurrentIndex(0)
            self.current_edit_row = -1

    def load_edit_data(self, row):
        """Load downtime data into edit fields"""
        start_text = self.table.item(row, 0).text()
        end_text = self.table.item(row, 1).text()
        reason_text = self.table.item(row, 3).text()
        
        self.downtime_start.setTime(QTime.fromString(start_text, "HH:mm"))
        self.downtime_end.setTime(QTime.fromString(end_text, "HH:mm"))
        
        index = self.downtime_reason.findText(reason_text)
        if index >= 0:
            self.downtime_reason.setCurrentIndex(index)
        
        self.current_edit_row = row
        self.update_button_colors()

    def edit_downtime(self):
        """Toggle edit mode"""
        self.edit_mode = not self.edit_mode
        
        if self.edit_mode:
            # Entering edit mode - deactivate delete mode
            self.delete_mode = False
        
        self.update_button_colors()
        
        if not self.edit_mode:
            # If exiting edit mode, clear fields
            self.downtime_start.setTime(QTime.currentTime())
            self.downtime_end.setTime(QTime.currentTime())
            self.downtime_reason.setCurrentIndex(0)
            self.current_edit_row = -1

    def update_button_colors(self):
        """Update button colors based on delete mode"""
        if self.delete_mode:
            # Delete mode active: Button stays red but with different shade to indicate active
            self.delete_btn.setStyleSheet("""
                QPushButton {
                    background-color: #B71C1C;
                    border: 2px solid #FF5252;
                    border-radius: 6px;
                    padding: 8px 14px;
                    color: white;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #C62828;
                }
            """)
        else:
            # Normal mode: Delete button default blue style
            self.delete_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2d89ef;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 14px;
                    color: white;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #1e6fd9;
                }
            """)

    def delete_downtime_at_row(self, row):
        """Delete downtime at specific row with confirmation"""
        if row >= len(self.row_ids):
            return
        
        # Exit delete mode first
        self.delete_mode = False
        self.update_button_colors()
        
        # Show confirmation dialog
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            "Are you sure you want to delete this downtime?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        row_id = self.row_ids[row]
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM downtimes WHERE id = ?", (row_id,))
        conn.commit()
        conn.close()

        self.load_downtimes()
        
        if self.on_update_callback:
            self.on_update_callback()

    def delete_downtime(self):
        """Toggle delete mode"""
        self.delete_mode = not self.delete_mode
        self.update_button_colors()
