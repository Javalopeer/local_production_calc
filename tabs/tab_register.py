import json
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QComboBox, QLineEdit,
    QPushButton, QLabel, QTimeEdit, QVBoxLayout, QHBoxLayout, QGroupBox, QProgressBar, QTabWidget, QDateEdit
)
from PySide6.QtCore import QTime, QDate, Qt
from PySide6.QtGui import QFont
from db.database import get_connection
from datetime import datetime
from .downtime_manager import DowntimeManager


def card(title, widget):
    """Helper function to create styled card/groupbox"""
    box = QGroupBox(title)
    layout = QVBoxLayout()
    layout.addWidget(widget) if isinstance(widget, QWidget) else layout.addLayout(widget)
    box.setLayout(layout)
    return box


class TimeEditWithShortcut(QTimeEdit):
    """QTimeEdit con soporte para Ctrl+Shift+: para hora actual y edición directa"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDisplayFormat("HH:mm")
        self.setCorrectionMode(QTimeEdit.CorrectToNearestValue)
        self.setAcceptDrops(True)
    
    def keyPressEvent(self, event):
        # Ctrl+Shift+:
        if event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            if event.key() == Qt.Key.Key_Colon:
                self.setTime(QTime.currentTime())
                return
        # Allow all text input
        super().keyPressEvent(event)
    
    def mouseDoubleClickEvent(self, event):
        """Allow double-click to select all for editing"""
        super().mouseDoubleClickEvent(event)
        # Select all text when double-clicked
        self.lineEdit().selectAll() if hasattr(self, 'lineEdit') and self.lineEdit() else None


class DateEditWithShortcut(QDateEdit):
    """QDateEdit con soporte para Ctrl+Shift+; para fecha actual y edición directa"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDisplayFormat("yyyy-MM-dd")
        self.setCalendarPopup(True)
        self.setAcceptDrops(True)
    
    def keyPressEvent(self, event):
        # Ctrl+Shift+; (semicolon)
        if event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            if event.key() == Qt.Key.Key_Semicolon:
                self.setDate(QDate.currentDate())
                return
        # Allow all text input
        super().keyPressEvent(event)
    
    def mouseDoubleClickEvent(self, event):
        """Allow double-click to select all for editing"""
        super().mouseDoubleClickEvent(event)
        # Select all text when double-clicked
        self.lineEdit().selectAll() if hasattr(self, 'lineEdit') and self.lineEdit() else None


