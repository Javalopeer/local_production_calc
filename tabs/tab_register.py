import json
import os
import sys

# Add parent directory to path for direct execution
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import (
    QWidget, QFormLayout, QComboBox, QLineEdit,
    QPushButton, QLabel, QTimeEdit, QVBoxLayout, QHBoxLayout, QGroupBox, QProgressBar, QTabWidget, QDateEdit, QTextEdit
)
from PySide6.QtCore import QTime, QDate, Qt, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont
from db.database import get_connection
from datetime import datetime
from .downtime_manager import DowntimeManager
from .toggle_switch import ToggleSwitch


def get_resource_path(relative_path):
    """Get absolute path to resource - works for dev and PyInstaller"""
    if getattr(sys, 'frozen', False):
        # Running as compiled exe - look in exe directory first, then _MEIPASS
        exe_dir = os.path.dirname(sys.executable)
        exe_path = os.path.join(exe_dir, relative_path)
        if os.path.exists(exe_path):
            return exe_path
        # Fall back to bundled data
        return os.path.join(sys._MEIPASS, relative_path)
    else:
        # Running as script
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, relative_path)


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
    case_saved = Signal()  # Signal emitted when a case is saved
    
    def __init__(self):
        super().__init__()
        self.editing_case_id = None  # Track if we're editing a case

        self.load_standards()
        self.load_units_eq()

        self.case_id = QLineEdit()
        self.case_id.setMaximumWidth(150)
        self.case_id.setPlaceholderText("Enter Case ID")
        self.case_id.textChanged.connect(self.on_case_id_changed)
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
        self.case_date.dateChanged.connect(self.on_date_changed)

        self.result_label = QLabel("—")
        self.result_label.setStyleSheet("""
            font-size: 13px;
            font-weight: bold;
            color: #4aa3ff;
            text-align: center;
        """)
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_label.setWordWrap(True)
        self.result_label.setMinimumHeight(50)
        self.result_label.setMaximumHeight(50)
        self.daily_production_label = QLabel("Daily Production: 0.00%")
        self.daily_production_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #2196F3;")
        
        self.equivalent_units_label = QLabel("Equivalent Units: 0.00")
        self.equivalent_units_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #9C27B0;")

        self.region.addItems(self.standards.keys())
        self.region.currentTextChanged.connect(self.update_case_types)
        
        self.update_case_types()

        self.start_time.setTime(QTime.currentTime())
        self.end_time.setTime(QTime(0, 0))  # Empty/default value

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
        
        # Count to production toggle
        self.count_toggle = ToggleSwitch(checked=True)
        toggle_layout = QHBoxLayout()
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_label = QLabel("Count to production?")
        toggle_label.setStyleSheet("font-size: 11px; color: #aaa;")
        toggle_layout.addWidget(toggle_label)
        toggle_layout.addWidget(self.count_toggle)
        toggle_layout.addStretch()
        toggle_widget = QWidget()
        toggle_widget.setLayout(toggle_layout)
        form.addRow("", toggle_widget)

        # Buttons layout - centered
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        buttons_layout.addWidget(calc_btn)
        buttons_layout.addWidget(save_btn)
        buttons_layout.addStretch()

        # Result section
        result_layout = QVBoxLayout()
        result_layout.addWidget(self.result_label)

        # Progress bar section
        progress_layout = QVBoxLayout()
        self.daily_production_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        progress_layout.addWidget(self.daily_production_label)
        
        self.equivalent_units_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        progress_layout.addWidget(self.equivalent_units_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v%")
        self.progress_bar.setMinimumHeight(28)
        progress_layout.addWidget(self.progress_bar)
        
        progress_group = card("Daily Production (6:00 AM - 3:00 PM)", progress_layout)

        # Left side layout - Case Information y Calculation Result
        left_layout = QVBoxLayout()
        left_layout.setSpacing(12)
        left_layout.setContentsMargins(15, 15, 15, 0)
        
        form_widget = QWidget()
        form_widget.setLayout(form)
        case_info_card = card("Case Information", form_widget)
        
        left_layout.addWidget(case_info_card)
        left_layout.addLayout(buttons_layout)
        left_layout.addWidget(card("Calculation Result", result_layout))
        left_layout.addStretch()
        
        # Right side layout - Comments, Downtime, Daily Production
        right_layout = QVBoxLayout()
        right_layout.setSpacing(12)
        right_layout.setContentsMargins(10, 10, 10, 10)
        
        # Comments section 
        self.comments_input = QTextEdit()
        self.comments_input.setPlaceholderText("Optional comments...")
        self.comments_input.setMaximumHeight(45)
        self.comments_input.setStyleSheet("font-size: 11px; padding: 3px;")
        comments_card = card("Comments (Optional)", self.comments_input)
        comments_card.setMaximumHeight(100)
        right_layout.addWidget(comments_card)
        
        # Downtime section
        downtime_widget = DowntimeManager(on_update_callback=self.load_daily_production)
        downtime_widget.setMaximumHeight(300)
        downtime_card = card("Downtime", downtime_widget)
        right_layout.addWidget(downtime_card)
        
        right_layout.addWidget(progress_group)
        
        # Main horizontal layout: Register left, Production+Downtime right
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
        standards_path = get_resource_path(os.path.join("data", "standards.json"))
        with open(standards_path, "r") as f:
            self.standards = json.load(f)

    def load_units_eq(self):
        """Load units equivalency for production calculation"""
        units_path = get_resource_path(os.path.join("data", "units_eq.json"))
        with open(units_path, "r") as f:
            self.units_eq = json.load(f)
    
    def get_units_for_production(self, region, production_pct):
        """
        Get units needed for a given production percentage based on region.
        Uses linear interpolation between defined thresholds.
        """
        if region not in self.units_eq:
            return 0
        
        region_data = self.units_eq[region]
        thresholds = sorted([int(k) for k in region_data.keys()], reverse=True)
        
        # If production is at or above highest threshold
        if production_pct >= thresholds[0]:
            # Calculate units per percent and extrapolate
            units_per_5pct = region_data[str(thresholds[0])] - region_data[str(thresholds[1])]
            extra_pct = production_pct - thresholds[0]
            extra_units = (extra_pct / 5) * units_per_5pct
            return region_data[str(thresholds[0])] + extra_units
        
        # Find the two thresholds to interpolate between
        for i in range(len(thresholds) - 1):
            if thresholds[i] >= production_pct >= thresholds[i + 1]:
                upper = thresholds[i]
                lower = thresholds[i + 1]
                upper_units = region_data[str(upper)]
                lower_units = region_data[str(lower)]
                
                # Linear interpolation
                ratio = (production_pct - lower) / (upper - lower)
                return lower_units + (upper_units - lower_units) * ratio
        
        # Below minimum threshold - extrapolate down
        lowest = thresholds[-1]
        second_lowest = thresholds[-2]
        units_per_5pct = region_data[str(second_lowest)] - region_data[str(lowest)]
        below_pct = lowest - production_pct
        return max(0, region_data[str(lowest)] - (below_pct / 5) * units_per_5pct)
    
    def on_case_id_changed(self, text):
        """Auto-set start time when Case ID is first entered"""
        if text and len(text) == 1:  # First character entered
            self.start_time.setTime(QTime.currentTime())
    
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

    def get_daily_downtime(self, date=None):
        """Get total downtime minutes for given date (or today if not specified)"""
        conn = get_connection()
        cursor = conn.cursor()
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        cursor.execute("""
            SELECT SUM(duracion)
            FROM downtimes
            WHERE fecha = ?
        """, (date,))
        
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
            status = "OK"
            color = "#4CAF50"
        elif efficiency >= 95:
            status = "WARN"
            color = "#FFC107"
        else:
            status = "LOW"
            color = "#F44336"

        # Display result with dynamic color showing efficiency and case value in two lines
        result_text = f"{efficiency:.1f}% – {status}\nCase Value: {case_value:.3f}%"
        self.result_label.setText(result_text)
        self.result_label.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold; text-align: center;")

    def on_date_changed(self):
        """Called when the date picker changes - reload production for that date"""
        self.load_daily_production()

    def load_daily_production(self):
        conn = get_connection()
        cursor = conn.cursor()
        # Use selected date from picker instead of today
        selected_date = self.case_date.date().toString("yyyy-MM-dd")
        
        # Get total case values for selected date (only count_production = 1)
        cursor.execute("""
            SELECT SUM(case_value)
            FROM cases
            WHERE fecha = ? AND (count_production = 1 OR count_production IS NULL)
        """, (selected_date,))
        
        result = cursor.fetchone()
        total_cases = result[0] if result[0] else 0.0
        
        # Get cases by region for equivalent units calculation (only count_production = 1)
        cursor.execute("""
            SELECT region, SUM(case_value)
            FROM cases
            WHERE fecha = ? AND (count_production = 1 OR count_production IS NULL)
            GROUP BY region
        """, (selected_date,))
        
        region_cases = cursor.fetchall()
        conn.close()
        
        # Calculate equivalent units based on region
        total_equivalent_units = 0.0
        for region, case_value in region_cases:
            if region in self.units_eq and case_value:
                # Get units at 100% for this region
                units_at_100 = self.units_eq[region].get("100", 0)
                # Equivalent units = (case_value / 100) * units_at_100
                total_equivalent_units += (case_value / 100) * units_at_100
        
        # Get total downtime and calculate as production value
        total_downtime = self.get_daily_downtime(selected_date)
        DAILY_BASE_MINUTES = 408.3  # Base for percentage calculation
        downtime_value = (total_downtime / DAILY_BASE_MINUTES) * 100 if total_downtime > 0 else 0
        
        # Total production = cases + downtime (both count as production)
        total_production = total_cases + downtime_value
        
        display_label = f"Daily Production: {total_production:.2f}%"
        if total_downtime > 0:
            display_label += f" (Cases: {total_cases:.2f}% + Downtime: {downtime_value:.2f}%)"
        
        self.daily_production_label.setText(display_label)
        self.equivalent_units_label.setText(f"Equivalent Units: {total_equivalent_units:.2f}")
        
        # Update progress bar with animation - NO CAP, allow any value
        self.progress_bar.setMaximum(max(100, int(total_production) + 10))
        
        # Animate the progress bar
        self.animate_progress_bar(int(total_production))
        
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

    def animate_progress_bar(self, target_value):
        """Animate the progress bar to the target value"""
        current_value = self.progress_bar.value()
        
        if not hasattr(self, '_progress_animation'):
            self._progress_animation = QPropertyAnimation(self.progress_bar, b"value")
            self._progress_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        
        self._progress_animation.stop()
        self._progress_animation.setDuration(500)  # 500ms smoother animation
        self._progress_animation.setStartValue(current_value)
        self._progress_animation.setEndValue(target_value)
        self._progress_animation.start()

    def load_case_for_edit(self, db_id):
        """Load a case from database into form for editing"""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT case_id, region, tipo_caso, doctor, fecha, hora_inicio, hora_fin, count_production, comments
            FROM cases WHERE id = ?
        """, (db_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            self.editing_case_id = db_id
            self.case_id.setText(row[0])
            
            # Set region and type
            region_idx = self.region.findText(row[1])
            if region_idx >= 0:
                self.region.setCurrentIndex(region_idx)
            self.update_case_types()
            type_idx = self.tipo.findText(row[2])
            if type_idx >= 0:
                self.tipo.setCurrentIndex(type_idx)
            
            self.doctor.setText(row[3] if row[3] else "")
            self.case_date.setDate(QDate.fromString(row[4], "yyyy-MM-dd"))
            self.start_time.setTime(QTime.fromString(row[5], "HH:mm"))
            self.end_time.setTime(QTime.fromString(row[6], "HH:mm"))
            
            # Set toggle state
            count_prod = row[7] if row[7] is not None else 1
            self.count_toggle.setChecked(bool(count_prod))
            
            # Set comments
            self.comments_input.setText(row[8] if row[8] else "")
            
            self.result_label.setText("Editing - Click Save to update")
            self.result_label.setStyleSheet("color: #FFC107; font-size: 13px; font-weight: bold; text-align: center;")

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
            self.result_label.setText("Invalid time")
            return

        if not case_id.strip():
            self.result_label.setText("Enter Case ID")
            return

        std_time = self.standards[region]["Aligners"][tipo]
        efficiency = (std_time / tiempo_real) * 100
        estado = "OK" if efficiency >= 100 else "LOW"
        case_value = self.calculate_case_value(std_time)

        conn = get_connection()
        cursor = conn.cursor()
        
        # Get toggle and comments values
        count_production = 1 if self.count_toggle.isChecked() else 0
        comments = self.comments_input.toPlainText().strip()

        # Check if we're editing an existing case
        if self.editing_case_id:
            cursor.execute("""
                UPDATE cases SET
                    case_id = ?, region = ?, tipo_caso = ?,
                    doctor = ?, fecha = ?, hora_inicio = ?, hora_fin = ?,
                    tiempo_real = ?, std_time = ?, efficiency = ?, estado = ?, case_value = ?,
                    count_production = ?, comments = ?
                WHERE id = ?
            """, (
                case_id, region, tipo,
                doctor if doctor else "", case_date,
                start.toString("HH:mm"), end.toString("HH:mm"),
                tiempo_real, std_time, efficiency, estado, case_value,
                count_production, comments,
                self.editing_case_id
            ))
            self.editing_case_id = None
            msg = "Case Updated"
        else:
            cursor.execute("""
                INSERT INTO cases (
                    case_id, region, tipo_caso,
                    doctor, fecha, hora_inicio, hora_fin,
                    tiempo_real, std_time, efficiency, estado, case_value,
                    count_production, comments
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                case_id, region, tipo,
                doctor if doctor else "", case_date,
                start.toString("HH:mm"), end.toString("HH:mm"),
                tiempo_real, std_time, efficiency, estado, case_value,
                count_production, comments
            ))
            msg = "Case Saved"

        conn.commit()
        conn.close()

        # Show success message with color
        self.result_label.setText(msg)
        self.result_label.setStyleSheet("color: #4CAF50; font-size: 13px; font-weight: bold; text-align: center;")
        self.load_daily_production()
        self.case_id.clear()
        self.doctor.clear()
        self.comments_input.clear()
        self.count_toggle.setChecked(True)  # Reset toggle to ON
        self.end_time.setTime(QTime(0, 0))  # Clear end time
        
        # Emit signal to notify other tabs
        self.case_saved.emit()
