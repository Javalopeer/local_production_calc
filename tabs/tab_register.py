import json
import os
import sys

# Add parent directory to path for direct execution
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import (
    QWidget, QFormLayout, QComboBox, QLineEdit,
    QPushButton, QLabel, QTimeEdit, QVBoxLayout, QHBoxLayout, QGroupBox, QProgressBar, QDateEdit, QTextEdit, QScrollArea
)
from PySide6.QtCore import QTime, QDate, Qt, Signal, QPropertyAnimation, QEasingCurve, QTimer
from db.database import get_connection
from .utils import (
    get_resource_path,
    calculate_case_value as _calc_cv,
    load_units_eq_data,
    get_units_per_case as _ue_lookup,
    calculate_equivalent_units,
    calculate_downtime_equivalent_units,
)
from datetime import datetime
from .downtime_manager import DowntimeManager
from .toggle_switch import ToggleSwitch


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
        self._import_toast = None
        self._import_toast_timer = None

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

        # Import from Web button
        import_web_btn = QPushButton("Import")
        import_web_btn.setMaximumWidth(90)
        import_web_btn.setMinimumHeight(26)
        import_web_btn.setToolTip(
            "Copy all text on the case page (Ctrl+A, Ctrl+C),\n"
            "then click here or press Ctrl+Shift+I to auto-fill the fields."
        )
        import_web_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a5c2a;
                color: #7ec890;
            }
            QPushButton:hover {
                background-color: #236b32;
                color: #a8e6b8;
            }
        """)
        import_web_btn.clicked.connect(self._on_import_case)

        # Buttons layout - centered
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        buttons_layout.addWidget(import_web_btn)
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
        
        self.progress_group = card("Daily Production (6:00 AM - 3:00 PM)", progress_layout)
        self.progress_group.setMaximumHeight(130)

        # Create left card (Case Information + Calculation Result)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(12)
        left_layout.setContentsMargins(10, 10, 10, 10)
        
        form_widget = QWidget()
        form_widget.setLayout(form)
        case_info_card = card("Case Information", form_widget)
        
        left_layout.addWidget(case_info_card)
        left_layout.addLayout(buttons_layout)
        left_layout.addWidget(card("Calculation Result", result_layout))
        left_layout.addStretch()
        
        # Create right card (Comments, Downtime, Progress)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
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
        self.downtime_manager = DowntimeManager(on_update_callback=self.load_daily_production)
        self.downtime_manager.setMaximumHeight(300)
        downtime_card = card("Downtime", self.downtime_manager)
        right_layout.addWidget(downtime_card)
        
        # Progress bar in right column (normal mode)
        right_layout.addWidget(self.progress_group)
        right_layout.addStretch()
        
        # Container for responsive layout
        self.content_widget = QWidget()
        self.content_layout = QHBoxLayout(self.content_widget)
        self.content_layout.setSpacing(15)
        self.content_layout.setContentsMargins(5, 5, 5, 5)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        
        self.left_widget = left_widget
        self.right_widget = right_widget
        self.right_layout = right_layout
        
        self.content_layout.addWidget(left_widget)
        self.content_layout.addWidget(right_widget)
        
        # Scroll area for content
        scroll = QScrollArea()
        scroll.setWidget(self.content_widget)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        
        # Main layout
        self.final_layout = QVBoxLayout()
        self.final_layout.setContentsMargins(5, 5, 5, 5)
        self.final_layout.setSpacing(5)
        self.final_layout.addWidget(scroll, 1)
        self.setLayout(self.final_layout)
        
        # Store current layout mode
        self.is_vertical = False
        
        self.load_daily_production()

    def update_theme_labels(self, is_light: bool):
        """Apply table text color changes for light/dark mode across any child tables."""
        from PySide6.QtGui import QBrush, QColor
        from PySide6.QtWidgets import QTableWidget

        # In light mode use dark text; in dark mode use light text
        fg_color = QColor(0, 0, 0) if is_light else QColor(255, 255, 255)
        bg_css = ' QTableWidget { background-color: #ffffff; } QTableWidget::item { background-color: #ffffff; }'
        for table in self.findChildren(QTableWidget):
            if not hasattr(table, '_saved_style'):
                table._saved_style = table.styleSheet() or ''
            if is_light:
                table.setStyleSheet(table._saved_style + bg_css)
            else:
                table.setStyleSheet(table._saved_style)
            for r in range(table.rowCount()):
                for c in range(table.columnCount()):
                    item = table.item(r, c)
                    if item:
                        item.setForeground(QBrush(fg_color))
    
    def resizeEvent(self, event):
        """Handle resize to switch between horizontal and vertical layout"""
        super().resizeEvent(event)
        width = event.size().width()
        
        # Switch to vertical layout when width < 850
        if width < 850 and not self.is_vertical:
            self.is_vertical = True
            self.content_layout.setDirection(QVBoxLayout.Direction.TopToBottom)
            # Set fixed width so widgets center properly and are wider
            responsive_width = min(width - 40, 600)  # Use most of available width
            self.left_widget.setFixedWidth(responsive_width)
            self.right_widget.setFixedWidth(responsive_width)
            # Move progress bar to sticky bottom
            self.right_layout.removeWidget(self.progress_group)
            self.final_layout.addWidget(self.progress_group, 0)
        elif width >= 850 and self.is_vertical:
            self.is_vertical = False
            self.content_layout.setDirection(QHBoxLayout.Direction.LeftToRight)
            # Remove fixed width in horizontal mode
            self.left_widget.setMinimumWidth(0)
            self.left_widget.setMaximumWidth(16777215)
            self.right_widget.setMinimumWidth(0)
            self.right_widget.setMaximumWidth(16777215)
            # Move progress bar back to right column
            self.final_layout.removeWidget(self.progress_group)
            self.right_layout.insertWidget(2, self.progress_group)  # After downtime
        elif self.is_vertical:
            # Update width when resizing in vertical mode
            responsive_width = min(width - 40, 600)
            self.left_widget.setFixedWidth(responsive_width)
            self.right_widget.setFixedWidth(responsive_width)

        self._reposition_import_toast()

    def _show_import_toast(self, message: str, duration_ms: int = 4200):
        """Show a floating top-right toast in Register tab after import."""
        if self._import_toast is None:
            self._import_toast = QLabel(self)
            self._import_toast.setWordWrap(True)
            self._import_toast.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._import_toast.setStyleSheet(
                """
                QLabel {
                    background-color: rgba(28, 34, 42, 235);
                    color: #EAF2FF;
                    border: 1px solid #2d89ef;
                    border-radius: 9px;
                    padding: 8px 10px;
                    font-size: 11px;
                    font-weight: 600;
                }
                """
            )

        self._import_toast.setText(message)
        self._import_toast.setFixedWidth(min(420, max(280, int(self.width() * 0.42))))
        self._import_toast.adjustSize()
        self._reposition_import_toast()
        self._import_toast.show()
        self._import_toast.raise_()

        if self._import_toast_timer is None:
            self._import_toast_timer = QTimer(self)
            self._import_toast_timer.setSingleShot(True)
            self._import_toast_timer.timeout.connect(self._import_toast.hide)

        self._import_toast_timer.start(duration_ms)

    def _reposition_import_toast(self):
        if not self._import_toast or not self._import_toast.isVisible():
            return
        margin = 14
        x = max(margin, self.width() - self._import_toast.width() - margin)
        y = margin
        self._import_toast.move(x, y)

    def load_standards(self):
        standards_path = get_resource_path(os.path.join("data", "standards.json"))
        with open(standards_path, "r") as f:
            self.standards = json.load(f)

    def load_units_eq(self):
        """Load units equivalency for production calculation"""
        self.units_eq = load_units_eq_data()

    def get_units_per_case(self, region, case_type):
        """Return UE value for a specific region+case_type."""
        return _ue_lookup(self.units_eq, region, case_type)
    
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
        """Calculate fixed percentage value for a case based on standard time."""
        return _calc_cv(std_time)

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

        # Auto-set end time to now
        self.end_time.blockSignals(True)
        self.end_time.setTime(QTime.currentTime())
        self.end_time.blockSignals(False)

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
        """Called when the date picker changes - reload production and downtime for that date"""
        selected_date = self.case_date.date().toString("yyyy-MM-dd")
        self.downtime_manager.set_date(selected_date)
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
        
        # Get cases by region+type for equivalent units calculation (only count_production = 1)
        cursor.execute("""
            SELECT region, tipo_caso, COUNT(*), SUM(case_value)
            FROM cases
            WHERE fecha = ? AND (count_production = 1 OR count_production IS NULL)
            GROUP BY region, tipo_caso
        """, (selected_date,))

        region_cases = cursor.fetchall()
        conn.close()

        # Calculate equivalent units supporting both legacy and per-type UE models
        total_equivalent_units = 0.0
        for region, case_type, count, sum_cv in region_cases:
            if count and sum_cv:
                total_equivalent_units += calculate_equivalent_units(
                    self.units_eq,
                    region,
                    case_type,
                    sum_cv,
                    count=count,
                )
        
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
        downtime_equivalent_units = calculate_downtime_equivalent_units(total_downtime)
        total_equivalent_units += downtime_equivalent_units

        eq_label = f"Equivalent Units: {total_equivalent_units:.2f}"
        if downtime_equivalent_units > 0:
            eq_label += (
                f" (Cases: {total_equivalent_units - downtime_equivalent_units:.2f}"
                f" + Downtime: {downtime_equivalent_units:.2f})"
            )
        self.equivalent_units_label.setText(eq_label)
        
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
                color: #ffffff;
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

    # ── Web Import ────────────────────────────────────────────────────────

    def _on_import_case(self):
        """
        Read the clipboard, show a confirmation dialog with the detected data,
        and fill the fields only if the user confirms.
        """
        from sync.clipboard_import import parse_clipboard
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QHBoxLayout, QPushButton

        data = parse_clipboard(self.standards)

        # Nothing found — show error directly, no dialog
        if not any(data.get(k) for k in ('case_id', 'region', 'tipo', 'doctor')):
            self.result_label.setText(
                "Nothing detected in clipboard.\n"
                "On the case page: press Ctrl+A then Ctrl+C, then try again."
            )
            self.result_label.setStyleSheet(
                "color: #FFC107; font-size: 12px; font-weight: bold; text-align: center;"
            )
            return

        # Build confirmation dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("Import from Clipboard")
        dlg.setMinimumWidth(300)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)

        header = QLabel("Import this case?")
        header.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(header)

        rows = [
            ("Case ID", data.get('case_id', '—')),
            ("Region",  data.get('region',  '—')),
            ("Type",    data.get('tipo',    '—')),
            ("Doctor",  data.get('doctor',  '—')),
        ]
        for label_text, value in rows:
            row_lbl = QLabel(f"<b>{label_text}:</b>  {value}")
            row_lbl.setWordWrap(True)
            layout.addWidget(row_lbl)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_cancel = QPushButton("Cancel")
        btn_import = QPushButton("Import")
        btn_import.setDefault(True)
        btn_import.setStyleSheet(
            "background-color: #1a5c2a; color: #7ec890; font-weight: bold;"
        )
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_import)
        layout.addLayout(btn_layout)

        btn_cancel.clicked.connect(dlg.reject)
        btn_import.clicked.connect(dlg.accept)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # User confirmed — fill fields
        imported_case_id = None
        imported_region = None
        imported_type = None

        if data.get('case_id'):
            self.case_id.setText(data['case_id'])
            imported_case_id = data['case_id']

        if data.get('region'):
            idx = self.region.findText(data['region'])
            if idx >= 0:
                self.region.blockSignals(True)
                self.region.setCurrentIndex(idx)
                self.region.blockSignals(False)
                self.update_case_types()
                imported_region = data['region']

        if data.get('tipo'):
            idx = self.tipo.findText(data['tipo'])
            if idx >= 0:
                self.tipo.setCurrentIndex(idx)
                imported_type = data['tipo']

        if data.get('doctor'):
            self.doctor.setText(data['doctor'])

        self.start_time.setTime(QTime.currentTime())

        summary_parts = [p for p in (imported_case_id, imported_region, imported_type) if p]
        summary = " | ".join(summary_parts) if summary_parts else "Case imported"
        self.result_label.setText(f"Imported: {summary}\nClick Calculate.")
        self.result_label.setStyleSheet(
            "color: #4CAF50; font-size: 11px; font-weight: bold; text-align: center;"
        )

        self._show_import_toast(
            "Verify if the case is Stage RX or Bite Sync.\n"
            "Import currently does not auto-detect this.",
            duration_ms=4200,
        )

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
        
        # Clear end time - set to midnight (00:00)
        self.end_time.blockSignals(True)
        self.end_time.setTime(QTime(0, 0))
        self.end_time.blockSignals(False)
        
        # Emit signal to notify other tabs
        self.case_saved.emit()