class RegisterTab(QWidget):
    def __init__(self):
        super().__init__()

        self.load_standards()

        self.case_id = QLineEdit()
        self.case_id.setMaximumWidth(150)
        self.case_id.setPlaceholderText("Enter Case ID")
        self.region = QComboBox()
        self.region.setMaximumWidth(180)
        self.tipo = QComboBox()
        self.tipo.setMaximumWidth(180)
        self.doctor = QLineEdit()
        self.doctor.setPlaceholderText("Optional")
        self.doctor.setMaximumWidth(180)

        self.start_time = TimeEditWithShortcut()
        self.start_time.setMaximumWidth(120)
        
        self.end_time = TimeEditWithShortcut()
        self.end_time.setMaximumWidth(120)
        self.end_time.timeChanged.connect(self.validate_end_time)

        self.case_date = DateEditWithShortcut()
        self.case_date.setDate(QDate.currentDate())
        self.case_date.setMaximumWidth(180)

        self.result_label = QLabel("—")
        self.result_label.setStyleSheet("""
            font-size: 20px;
            font-weight: bold;
            color: #4aa3ff;
            text-align: center;
        """)
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_label.setMinimumHeight(40)
        self.daily_production_label = QLabel("Daily Production: 0.00%")
        self.daily_production_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #2196F3;")

        self.region.addItems(self.standards.keys())
        self.region.currentTextChanged.connect(self.update_case_types)
        
        self.update_case_types()

        self.start_time.setTime(QTime.currentTime())
        self.end_time.setTime(QTime.currentTime())

        calc_btn = QPushButton("Calculate")
        calc_btn.setMaximumWidth(120)
        calc_btn.setMinimumHeight(26)
        save_btn = QPushButton("Save Case")
        save_btn.setMaximumWidth(120)
        save_btn.setMinimumHeight(26)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #444;
            }
            QPushButton:hover {
                background-color: #555;
            }
        """)
        save_btn.clicked.connect(self.save_case)

        calc_btn.clicked.connect(self.calculate)

        # Form layout - centered
        form = QFormLayout()
        form.setSpacing(9)
        form.setContentsMargins(11, 11, 11, 11)
        form.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        form.addRow("Case ID:", self.case_id)
        form.addRow("Region:", self.region)
        form.addRow("Type:", self.tipo)
        form.addRow("Doctor:", self.doctor)
        form.addRow("Date:", self.case_date)
        form.addRow("Start:", self.start_time)
        form.addRow("End:", self.end_time)

        # Buttons layout - centered
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        buttons_layout.addWidget(calc_btn)
        buttons_layout.addWidget(save_btn)
        buttons_layout.addStretch()

        # Result section
        result_layout = QVBoxLayout()
        result_layout.addWidget(self.result_label)

        # Left side layout - formulario centrado
        left_layout = QVBoxLayout()
        left_layout.setSpacing(12)
        left_layout.setContentsMargins(15, 15, 15, 15)
        left_layout.addStretch()
        form_widget = QWidget()
        form_widget.setLayout(form)
        left_layout.addWidget(card("Case Information", form_widget))
        left_layout.addLayout(buttons_layout)
        left_layout.addWidget(card("Calculation Result", result_layout))
        left_layout.addSpacing(12)
        
        # Progress bar section
        progress_layout = QVBoxLayout()
        
        self.daily_production_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        progress_layout.addWidget(self.daily_production_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v%")
        self.progress_bar.setMinimumHeight(28)
        progress_layout.addWidget(self.progress_bar)
        
        progress_group = card("Daily Production (6:00 AM - 3:00 PM)", progress_layout)
        
        left_layout.addWidget(progress_group)
        left_layout.addStretch()
        
        # Right side layout - Downtime Manager
        right_layout = QVBoxLayout()
        right_layout.setSpacing(12)
        right_layout.setContentsMargins(15, 15, 15, 15)
        downtime_widget = DowntimeManager(on_update_callback=self.load_daily_production)
        right_layout.addWidget(downtime_widget)
        
        # Main horizontal layout: Register left, Downtime right
        main_layout = QHBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.addLayout(left_layout, 1)
        main_layout.addLayout(right_layout, 1)
        
        final_layout = QVBoxLayout()
        final_layout.addLayout(main_layout)
        self.setLayout(final_layout)
        
        self.load_daily_production()

    def load_standards(self):
        with open("data/standards.json", "r") as f:
            self.standards = json.load(f)
    
    def update_case_types(self):
        region = self.region.currentText()
        if region and region in self.standards:
            self.tipo.clear()
            self.tipo.addItems(self.standards[region]["Aligners"].keys())
    
    def validate_end_time(self):
        """Ensure end_time is not less than start_time"""
        if self.end_time.time() < self.start_time.time():
            self.end_time.blockSignals(True)
            self.end_time.setTime(self.start_time.time())
            self.end_time.blockSignals(False)
    
    def calculate_case_value(self, std_time):
        """
        Calculate fixed percentage value for a case based on standard time.
        Reference: 9-hour workday (6:00 AM - 3:00 PM) = 540 minutes = 100%
        But using 408.3 minutes as base to match ICON Warford Primary = 6.980%
        Formula: case_value = (std_time / 408.3) * 100
        """
        DAILY_BASE_MINUTES = 408.3  # Base for percentage calculation
        case_value = (std_time / DAILY_BASE_MINUTES) * 100
        return case_value

    def get_daily_downtime(self):
        """Get total downtime minutes for today"""
        conn = get_connection()
        cursor = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        
        cursor.execute("""
            SELECT SUM(duracion)
            FROM downtimes
            WHERE fecha = ?
        """, (today,))
        
        result = cursor.fetchone()
        conn.close()
        
        total_downtime = result[0] if result[0] else 0.0
        return total_downtime

    def calculate(self):
        region = self.region.currentText()
        tipo = self.tipo.currentText()

        if not region or not tipo:
            return

        std_time = self.standards[region]["Aligners"][tipo]
        case_value = self.calculate_case_value(std_time)

        start = self.start_time.time()
        end = self.end_time.time()

        real_minutes = start.secsTo(end) / 60
        if real_minutes <= 0:
            self.result_label.setText("Invalid time")
            return

        efficiency = (std_time / real_minutes) * 100
        
        # Determine status and color
        if efficiency >= 100:
            status = "✓ OK"
            color = "#4CAF50"
        elif efficiency >= 95:
            status = "⚠ WARN"
            color = "#FFC107"
        else:
            status = "✗ LOW"
            color = "#F44336"

        # Display result with dynamic color
        result_text = f"{efficiency:.1f}% – {status}"
        self.result_label.setText(result_text)
        self.result_label.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: bold; text-align: center;")

    def load_daily_production(self):
        conn = get_connection()
        cursor = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Get total case values for today
        cursor.execute("""
            SELECT SUM(case_value)
            FROM cases
            WHERE fecha = ?
        """, (today,))
        
        result = cursor.fetchone()
        conn.close()
        
        total_cases = result[0] if result[0] else 0.0
        
        # Get total downtime and calculate as production value
        total_downtime = self.get_daily_downtime()
        DAILY_BASE_MINUTES = 408.3  # Base for percentage calculation
        downtime_value = (total_downtime / DAILY_BASE_MINUTES) * 100 if total_downtime > 0 else 0
        
        # Total production = cases + downtime (both count as production)
        total_production = total_cases + downtime_value
        
        display_label = f"Daily Production: {total_production:.2f}%"
        if total_downtime > 0:
            display_label += f" (Cases: {total_cases:.2f}% + Downtime: {downtime_value:.2f}%)"
        
        self.daily_production_label.setText(display_label)
        
        # Update progress bar (capped at 100%)
        display_value = min(int(total_production), 100)
        self.progress_bar.setValue(display_value)
        
        # Change color based on performance
        if total_production < 95:
            bar_color = "#F44336"
        elif total_production < 100:
            bar_color = "#FFC107"
        else:
            bar_color = "#4CAF50"
        
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid #3c3c3c;
                border-radius: 8px;
                text-align: center;
                height: 24px;
                background-color: #2b2b2b;
            }}
            QProgressBar::chunk {{
                background-color: {bar_color};
                border-radius: 6px;
            }}
        """)
        
        return total_production

    def save_case(self):
        region = self.region.currentText()
        tipo = self.tipo.currentText()
        case_id = self.case_id.text()
        doctor = self.doctor.text().strip()
        case_date = self.case_date.date().toString("yyyy-MM-dd")

        start = self.start_time.time()
        end = self.end_time.time()

        tiempo_real = start.secsTo(end) / 60
        if tiempo_real <= 0:
            self.result_label.setText("⚠️ Invalid time")
            return

        if not case_id.strip():
            self.result_label.setText("⚠️ Enter Case ID")
            return

        std_time = self.standards[region]["Aligners"][tipo]
        efficiency = (std_time / tiempo_real) * 100
        estado = "OK" if efficiency >= 100 else "LOW"
        case_value = self.calculate_case_value(std_time)

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO cases (
                case_id, region, tipo_caso,
                doctor, fecha, hora_inicio, hora_fin,
                tiempo_real, std_time, efficiency, estado, case_value
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            case_id,
            region,
            tipo,
            doctor if doctor else "",
            case_date,
            start.toString("HH:mm"),
            end.toString("HH:mm"),
            tiempo_real,
            std_time,
            efficiency,
            estado,
            case_value
        ))

        conn.commit()
        conn.close()

        # Show success message with color
        self.result_label.setText("✓ Case Saved")
        self.result_label.setStyleSheet("color: #4CAF50; font-size: 20px; font-weight: bold; text-align: center;")
        self.load_daily_production()
        self.case_id.clear()
        self.doctor.clear()
