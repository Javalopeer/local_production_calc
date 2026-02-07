import json
import os
import sys
import re
from PySide6.QtWidgets import (
    QApplication, QWidget, QFormLayout, QComboBox, QLineEdit,
    QPushButton, QLabel, QTimeEdit, QVBoxLayout, QHBoxLayout, QGroupBox, QDateEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QTextEdit, QProgressBar, QScrollArea, QDoubleSpinBox, QSpinBox, QFrame
)
from PySide6.QtWidgets import QAbstractSpinBox
from PySide6.QtCore import QTime, QDate, Qt, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont, QColor, QBrush
from db.database import get_connection
from datetime import datetime
from .toggle_switch import ToggleSwitch


def get_resource_path(relative_path):
    """Get absolute path to resource - works for dev and PyInstaller"""
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        exe_path = os.path.join(exe_dir, relative_path)
        if os.path.exists(exe_path):
            return exe_path
        return os.path.join(sys._MEIPASS, relative_path)
    else:
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
    """QTimeEdit con soporte para Ctrl+Shift+: para hora actual"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDisplayFormat("HH:mm")
        self.setCorrectionMode(QTimeEdit.CorrectToNearestValue)
    
    def keyPressEvent(self, event):
        if event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            if event.key() == Qt.Key.Key_Colon:
                self.setTime(QTime.currentTime())
                return
        super().keyPressEvent(event)


class DateEditWithShortcut(QDateEdit):
    """QDateEdit con soporte para Ctrl+Shift+; para fecha actual"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDisplayFormat("yyyy-MM-dd")
        self.setCalendarPopup(True)
    
    def keyPressEvent(self, event):
        if event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            if event.key() == Qt.Key.Key_Semicolon:
                self.setDate(QDate.currentDate())
                return
        super().keyPressEvent(event)


