import json
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QComboBox, QLineEdit,
    QPushButton, QLabel, QTimeEdit, QVBoxLayout, QHBoxLayout, QGroupBox, QProgressBar, QTabWidget
)
from PySide6.QtCore import QTime, QDate, Qt
from PySide6.QtGui import QFont
from db.database import get_connection
from datetime import datetime
from .downtime_manager import DowntimeManager


class TimeEditWithShortcut(QTimeEdit):
    """QTimeEdit con soporte para Ctrl+Shift+: para hora actual"""
    def keyPressEvent(self, event):
        # Ctrl+Shift+:
        if event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            if event.key() == Qt.Key.Key_Colon:
                self.setTime(QTime.currentTime())
                return
        super().keyPressEvent(event)


class RegisterTab(QWidget):
    def __init__(self):
        super().__init__()

        self.load_standards()

        self.case_id = QLineEdit()
        self.case_id.setMaximumWidth(120)
        self.region = QComboBox()
        self.region.setMaximumWidth(150)
        self.tipo = QComboBox()
        self.tipo.setMaximumWidth(150)
        self.doctor = QLineEdit()
        self.doctor.setPlaceholderText("Optional")
        self.doctor.setMaximumWidth(150)

        self.start_time = TimeEditWithShortcut()
        self.start_time.setMaximumWidth(100)
        
        self.end_time = TimeEditWithShortcut()
        self.end_time.setMaximumWidth(100)

        self.result_label = QLabel("Production: -")
        self.result_label.setStyleSheet("font-size: 12px;")
        self.daily_production_label = QLabel("Daily Production: 0.00%")
        self.daily_production_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #2196F3;")

        self.region.addItems(self.standards.keys())
        self.region.currentTextChanged.connect(self.update_case_types)
        
        self.update_case_types()

        self.start_time.setTime(QTime.currentTime())
        self.end_time.setTime(QTime.currentTime())

        calc_btn = QPushButton("Calculate")
        calc_btn.setMaximumWidth(100)
        save_btn = QPushButton("Save Case")
        save_btn.setMaximumWidth(100)
        save_btn.clicked.connect(self.save_case)

        calc_btn.clicked.connect(self.calculate)

        # Form layout - mas compacto
        form = QFormLayout()
        form.setSpacing(10)
        form.setContentsMargins(10, 10, 10, 10)
        form.addRow("Case ID:", self.case_id)
        form.addRow("Region:", self.region)
        form.addRow("Type:", self.tipo)
        form.addRow("Doctor:", self.doctor)
        form.addRow("Start:", self.start_time)
        form.addRow("End:", self.end_time)

        # Buttons layout
        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(calc_btn)
        buttons_layout.addWidget(save_btn)
        buttons_layout.addStretch()

        # Left side layout - formulario compacto
        left_layout = QVBoxLayout()
        left_layout.addLayout(form)
        left_layout.addLayout(buttons_layout)
        left_layout.addWidget(self.result_label)
        left_layout.addSpacing(15)
        
        # Progress bar section
        progress_group = QGroupBox("Daily Production (6:00 AM - 3:00 PM)")
        progress_layout = QVBoxLayout()
        
        self.daily_production_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        progress_layout.addWidget(self.daily_production_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v%")
        self.progress_bar.setMinimumHeight(40)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid grey;
                border-radius: 5px;
                text-align: center;
                font-size: 18px;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #4CAF50, stop:1 #8BC34A);
                border-radius: 3px;
            }
        """)
        progress_layout.addWidget(self.progress_bar)
        progress_group.setLayout(progress_layout)
        
        left_layout.addWidget(progress_group)
        left_layout.addStretch()
        
        # Main layout con tabs: Register y Downtime
        main_tabs = QTabWidget()
        
        # Tab 1: Register (formulario compacto)
        register_widget = QWidget()
        register_layout = QVBoxLayout()
        register_layout.addLayout(left_layout)
        register_widget.setLayout(register_layout)
        main_tabs.addTab(register_widget, "Register")
        
        # Tab 2: Downtime
        downtime_widget = DowntimeManager(on_update_callback=self.load_daily_production)
        main_tabs.addTab(downtime_widget, "Downtime")
        
        final_layout = QVBoxLayout()
        final_layout.addWidget(main_tabs)
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
        estado = "🟢 OK" if efficiency >= 100 else "🔴 LOW"

        self.result_label.setText(
            f"Std: {std_time:.1f} min | Real: {real_minutes:.1f} min | Efficiency: {efficiency:.1f}% {estado}\n"
            f"Case Value: {case_value:.3f}%"
        )

    def load_daily_production(self):
        conn = get_connection()
        cursor = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Get total case values
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
        if total_production >= 100:
            self.progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 2px solid grey;
                    border-radius: 5px;
                    text-align: center;
                    font-size: 18px;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                        stop:0 #4CAF50, stop:1 #66BB6A);
                    border-radius: 3px;
                }
            """)
        elif total_production >= 80:
            self.progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 2px solid grey;
                    border-radius: 5px;
                    text-align: center;
                    font-size: 18px;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                        stop:0 #FFC107, stop:1 #FFD54F);
                    border-radius: 3px;
                }
            """)
        else:
            self.progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 2px solid grey;
                    border-radius: 5px;
                    text-align: center;
                    font-size: 18px;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                        stop:0 #F44336, stop:1 #EF5350);
                    border-radius: 3px;
                }
            """)
        
        return total_production

    def save_case(self):
        region = self.region.currentText()
        tipo = self.tipo.currentText()
        case_id = self.case_id.text()
        doctor = self.doctor.text().strip()

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
            datetime.now().strftime("%Y-%m-%d"),
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

        self.result_label.setText(f"✅ Case saved | Value: {case_value:.3f}% | Efficiency: {efficiency:.1f}%")
        self.load_daily_production()
        self.case_id.clear()
        self.doctor.clear()