class OvertimeTab(QWidget):
    ot_saved = Signal()  # Signal emitted when OT case is saved
    
    def __init__(self):
        super().__init__()
        self.ot_case_ids = []  # Store database IDs for edit/delete
        self.editing_ot_id = None  # Track if we're editing a case
        self.load_standards()
        self.load_units_eq()
        self.init_ui()

    def load_standards(self):
        standards_path = get_resource_path(os.path.join("data", "standards.json"))
        with open(standards_path, "r") as f:
            self.standards = json.load(f)

    def load_units_eq(self):
        units_path = get_resource_path(os.path.join("data", "units_eq.json"))
        with open(units_path, "r") as f:
            self.units_eq = json.load(f)
    
    def calculate_units_eq(self, region, case_value):
        """Calculate equivalent units for a case based on region and value"""
        if not case_value:
            return 0.0

        # direct match
        if region in self.units_eq:
            units_at_100 = self.units_eq[region].get("100", 0)
            return (case_value / 100) * units_at_100

        # fallback: try to find a close key by normalizing names (remove non-alnum, lowercase)
        def norm(s):
            return re.sub(r'[^a-z0-9]', '', s.lower()) if s else ''

        rnorm = norm(region)
        for k in self.units_eq.keys():
            kn = norm(k)
            if kn and (kn in rnorm or rnorm in kn):
                units_at_100 = self.units_eq[k].get("100", 0)
                return (case_value / 100) * units_at_100

        # no match
        return 0.0

    def init_ui(self):
        # Form fields
        self.case_id = QLineEdit()
        self.case_id.setMaximumWidth(150)
        self.case_id.setPlaceholderText("Enter Case ID")
        self.case_id.textChanged.connect(self.on_case_id_changed)
        
        self.region = QComboBox()
        self.region.setMaximumWidth(180)
        self.region.addItems(self.standards.keys())
        self.region.currentTextChanged.connect(self.update_case_types)
        
        self.tipo = QComboBox()
        self.tipo.setMaximumWidth(180)
        
        self.doctor = QLineEdit()
        self.doctor.setPlaceholderText("Optional")
        self.doctor.setMaximumWidth(180)

        self.start_time = TimeEditWithShortcut()
        self.start_time.setMaximumWidth(120)
        self.start_time.setTime(QTime.currentTime())
        
        self.end_time = TimeEditWithShortcut()
        self.end_time.setMaximumWidth(120)
        self.end_time.setTime(QTime(0, 0))  # Empty/default value
        self.end_time.timeChanged.connect(self.validate_end_time)

        self.case_date = DateEditWithShortcut()
        self.case_date.setDate(QDate.currentDate())
        self.case_date.setMaximumWidth(180)
        self.case_date.dateChanged.connect(self.on_date_changed)

        self.result_label = QLabel("—")
        self.result_label.setStyleSheet("""
            font-size: 13px;
            font-weight: bold;
            color: #FF9800;
            text-align: center;
        """)
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_label.setWordWrap(True)
        self.result_label.setMinimumHeight(50)

        self.update_case_types()

        # Buttons
        calc_btn = QPushButton("Calculate")
        calc_btn.setMaximumWidth(120)
        calc_btn.setMinimumHeight(26)
        calc_btn.clicked.connect(self.calculate)
        
        save_btn = QPushButton("Save OT Case")
        save_btn.setMaximumWidth(120)
        save_btn.setMinimumHeight(26)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
        """)
        save_btn.clicked.connect(self.save_ot_case)

        # Form layout
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
        toggle_label.setStyleSheet("font-size: 11px; color: #000000;")
        toggle_layout.addWidget(toggle_label)
        toggle_layout.addWidget(self.count_toggle)
        toggle_layout.addStretch()
        toggle_widget = QWidget()
        toggle_widget.setLayout(toggle_layout)
        form.addRow("", toggle_widget)

        # Buttons layout
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        buttons_layout.addWidget(calc_btn)
        buttons_layout.addWidget(save_btn)
        buttons_layout.addStretch()

        # Result section
        result_layout = QVBoxLayout()
        result_layout.addWidget(self.result_label)

        # Daily OT Production and Equivalent Units
        self.daily_ot_label = QLabel("OT Production: 0.00%")
        self.daily_ot_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #FF9800;")
        self.daily_ot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.ot_units_label = QLabel("OT Equivalent Units: 0.00")
        self.ot_units_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #9C27B0;")
        self.ot_units_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Comments section
        self.comments_input = QTextEdit()
        self.comments_input.setPlaceholderText("Optional comments...")
        self.comments_input.setMaximumHeight(100)
        self.comments_input.setStyleSheet("font-size: 11px; padding: 3px;")

        # Left layout
        left_layout = QVBoxLayout()
        left_layout.setSpacing(10)
        left_layout.setContentsMargins(15, 15, 15, 15)
        
        form_widget = QWidget()
        form_widget.setLayout(form)

        # Build a combined case info card: form on the left, estimate panel on the right
        case_card_widget = QWidget()
        case_card_layout = QHBoxLayout()
        case_card_layout.setContentsMargins(6, 6, 6, 6)
        case_card_layout.setSpacing(12)

        # Left: the existing form
        case_card_layout.addWidget(form_widget, 1)

        # Vertical separator between left form and right estimate panel
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setLineWidth(1)
        separator.setFixedWidth(1)
        separator.setStyleSheet("background-color: #3c3c3c;")
        case_card_layout.addWidget(separator)

        # Right: compact estimate panel (region, hours, button, result)
        estimate_panel = QWidget()
        estimate_panel_layout = QVBoxLayout()
        estimate_panel_layout.setContentsMargins(0, 0, 0, 0)
        estimate_panel_layout.setSpacing(8)

        # Region selector for estimate (independent from left-side region)
        self.est_region_combo = QComboBox()
        self.est_region_combo.addItems(sorted(self.standards.keys()))
        self.est_region_combo.setMaximumWidth(160)
        # region selector will be applied when user clicks Estimate

        estimate_panel_layout.addWidget(self.est_region_combo)

        self.ot_hours_spin = QDoubleSpinBox()
        self.ot_hours_spin.setRange(0.25, 12.0)
        self.ot_hours_spin.setSingleStep(0.25)
        self.ot_hours_spin.setValue(1.0)
        self.ot_hours_spin.setSuffix(" h")
        self.ot_hours_spin.setMaximumWidth(120)

        estimate_btn = QPushButton("Estimate")
        estimate_btn.setMaximumWidth(120)
        estimate_btn.clicked.connect(self.calculate_for_hours)

        self.estimate_label = QLabel("")
        self.estimate_label.setWordWrap(True)
        self.estimate_label.setStyleSheet("font-size:12px; color:#222222;")
        self.estimate_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        # hide the overall quick summary — we'll show per-type info next to each spinbox
        self.estimate_label.hide()

        # counts per type area
        self.estimate_counts_layout = QFormLayout()
        self.estimate_counts_layout.setSpacing(6)
        self.estimate_counts_widget = QWidget()
        self.estimate_counts_widget.setLayout(self.estimate_counts_layout)
        # hide until user presses Estimate
        self.estimate_counts_widget.hide()

        # per-type info labels (populated in update_estimate_types)
        self.estimate_info_labels = {}

        estimate_panel_layout.addWidget(self.ot_hours_spin)
        estimate_panel_layout.addWidget(estimate_btn)
        estimate_panel_layout.addWidget(self.estimate_label)
        estimate_panel_layout.addWidget(self.estimate_counts_widget)
        estimate_panel_layout.addStretch()
        estimate_panel.setLayout(estimate_panel_layout)
        estimate_panel.setMaximumWidth(260)

        case_card_layout.addWidget(estimate_panel, 0)
        case_card_widget.setLayout(case_card_layout)

        case_info_card = card("OT Case Information", case_card_widget)

        left_layout.addWidget(case_info_card)

        # initialize estimate type spinboxes (use right-region selector)
        self.estimate_counts = {}
        # do not auto-update counts; user must press Estimate
        left_layout.addLayout(buttons_layout)
        left_layout.addWidget(card("Calculation Result", result_layout))

        # Right layout
        right_layout = QVBoxLayout()
        right_layout.setSpacing(8)
        right_layout.setContentsMargins(15, 15, 15, 15)
        
        # Comments section 
        comments_card = card("Comments (Optional)", self.comments_input)
        comments_card.setMaximumHeight(100)
        right_layout.addWidget(comments_card)
        
        # OT Summary card with progress bar
        summary_widget = QWidget()
        summary_layout = QVBoxLayout()
        summary_layout.addWidget(self.daily_ot_label)
        summary_layout.addWidget(self.ot_units_label)
        # OT Progress bar
        self.ot_progress_bar = QProgressBar()
        self.ot_progress_bar.setMinimum(0)
        self.ot_progress_bar.setMaximum(100)
        self.ot_progress_bar.setValue(0)
        self.ot_progress_bar.setTextVisible(True)
        self.ot_progress_bar.setFormat("%v%")
        self.ot_progress_bar.setMinimumHeight(24)
        self.ot_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #3c3c3c;
                border-radius: 8px;
                text-align: center;
                height: 24px;
                background-color: #2b2b2b;
            }
            QProgressBar::chunk {
                background-color: #FF9800;
                border-radius: 6px;
            }
        """)
        summary_layout.addWidget(self.ot_progress_bar)

        summary_widget.setLayout(summary_layout)
        self.ot_summary_group = card("OT Daily Summary", summary_widget)
        self.ot_summary_group.setMaximumHeight(130)
        right_layout.addWidget(self.ot_summary_group)
        
        # Filter/Finder section
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(12)
        
        # Text search for Case ID or Doctor
        self.filter_field = QComboBox()
        self.filter_field.addItems(["Case ID", "Doctor"])
        self.filter_field.setMaximumWidth(100)
        
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Search...")
        self.filter_input.setMaximumWidth(150)
        self.filter_input.textChanged.connect(self.filter_ot_cases)
        
        # Region dropdown filter
        self.region_filter = QComboBox()
        self.region_filter.addItem("All Regions")
        self.region_filter.addItems(self.standards.keys())
        self.region_filter.setMaximumWidth(130)
        self.region_filter.currentTextChanged.connect(self.filter_ot_cases)
        
        # Type dropdown filter
        self.type_filter = QComboBox()
        self.type_filter.addItem("All Types")
        self.type_filter.setMaximumWidth(130)
        self.type_filter.currentTextChanged.connect(self.filter_ot_cases)
        
        # Populate types from all regions
        all_types = set()
        for region_data in self.standards.values():
            if "Aligners" in region_data:
                all_types.update(region_data["Aligners"].keys())
        self.type_filter.addItems(sorted(all_types))
        
        self.clear_filter_btn = QPushButton("Clear")
        self.clear_filter_btn.setMaximumWidth(110)
        self.clear_filter_btn.clicked.connect(self.clear_filter)
        
        filter_layout.addWidget(self.filter_field)
        filter_layout.addWidget(self.filter_input)
        filter_layout.addWidget(self.region_filter)
        filter_layout.addWidget(self.type_filter)
        filter_layout.addWidget(self.clear_filter_btn)
        filter_layout.addStretch()
        
        right_layout.addLayout(filter_layout)
        
        # OT Cases Table
        self.ot_table = QTableWidget()
        self.ot_table.setAlternatingRowColors(False)
        self.ot_table.verticalHeader().setVisible(False)
        self.ot_table.setColumnCount(8)
        self.ot_table.setHorizontalHeaderLabels([
            "Case ID", "Doctor", "Region", "Type", "Time", "Eff %", "Value %", "Und Eq"
        ])
        self.ot_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.ot_table.setShowGrid(True)
        self.ot_table.setGridStyle(Qt.PenStyle.SolidLine)
        
        # Style for grid lines
        self.ot_table.setStyleSheet("""
            QTableWidget {
                gridline-color: #5a5a5a;
            }
            QHeaderView::section {
                background-color: #3c3c3c;
                border: 1px solid #5a5a5a;
                padding: 4px;
            }
        """)
        
        # Set column widths
        self.ot_table.setColumnWidth(0, 85)   # Case ID
        self.ot_table.setColumnWidth(1, 90)   # Doctor
        self.ot_table.setColumnWidth(2, 85)   # Region
        self.ot_table.setColumnWidth(3, 65)   # Type
        self.ot_table.setColumnWidth(4, 45)   # Time
        self.ot_table.setColumnWidth(5, 48)   # Eff
        self.ot_table.setColumnWidth(6, 55)   # Value
        self.ot_table.setColumnWidth(7, 50)   # Units Eq
        
        header = self.ot_table.horizontalHeader()
        header.setStretchLastSection(False)
        
        # Fixed table size
        table_width = 85 + 90 + 85 + 65 + 45 + 50 + 55 + 50 + 10
        self.ot_table.setFixedWidth(table_width)
        self.ot_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.ot_table.setMaximumHeight(260)
        
        table_card = card("Today's OT Cases", self.ot_table)
        right_layout.addWidget(table_card)
        
        # Edit/Delete buttons
        action_buttons_layout = QHBoxLayout()
        action_buttons_layout.addStretch()
        
        self.edit_ot_btn = QPushButton("Edit")
        self.edit_ot_btn.setMaximumWidth(100)
        self.edit_ot_btn.setMinimumHeight(26)
        self.edit_ot_btn.clicked.connect(self.edit_selected_ot_case)
        
        self.delete_ot_btn = QPushButton("Delete")
        self.delete_ot_btn.setMaximumWidth(100)
        self.delete_ot_btn.setMinimumHeight(26)
        self.delete_ot_btn.setStyleSheet("""
            QPushButton {
                background-color: #F44336;
            }
            QPushButton:hover {
                background-color: #D32F2F;
            }
        """)
        self.delete_ot_btn.clicked.connect(self.delete_selected_ot_case)
        
        action_buttons_layout.addWidget(self.edit_ot_btn)
        action_buttons_layout.addWidget(self.delete_ot_btn)
        action_buttons_layout.addStretch()
        right_layout.addLayout(action_buttons_layout)
        
        # Create widgets for responsive layout
        left_widget = QWidget()
        left_widget.setLayout(left_layout)
        
        right_widget = QWidget()
        right_widget.setLayout(right_layout)
        
        # Container for vertical layout (always responsive)
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
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
        # No extra bottom margin — let footer sit below the scroll area
        
        # Main layout with sticky OT summary at bottom
        self.final_layout = QVBoxLayout()
        self.final_layout.setContentsMargins(5, 5, 5, 5)
        self.final_layout.setSpacing(5)
        self.final_layout.addWidget(scroll, 1)
        
        # Move OT summary to sticky bottom
        self.right_layout.removeWidget(self.ot_summary_group)
        self.final_layout.addWidget(self.ot_summary_group, 0)
        
        self.setLayout(self.final_layout)
        
        self.load_daily_ot_production()
        self.load_ot_cases()
    
    def resizeEvent(self, event):
        """Handle resize to adjust widget widths"""
        super().resizeEvent(event)
        width = event.size().width()
        
        # Always vertical layout - just adjust widths
        responsive_width = min(width - 40, 600)
        self.left_widget.setFixedWidth(responsive_width)
        self.right_widget.setFixedWidth(responsive_width)

    def on_case_id_changed(self, text):
        """Auto-set start time when Case ID is first entered"""
        if text and len(text) == 1:  # First character entered
            self.start_time.setTime(QTime.currentTime())

    def update_case_types(self):
        region = self.region.currentText()
        if region and region in self.standards:
            self.tipo.clear()
            self.tipo.addItems(self.standards[region]["Aligners"].keys())
        # (do not update right-hand estimate region here)

    def validate_end_time(self):
        if self.end_time.time() < self.start_time.time():
            self.end_time.blockSignals(True)
            self.end_time.setTime(self.start_time.time())
            self.end_time.blockSignals(False)

    def calculate_case_value(self, std_time):
        """Calculate case value percentage"""
        DAILY_BASE_MINUTES = 408.3
        case_value = (std_time / DAILY_BASE_MINUTES) * 100
        return case_value

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
        
        if efficiency >= 100:
            status = "OK"
            color = "#4CAF50"
        elif efficiency >= 95:
            status = "⚠ WARN"
            color = "#FFC107"
        else:
            status = "LOW"
            color = "#F44336"

        result_text = f"{efficiency:.1f}% – {status}\nOT Case Value: {case_value:.3f}%"
        self.result_label.setText(result_text)
        self.result_label.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold; text-align: center;")

    def on_date_changed(self):
        """Called when date picker changes - reload OT data for that date"""
        self.load_daily_ot_production()
        self.load_ot_cases()

    def load_daily_ot_production(self):
        conn = get_connection()
        cursor = conn.cursor()
        # Use selected date from picker
        selected_date = self.case_date.date().toString("yyyy-MM-dd")
        
        # Get total OT case values (only count_production = 1)
        cursor.execute("""
            SELECT SUM(case_value)
            FROM ot_cases
            WHERE fecha = ? AND (count_production = 1 OR count_production IS NULL)
        """, (selected_date,))
        
        result = cursor.fetchone()
        total_ot = result[0] if result[0] else 0.0
        
        # Get cases by region for equivalent units calculation (only count_production = 1)
        cursor.execute("""
            SELECT region, SUM(case_value)
            FROM ot_cases
            WHERE fecha = ? AND (count_production = 1 OR count_production IS NULL)
            GROUP BY region
        """, (selected_date,))
        
        region_cases = cursor.fetchall()
        conn.close()
        
        # Calculate equivalent units based on region
        total_equivalent_units = 0.0
        for region, case_value in region_cases:
            if region in self.units_eq and case_value:
                units_at_100 = self.units_eq[region].get("100", 0)
                total_equivalent_units += (case_value / 100) * units_at_100
        
        self.daily_ot_label.setText(f"OT Production: {total_ot:.2f}%")
        self.ot_units_label.setText(f"OT Equivalent Units: {total_equivalent_units:.2f}")
        
        # Update OT progress bar with animation
        self.ot_progress_bar.setMaximum(max(100, int(total_ot) + 10))
        self.animate_ot_progress_bar(int(total_ot))
        
        # Change color based on OT production
        if total_ot < 10:
            bar_color = "#9E9E9E"  # Gray for low OT
        elif total_ot < 25:
            bar_color = "#FF9800"  # Orange
        else:
            bar_color = "#4CAF50"  # Green for good OT
        # Store chunk color and let the theme helper set the background
        self._ot_progress_chunk = bar_color
        current_is_light = 'background-color: #F7ECE1' in QApplication.instance().styleSheet()
        # Update bar appearance according to current theme
        self.update_progress_bar_style(current_is_light)
        
        return total_ot

    def calculate_for_hours(self):
        """Estimate production percent, TU and equivalent units for selected OT hours"""
        # Rebuild spinboxes for the selected right-side region and hours
        self.update_estimate_types()
        # show the counts area only when estimate requested
        self.estimate_counts_widget.show()

        # Now compute totals using counts in the spinboxes and include UE
        hours = float(self.ot_hours_spin.value())
        minutes = hours * 60.0
        region = self.est_region_combo.currentText() if hasattr(self, 'est_region_combo') else self.region.currentText()

        total_cases = 0
        total_case_value = 0.0
        total_equivalent_units = 0.0
        used_minutes = 0.0

        for t, sb in self.estimate_counts.items():
            cnt = int(sb.value())
            total_cases += cnt
            # use resolved standards key stored during update_estimate_types
            key = getattr(self, 'estimate_key_map', {}).get(t)
            std_time = self.standards.get(region, {}).get("Aligners", {}).get(key, 0) if key else 0
            case_value_per = self.calculate_case_value(std_time) if std_time else 0.0
            units_per_case = self.calculate_units_eq(region, case_value_per)
            total_case_value += cnt * case_value_per
            total_equivalent_units += cnt * units_per_case
            used_minutes += cnt * float(std_time or 0)

        tu_percent = (used_minutes / minutes) * 100.0 if minutes > 0 else 0.0

        # Update per-type info labels with "% · TU · UE"
        minutes = minutes if minutes > 0 else 1.0
        for t, sb in self.estimate_counts.items():
            cnt = int(sb.value())
            key = getattr(self, 'estimate_key_map', {}).get(t)
            std_time = self.standards.get(region, {}).get("Aligners", {}).get(key, 0) if key else 0
            case_value_per = self.calculate_case_value(std_time) if std_time else 0.0
            units_per_case = self.calculate_units_eq(region, case_value_per)
            cases_value_total = cnt * case_value_per
            used_min_type = cnt * float(std_time or 0)
            tu_type = (used_min_type / minutes) * 100.0
            equiv_units_type = cnt * units_per_case
            info_label = self.estimate_info_labels.get(t)
            if info_label:
                info_label.setText(f"{cases_value_total:.2f}% · TU {tu_type:.1f}% · {equiv_units_type:.2f} UE")

        # clear overall label (we use per-type labels now)
        self.estimate_label.clear()
        return

    def update_estimate_types(self):
        """Rebuild the per-type spinboxes based on selected region."""
        # clear existing
        try:
            while self.estimate_counts_layout.count():
                item = self.estimate_counts_layout.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()
        except Exception:
            pass

        self.estimate_counts = {}
        # mapping from canonical label (CR/Refinement/Primary) to actual standards key used
        self.estimate_key_map = {}
        # use the right-side region selector if present
        region = self.est_region_combo.currentText() if hasattr(self, 'est_region_combo') else self.region.currentText()
        if not region or region not in self.standards:
            return

        # compute maximum cases possible given selected hours
        minutes = float(self.ot_hours_spin.value()) * 60.0 if hasattr(self, 'ot_hours_spin') else 0.0
        # Ensure the three canonical types are present: CR, Refinement, Primary
        desired = ['CR', 'Refinement', 'Primary']
        all_types = list(self.standards[region].get("Aligners", {}).keys())

        for t in desired:
            # try exact match first
            found_key = None
            for k in all_types:
                if k.strip().lower() == t.lower():
                    found_key = k
                    break
            # flexible fallback: for 'Refinement' match any key containing 'ref', for 'CR' match 'cr', for 'Primary' match 'primary'
            if not found_key:
                needle = t.lower()
                if t.lower() == 'refinement':
                    needle = 'ref'
                if t.lower() == 'cr':
                    needle = 'cr'
                for k in all_types:
                    if needle in k.strip().lower():
                        found_key = k
                        break

            # If still not found for Refinement, fall back to a 'Secondary' variant if available
            if not found_key and t.lower() == 'refinement':
                fallback_candidates = ['Secondary', 'Stage RX Secondary', 'Bite Sync Secondary']
                for cand in fallback_candidates:
                    for k in all_types:
                        if k.strip().lower() == cand.lower():
                            found_key = k
                            break
                    if found_key:
                        break

            std_time = self.standards[region]["Aligners"].get(found_key, 0) if found_key else 0
            # store mapping for later calculations
            self.estimate_key_map[t] = found_key
            max_cases = int((minutes // float(std_time)) if std_time and minutes > 0 else 0)
            sb = QSpinBox()
            # remove up/down buttons for a compact numeric field and make it non-editable
            sb.setButtonSymbols(QAbstractSpinBox.NoButtons)
            sb.setReadOnly(True)
            sb.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            sb.setRange(0, max(1, max_cases))
            # default to max possible so user sees capacity
            sb.setValue(max_cases)
            sb.setMaximumWidth(90)

            # per-type info label placed below spinbox
            info_label = QLabel("")
            info_label.setStyleSheet("font-size:11px; color:#222222;")
            info_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            # container widget to hold spinbox and info label (vertical)
            container = QWidget()
            v = QVBoxLayout()
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(4)
            v.addWidget(sb)
            v.addWidget(info_label)
            container.setLayout(v)

            self.estimate_counts_layout.addRow(f"{t}", container)
            self.estimate_counts[t] = sb
            self.estimate_info_labels[t] = info_label

        # After building spinboxes, compute quick summary (without UE)
        total_case_value = 0.0
        used_minutes = 0.0
        for t, sb in self.estimate_counts.items():
            cnt = int(sb.value())
            key = self.estimate_key_map.get(t)
            std_time = self.standards[region]["Aligners"].get(key, 0) if key else 0
            case_value_per = self.calculate_case_value(std_time) if std_time else 0.0
            total_case_value += cnt * case_value_per
            used_minutes += cnt * float(std_time or 0)

        tu_percent = (used_minutes / minutes) * 100.0 if minutes > 0 else 0.0
        # update label without UE (UE shown only on explicit Estimate) — hide case count
        self.estimate_label.setText(f"{total_case_value:.2f}% · TU {tu_percent:.1f}%")

    def animate_ot_progress_bar(self, target_value):
        """Animate the OT progress bar to the target value"""
        current_value = self.ot_progress_bar.value()
        
        if not hasattr(self, '_ot_progress_animation'):
            self._ot_progress_animation = QPropertyAnimation(self.ot_progress_bar, b"value")
            self._ot_progress_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        
        self._ot_progress_animation.stop()
        self._ot_progress_animation.setDuration(600)  # 600ms smoother animation
        self._ot_progress_animation.setStartValue(current_value)
        self._ot_progress_animation.setEndValue(target_value)
        self._ot_progress_animation.start()

    def update_progress_bar_style(self, light_mode: bool):
        """Update OT progress bar appearance for light/dark themes."""
        chunk = getattr(self, '_ot_progress_chunk', '#FF9800')
        if light_mode:
            bg = '#8D86C9'
        else:
            bg = '#2b2b2b'

        try:
            self.ot_progress_bar.setStyleSheet(f"""
                QProgressBar {{
                    border: 1px solid #3c3c3c;
                    border-radius: 8px;
                    text-align: center;
                    height: 24px;
                    background-color: {bg};
                }}
                QProgressBar::chunk {{
                    background-color: {chunk};
                    border-radius: 6px;
                }}
            """)
        except Exception:
            pass

    def update_theme_labels(self, light_mode: bool):
        """Adjust label colors so Light mode shows dark text and Dark mode preserves original light colors."""
        try:
            if light_mode:
                tl_color = '#000000'
                est_color = '#222222'
                info_color = '#222222'
            else:
                tl_color = '#aaaaaa'
                est_color = '#e6e6e6'
                info_color = '#bdbdbd'

            # Count toggle label
            for w in [getattr(self, 'count_toggle', None)]:
                pass
            toggle_label = None
            # find the toggle label by walking children
            for child in self.findChildren(QLabel):
                if child.text() == 'Count to production?':
                    toggle_label = child
                    break
            if toggle_label:
                toggle_label.setStyleSheet(f"font-size:11px; color: {tl_color};")

            # estimate overall label
            if hasattr(self, 'estimate_label') and self.estimate_label:
                self.estimate_label.setStyleSheet(f"font-size:12px; color:{est_color};")

            # per-type info labels
            for lbl in getattr(self, 'estimate_info_labels', {}).values():
                try:
                    lbl.setStyleSheet(f"font-size:11px; color:{info_color};")
                except Exception:
                    pass
        except Exception:
            pass

    def load_ot_cases(self):
        """Load OT cases for selected date into the table"""
        conn = get_connection()
        cursor = conn.cursor()
        selected_date = self.case_date.date().toString("yyyy-MM-dd")
        
        cursor.execute("""
            SELECT id, case_id, doctor, region, tipo_caso, tiempo_real, efficiency, case_value, estado, count_production
            FROM ot_cases
            WHERE fecha = ?
            ORDER BY id DESC
        """, (selected_date,))
        
        cases = cursor.fetchall()
        conn.close()
        
        self.ot_table.setRowCount(len(cases))
        self.ot_case_ids = []  # Store database IDs for edit/delete
        
        for row_idx, case in enumerate(cases):
            db_id, case_id, doctor, region, tipo, tiempo_real, efficiency, case_value, estado, count_production = case
            self.ot_case_ids.append(db_id)
            
            # Check if case counts for production
            counts_for_production = count_production if count_production is not None else 1
            
            # Yellow background for cases that don't count, otherwise zebra striping
            if counts_for_production == 0:
                bg_color = QColor(180, 150, 50)  # Yellow/gold for non-counting cases
            else:
                bg_color = QColor(43, 43, 43) if (row_idx % 2 == 0) else QColor(45, 45, 45)
            
            bg_brush = QBrush(bg_color)
            
            # Case ID - bold
            case_item = QTableWidgetItem(str(case_id))
            case_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            case_item.setBackground(bg_brush)
            font = QFont()
            font.setBold(True)
            case_item.setFont(font)
            self.ot_table.setItem(row_idx, 0, case_item)
            
            # Doctor - bold
            doctor_item = QTableWidgetItem(str(doctor) if doctor else "")
            doctor_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            doctor_item.setBackground(bg_brush)
            doctor_item.setFont(font)
            self.ot_table.setItem(row_idx, 1, doctor_item)
            
            # Region
            region_item = QTableWidgetItem(str(region))
            region_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            region_item.setBackground(bg_brush)
            self.ot_table.setItem(row_idx, 2, region_item)
            
            # Type
            tipo_item = QTableWidgetItem(str(tipo))
            tipo_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tipo_item.setBackground(bg_brush)
            self.ot_table.setItem(row_idx, 3, tipo_item)
            
            # Time
            time_item = QTableWidgetItem(f"{tiempo_real:.0f}")
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            time_item.setBackground(bg_brush)
            self.ot_table.setItem(row_idx, 4, time_item)
            
            # Efficiency with color background (like Production tab)
            eff_item = QTableWidgetItem(f"{efficiency:.0f}")
            eff_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if estado == "OK":
                eff_item.setBackground(QBrush(QColor(76, 175, 80)))  # Green background
                eff_item.setForeground(QBrush(QColor(255, 255, 255)))  # White text
            else:
                eff_item.setBackground(QBrush(QColor(244, 67, 54)))  # Red background
                eff_item.setForeground(QBrush(QColor(255, 255, 255)))  # White text
            self.ot_table.setItem(row_idx, 5, eff_item)
            
            # Value - no color, same background as other columns
            value_item = QTableWidgetItem(f"{case_value:.2f}")
            value_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            value_item.setBackground(bg_brush)
            self.ot_table.setItem(row_idx, 6, value_item)
            
            # Units Equivalent - calculated from region and case_value
            units_eq = self.calculate_units_eq(region, case_value)
            units_eq_item = QTableWidgetItem(f"{units_eq:.2f}")
            units_eq_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            units_eq_item.setBackground(bg_brush)
            self.ot_table.setItem(row_idx, 7, units_eq_item)

    def save_ot_case(self):
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
        
        # Get toggle and comments values
        count_production = 1 if self.count_toggle.isChecked() else 0
        comments = self.comments_input.toPlainText().strip()

        conn = get_connection()
        cursor = conn.cursor()

        # Check if we're editing an existing case
        if hasattr(self, 'editing_ot_id') and self.editing_ot_id:
            cursor.execute("""
                UPDATE ot_cases SET
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
                self.editing_ot_id
            ))
            self.editing_ot_id = None
            msg = "OT Case Updated"
        else:
            cursor.execute("""
                INSERT INTO ot_cases (
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
            msg = "OT Case Saved"

        conn.commit()
        conn.close()

        self.result_label.setText(msg)
        self.result_label.setStyleSheet("color: #FF9800; font-size: 13px; font-weight: bold; text-align: center;")
        self.load_daily_ot_production()
        self.load_ot_cases()
        self.case_id.clear()
        self.doctor.clear()
        self.comments_input.clear()
        self.count_toggle.setChecked(True)  # Reset toggle to ON
        
        # Clear end time - set to midnight (00:00)
        self.end_time.blockSignals(True)
        self.end_time.setTime(QTime(0, 0))
        self.end_time.blockSignals(False)
        
        self.ot_saved.emit()

    def edit_selected_ot_case(self):
        """Load selected OT case into form for editing"""
        selected_row = self.ot_table.currentRow()
        if selected_row < 0 or selected_row >= len(self.ot_case_ids):
            self.result_label.setText("Select a case to edit")
            return
        
        db_id = self.ot_case_ids[selected_row]
        
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT case_id, region, tipo_caso, doctor, hora_inicio, hora_fin, count_production, comments
            FROM ot_cases WHERE id = ?
        """, (db_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            self.editing_ot_id = db_id
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
            self.start_time.setTime(QTime.fromString(row[4], "HH:mm"))
            self.end_time.setTime(QTime.fromString(row[5], "HH:mm"))
            
            # Set toggle and comments
            count_prod = row[6] if row[6] is not None else 1
            self.count_toggle.setChecked(bool(count_prod))
            self.comments_input.setText(row[7] if row[7] else "")
            
            self.result_label.setText("Editing - Click Save to update")
            self.result_label.setStyleSheet("color: #FFC107; font-size: 13px; font-weight: bold; text-align: center;")

    def delete_selected_ot_case(self):
        """Delete selected OT case"""
        selected_row = self.ot_table.currentRow()
        if selected_row < 0 or selected_row >= len(self.ot_case_ids):
            self.result_label.setText("Select a case to delete")
            return
        
        db_id = self.ot_case_ids[selected_row]
        case_id_text = self.ot_table.item(selected_row, 0).text()
        
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete OT case '{case_id_text}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM ot_cases WHERE id = ?", (db_id,))
            conn.commit()
            conn.close()
            
            self.result_label.setText("OT Case Deleted")
            self.result_label.setStyleSheet("color: #F44336; font-size: 13px; font-weight: bold; text-align: center;")
            self.load_daily_ot_production()
            self.load_ot_cases()
            self.ot_saved.emit()

    def filter_ot_cases(self):
        """Filter OT cases table based on all filter inputs"""
        search_text = self.filter_input.text().strip().lower()
        filter_field = self.filter_field.currentText()
        region_filter = self.region_filter.currentText()
        type_filter = self.type_filter.currentText()
        
        # Column mapping for text search
        column_map = {
            "Case ID": 0,
            "Doctor": 1
        }
        
        text_column_idx = column_map.get(filter_field, 0)
        
        for row in range(self.ot_table.rowCount()):
            show_row = True
            
            # Text search filter
            if search_text:
                item = self.ot_table.item(row, text_column_idx)
                if item:
                    cell_text = item.text().lower()
                    if search_text not in cell_text:
                        show_row = False
                else:
                    show_row = False
            
            # Region filter
            if show_row and region_filter != "All Regions":
                region_item = self.ot_table.item(row, 2)  # Region is column 2
                if region_item:
                    if region_item.text() != region_filter:
                        show_row = False
                else:
                    show_row = False
            
            # Type filter
            if show_row and type_filter != "All Types":
                type_item = self.ot_table.item(row, 3)  # Type is column 3
                if type_item:
                    if type_item.text() != type_filter:
                        show_row = False
                else:
                    show_row = False
            
            self.ot_table.setRowHidden(row, not show_row)

    def clear_filter(self):
        """Clear all filters and show all rows"""
        self.filter_input.clear()
        self.region_filter.setCurrentIndex(0)  # "All Regions"
        self.type_filter.setCurrentIndex(0)  # "All Types"
        for row in range(self.ot_table.rowCount()):
            self.ot_table.setRowHidden(row, False)
