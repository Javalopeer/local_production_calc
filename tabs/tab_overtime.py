import json
import os
import sys
from PySide6.QtWidgets import (
    QApplication, QWidget, QFormLayout, QComboBox, QLineEdit,
    QPushButton, QLabel, QTimeEdit, QVBoxLayout, QHBoxLayout, QGroupBox, QDateEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QTextEdit, QProgressBar, QScrollArea, QDoubleSpinBox, QFrame
)
from PySide6.QtCore import QTime, QDate, Qt, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont, QColor, QBrush
from db.database import get_connection
from datetime import datetime
from .toggle_switch import ToggleSwitch
from .utils import get_resource_path, calculate_case_value as _calc_cv, load_units_eq_data, get_units_per_case as _ue_lookup


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
        self.units_eq = load_units_eq_data()

    def calculate_units_eq(self, region, case_type):
        """Return UE per case for a given region and case type."""
        return _ue_lookup(self.units_eq, region, case_type)

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
        # Do not set a fixed color here; theme updater will apply appropriate color.
        toggle_label.setStyleSheet("font-size: 11px;")
        # keep a reference so update_theme_labels can update it later
        self.count_toggle_label = toggle_label
        toggle_layout.addWidget(toggle_label)
        toggle_layout.addWidget(self.count_toggle)
        toggle_layout.addStretch()
        toggle_widget = QWidget()
        toggle_widget.setLayout(toggle_layout)
        form.addRow("", toggle_widget)

        # Import from clipboard button
        import_btn = QPushButton("Import")
        import_btn.setMaximumWidth(90)
        import_btn.setMinimumHeight(26)
        import_btn.setToolTip(
            "Copy all text on the case page (Ctrl+A, Ctrl+C),\n"
            "then click here or press Ctrl+Shift+I to auto-fill the fields."
        )
        import_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a5c2a;
                color: #7ec890;
            }
            QPushButton:hover {
                background-color: #236b32;
                color: #a8e6b8;
            }
        """)
        import_btn.clicked.connect(self._on_import_case)

        # Buttons layout (centered)
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        buttons_layout.addWidget(import_btn)
        buttons_layout.addWidget(calc_btn)
        buttons_layout.addSpacing(8)
        buttons_layout.addWidget(save_btn)
        buttons_layout.addStretch()
        # Container so we can center the buttons within the left column
        buttons_container = QWidget()
        buttons_container.setLayout(buttons_layout)

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

        # counts per type area (VBox so we can add explicit styled rows)
        self.estimate_counts_layout = QVBoxLayout()
        self.estimate_counts_layout.setSpacing(6)
        self.estimate_counts_layout.setContentsMargins(0, 0, 0, 0)
        self.estimate_counts_widget = QWidget()
        self.estimate_counts_widget.setLayout(self.estimate_counts_layout)
        # hide until user presses Estimate
        self.estimate_counts_widget.hide()

        # per-type labels (populated in update_estimate_types)
        self.estimate_info_labels = {}
        self.estimate_type_labels = {}  # type-name + capacity labels

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
        left_layout.addWidget(buttons_container, alignment=Qt.AlignmentFlag.AlignHCenter)
        left_layout.addWidget(card("Calculation Result", result_layout))

        # Right layout
        right_layout = QVBoxLayout()
        right_layout.setSpacing(8)
        # Reduce right panel margins so content is closer to the card borders
        right_layout.setContentsMargins(8, 8, 8, 8)
        
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
                color: #ffffff;
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

        # Wrap filters in a container so we can center them horizontally
        filter_container = QWidget()
        filter_container.setLayout(filter_layout)
        right_layout.addWidget(filter_container, alignment=Qt.AlignmentFlag.AlignHCenter)
        
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
        # Reduce table max height to avoid large empty area inside the card
        self.ot_table.setMaximumHeight(200)
        
        table_card = card("Today's OT Cases", self.ot_table)
        # Remove extra top/inner margins so the header sits flush with the card title
        try:
            if table_card.layout():
                table_card.layout().setContentsMargins(0, 0, 0, 0)
                table_card.layout().setSpacing(0)
        except Exception:
            pass
        # Center the OT cases table card horizontally within the right panel
        right_layout.addWidget(table_card, alignment=Qt.AlignmentFlag.AlignHCenter)
        
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
        # Create main final layout and add left/right content inside a scroll area
        self.final_layout = QVBoxLayout()
        self.final_layout.setContentsMargins(5, 5, 5, 5)
        self.final_layout.setSpacing(5)

        # Build left/right widgets from existing layouts
        try:
            left_widget = QWidget()
            left_widget.setLayout(left_layout)
            right_widget = QWidget()
            right_widget.setLayout(right_layout)
            # expose as attributes so resizeEvent can access them
            self.left_widget = left_widget
            self.right_widget = right_widget

            from PySide6.QtWidgets import QBoxLayout

            self.content_widget = QWidget()
            # Default to stacked (TopToBottom) so initial position is left above right.
            self.content_layout = QBoxLayout(QBoxLayout.TopToBottom)
            self.content_widget.setLayout(self.content_layout)
            self.content_layout.setSpacing(15)
            self.content_layout.setContentsMargins(5, 5, 5, 5)
            # Align left/top so stacked widgets align like a staircase and don't center.
            self.content_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            # Add widgets; we'll switch direction in resizeEvent when window is wide.
            self.content_layout.addWidget(left_widget, 1)
            self.content_layout.addWidget(right_widget, 0)

            scroll = QScrollArea()
            scroll.setWidget(self.content_widget)
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

            self.final_layout.addWidget(scroll, 1)
        except Exception:
            # Fallback: still add the summary group if building content fails
            pass

        self.final_layout.addWidget(self.ot_summary_group, 0)
        self.setLayout(self.final_layout)
        
        self.load_daily_ot_production()
        self.load_ot_cases()
    
    def resizeEvent(self, event):
        """Switch between stacked and side-by-side depending on width.

        Default behavior: stacked (TopToBottom). If the window becomes wider
        than `stack_threshold`, switch to LeftToRight to show panels side-by-side.
        """
        super().resizeEvent(event)
        try:
            from PySide6.QtWidgets import QBoxLayout

            width = event.size().width()
            stack_threshold = 1000
            if width > stack_threshold:
                # side-by-side
                self.content_layout.setDirection(QBoxLayout.LeftToRight)
                # give right panel a comfortable max width
                try:
                    self.right_widget.setMaximumWidth(420)
                except Exception:
                    pass
            else:
                # stacked vertically
                self.content_layout.setDirection(QBoxLayout.TopToBottom)
                try:
                    self.right_widget.setMaximumWidth(16777215)
                except Exception:
                    pass
        except Exception:
            pass

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
        """Calculate case value percentage."""
        return _calc_cv(std_time)

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
        
        # Get cases by region+type for equivalent units calculation (only count_production = 1)
        cursor.execute("""
            SELECT region, tipo_caso, COUNT(*), SUM(case_value)
            FROM ot_cases
            WHERE fecha = ? AND (count_production = 1 OR count_production IS NULL)
            GROUP BY region, tipo_caso
        """, (selected_date,))

        region_cases = cursor.fetchall()
        conn.close()

        # Calculate equivalent units: sum(case_value%) × base_rate / 100
        # (same formula as each row in the table: case_value * base_rate / 100)
        total_equivalent_units = 0.0
        for region, case_type, count, sum_case_value in region_cases:
            if count and sum_case_value:
                base_rate = self.calculate_units_eq(region, case_type)
                total_equivalent_units += sum_case_value * base_rate / 100.0
        
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

        for t, cnt in self.estimate_counts.items():
            total_cases += cnt
            # use resolved standards key stored during update_estimate_types
            key = getattr(self, 'estimate_key_map', {}).get(t)
            std_time = self.standards.get(region, {}).get("Aligners", {}).get(key, 0) if key else 0
            case_value_per = self.calculate_case_value(std_time) if std_time else 0.0
            daily_rate = self.calculate_units_eq(region, key)
            total_case_value += cnt * case_value_per
            # UE = case_value% × daily_rate / 100  (same formula as Register tab)
            total_equivalent_units += cnt * case_value_per * daily_rate / 100.0
            used_minutes += cnt * float(std_time or 0)

        tu_percent = (used_minutes / minutes) * 100.0 if minutes > 0 else 0.0

        # Query today's OT done counts by case type for the selected region
        selected_date = self.case_date.date().toString("yyyy-MM-dd")
        done_by_key: dict = {}
        try:
            _conn = get_connection()
            _cur = _conn.cursor()
            _cur.execute(
                "SELECT tipo_caso, COUNT(*) FROM ot_cases WHERE fecha = ? AND region = ? GROUP BY tipo_caso",
                (selected_date, region),
            )
            for _tipo, _cnt in _cur.fetchall():
                done_by_key[_tipo] = int(_cnt)
            _conn.close()
        except Exception:
            pass

        # Update per-type info labels with std time, done/remaining and UE
        minutes = minutes if minutes > 0 else 1.0
        for t, cnt in self.estimate_counts.items():
            key = getattr(self, 'estimate_key_map', {}).get(t)
            std_time = self.standards.get(region, {}).get("Aligners", {}).get(key, 0) if key else 0
            case_value_per = self.calculate_case_value(std_time) if std_time else 0.0
            daily_rate = self.calculate_units_eq(region, key)
            # UE per type = cnt × case_value% × daily_rate / 100
            equiv_units_type = cnt * case_value_per * daily_rate / 100.0
            done_count = done_by_key.get(key, 0) if key else 0
            remaining = max(0, cnt - done_count)
            info_label = self.estimate_info_labels.get(t)
            if info_label:
                std_str = f"{std_time:.0f} min" if std_time else "—"
                info_label.setText(
                    f"\u23f1 {std_str}  |  \u2713{done_count} hechos · {remaining} faltan  |  {equiv_units_type:.2f} UE"
                )

        # clear overall label (we use per-type labels now)
        self.estimate_label.clear()

        # Apply correct theme colors to newly created/updated info labels
        try:
            from PySide6.QtGui import QPalette
            _pal = QApplication.instance().palette()
            _is_light = _pal.color(QPalette.ColorRole.Window).lightness() > 128
            self.update_theme_labels(_is_light)
        except Exception:
            pass

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

            # store max capacity as plain int (no spinbox needed — it was read-only)
            self.estimate_counts[t] = max_cases

            # Build an explicit card row so labels are always themed correctly
            display_name = found_key or t
            row_frame = QFrame()
            row_frame.setFrameShape(QFrame.Shape.StyledPanel)
            row_layout = QVBoxLayout(row_frame)
            row_layout.setContentsMargins(6, 4, 6, 4)
            row_layout.setSpacing(2)

            type_lbl = QLabel(f"<b>{display_name}</b> &nbsp;·&nbsp; {max_cases} posibles")
            type_lbl.setStyleSheet("font-size:11px; color:#e6e6e6;")

            info_label = QLabel("")
            info_label.setStyleSheet("font-size:10px; color:#bdbdbd;")
            info_label.setWordWrap(True)

            row_layout.addWidget(type_lbl)
            row_layout.addWidget(info_label)

            self.estimate_counts_layout.addWidget(row_frame)
            self.estimate_type_labels[t] = type_lbl
            self.estimate_info_labels[t] = info_label

        # After building rows, compute quick summary
        total_case_value = 0.0
        used_minutes = 0.0
        for t, cnt in self.estimate_counts.items():
            key = self.estimate_key_map.get(t)
            std_time = self.standards[region]["Aligners"].get(key, 0) if key else 0
            case_value_per = self.calculate_case_value(std_time) if std_time else 0.0
            total_case_value += cnt * case_value_per
            used_minutes += cnt * float(std_time or 0)

        tu_percent = (used_minutes / minutes) * 100.0 if minutes > 0 else 0.0
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
                    color: #ffffff;
                }}
                QProgressBar::chunk {{
                    background-color: {chunk};
                    border-radius: 6px;
                }}
            """)
        except Exception:
            pass

        # Also adjust OT table and action button colors to match Downtime appearance when in Light mode
        try:
            # Save original styles on first run so we can restore on dark mode
            if not hasattr(self, '_ot_table_saved_style'):
                self._ot_table_saved_style = self.ot_table.styleSheet() or ''

            if light_mode:
                # Table header and grid colors in light mode: use grayish, high-contrast hues for readability
                # Do NOT force per-item background here so per-item setBackground() calls
                # (used for efficiency coloring) are respected.
                self.ot_table.setStyleSheet("""
                    QTableWidget {
                        gridline-color: #E0E0E0;
                        background-color: #ffffff;
                        color: #222222;
                    }
                    QHeaderView::section {
                        background-color: #E6E6E6;
                        color: #242038;
                        border: 1px solid #D0CFCF;
                        padding: 6px;
                    }
                """)

                # (Buttons left unchanged here; only table colors are adjusted)
            else:
                # Restore saved styles for dark mode
                try:
                    self.ot_table.setStyleSheet(self._ot_table_saved_style)
                except Exception:
                    pass
                # restore OT table style only (buttons keep their original behavior)
                try:
                    self.ot_table.setStyleSheet(self._ot_table_saved_style)
                except Exception:
                    pass
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
                # Use a bright/light label color for dark mode so it's readable
                tl_color = '#e6e6e6'
                est_color = '#e6e6e6'
                info_color = '#bdbdbd'

            # Count toggle label — prefer explicit reference if available
            toggle_label = getattr(self, 'count_toggle_label', None)
            if toggle_label is None:
                # fallback: find by text
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
                    lbl.setStyleSheet(f"font-size:10px; color:{info_color};")
                except Exception:
                    pass
            # per-type name labels
            type_lbl_color = '#ffffff' if not light_mode else '#222222'
            for lbl in getattr(self, 'estimate_type_labels', {}).values():
                try:
                    lbl.setStyleSheet(f"font-size:11px; color:{type_lbl_color};")
                except Exception:
                    pass
            # Update table cell foregrounds to match theme (light text on dark backgrounds, dark on light)
            try:
                from PySide6.QtGui import QBrush, QColor
                from PySide6.QtWidgets import QTableWidget
                # We'll set each item's foreground color based on its background
                # color to ensure contrast. If the background is light, use dark
                # text; if background is dark, use white text.
                for table in self.findChildren(QTableWidget):
                    for r in range(table.rowCount()):
                        for c in range(table.columnCount()):
                            item = table.item(r, c)
                            if item:
                                bg = item.background().color() if item.background() else None
                                if bg is None:
                                    fg = QColor(34, 32, 56) if light_mode else QColor(255, 255, 255)
                                else:
                                    # lightness threshold - if background is light, use dark text
                                    fg = QColor(34, 32, 56) if bg.lightness() > 128 else QColor(255, 255, 255)
                                item.setForeground(QBrush(fg))
            except Exception:
                pass

            # Ensure progress bar and table header styles are updated too
            try:
                self.update_progress_bar_style(light_mode)
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
            SELECT id, case_id, doctor, region, tipo_caso, tiempo_real, hora_inicio, hora_fin, efficiency, case_value, estado, count_production
            FROM ot_cases
            WHERE fecha = ?
            ORDER BY id DESC
        """, (selected_date,))
        
        cases = cursor.fetchall()
        conn.close()
        
        # Robustly determine if the app is in light mode using palette
        try:
            from PySide6.QtGui import QPalette
            pal = QApplication.instance().palette()
            win_color = pal.color(QPalette.ColorRole.Window)
            current_is_light = win_color.lightness() > 128
        except Exception:
            current_is_light = False

        self.ot_table.setRowCount(len(cases))
        self.ot_case_ids = []  # Store database IDs for edit/delete
        
        for row_idx, case in enumerate(cases):
            (db_id, case_id, doctor, region, tipo,
             tiempo_real, hora_inicio, hora_fin,
             efficiency, case_value, estado, count_production) = case
            self.ot_case_ids.append(db_id)
            
            # Check if case counts for production
            counts_for_production = count_production if count_production is not None else 1
            
            # Yellow background for cases that don't count, otherwise zebra striping.
            # Use the palette-derived theme flag so light mode rows are light.
            if counts_for_production == 0:
                bg_color = QColor(180, 150, 50)  # Yellow/gold for non-counting cases
            else:
                if current_is_light:
                    bg_color = QColor(255, 255, 255) if (row_idx % 2 == 0) else QColor(250, 250, 250)
                else:
                    bg_color = QColor(43, 43, 43) if (row_idx % 2 == 0) else QColor(45, 45, 45)
            
            bg_brush = QBrush(bg_color)
            
            # Determine text color based on theme
            text_color = QColor(34, 32, 56) if current_is_light else QColor(255, 255, 255)

            # Case ID - bold
            case_item = QTableWidgetItem(str(case_id))
            case_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            case_item.setBackground(bg_brush)
            font = QFont()
            font.setBold(True)
            case_item.setFont(font)
            case_item.setForeground(QBrush(text_color))
            self.ot_table.setItem(row_idx, 0, case_item)
            
            # Doctor - bold
            doctor_item = QTableWidgetItem(str(doctor) if doctor else "")
            doctor_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            doctor_item.setBackground(bg_brush)
            doctor_item.setFont(font)
            doctor_item.setForeground(QBrush(text_color))
            self.ot_table.setItem(row_idx, 1, doctor_item)
            
            # Region
            region_item = QTableWidgetItem(str(region))
            region_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            region_item.setBackground(bg_brush)
            region_item.setForeground(QBrush(text_color))
            self.ot_table.setItem(row_idx, 2, region_item)
            
            # Type
            tipo_item = QTableWidgetItem(str(tipo))
            tipo_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tipo_item.setBackground(bg_brush)
            tipo_item.setForeground(QBrush(text_color))
            self.ot_table.setItem(row_idx, 3, tipo_item)
            
            # Time (if stored tiempo_real is 0 or missing, try to compute from hora_inicio/hora_fin)
            try:
                t_val = float(tiempo_real) if tiempo_real is not None else 0.0
            except Exception:
                t_val = 0.0

            if t_val <= 0 and hora_inicio and hora_fin:
                try:
                    # hora_* stored as 'HH:MM'
                    st = QTime.fromString(hora_inicio, "HH:mm")
                    ed = QTime.fromString(hora_fin, "HH:mm")
                    if st.isValid() and ed.isValid():
                        t_val = st.secsTo(ed) / 60.0
                except Exception:
                    t_val = t_val

            time_item = QTableWidgetItem(f"{t_val:.0f}")
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            time_item.setBackground(bg_brush)
            time_item.setForeground(QBrush(text_color))
            self.ot_table.setItem(row_idx, 4, time_item)
            
            # Efficiency with color background (like Production tab)
            eff_item = QTableWidgetItem(f"{efficiency:.0f}")
            eff_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            # Color the Efficiency column based on numeric efficiency rules:
            # >=100 -> green, >=95 -> yellow, else red. Text stays white for contrast.
            try:
                eff_val = float(efficiency)
            except Exception:
                eff_val = None

            if eff_val is not None:
                if eff_val >= 100:
                    eff_item.setBackground(QBrush(QColor(76, 175, 80)))  # Green
                elif eff_val >= 95:
                    eff_item.setBackground(QBrush(QColor(255, 193, 7)))  # Amber/Yellow
                else:
                    eff_item.setBackground(QBrush(QColor(244, 67, 54)))  # Red
                # choose text color for eff cell: dark text on light theme, white on dark
                eff_text_color = QColor(34, 32, 56) if current_is_light else QColor(255, 255, 255)
                eff_item.setForeground(QBrush(eff_text_color))
            else:
                # Fallback: use estado if numeric efficiency missing
                if estado == "OK":
                    eff_item.setBackground(QBrush(QColor(76, 175, 80)))
                else:
                    eff_item.setBackground(QBrush(QColor(244, 67, 54)))
                eff_item.setForeground(QBrush(QColor(255, 255, 255)))
            self.ot_table.setItem(row_idx, 5, eff_item)
            
            # Value - no color, same background as other columns
            value_item = QTableWidgetItem(f"{case_value:.2f}")
            value_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            value_item.setBackground(bg_brush)
            value_item.setForeground(QBrush(text_color))
            self.ot_table.setItem(row_idx, 6, value_item)
            
            # Units Equivalent: case_value% × base_rate / 100
            # (same formula as Register/Production tabs)
            base_rate = self.calculate_units_eq(region, tipo)
            units_eq = case_value * base_rate / 100.0
            units_eq_item = QTableWidgetItem(f"{units_eq:.2f}")
            units_eq_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            units_eq_item.setBackground(bg_brush)
            units_eq_item.setForeground(QBrush(text_color))
            self.ot_table.setItem(row_idx, 7, units_eq_item)

        # After populating rows, ensure other theme-driven labels update
        try:
            self.update_theme_labels(current_is_light)
        except Exception:
            pass

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
        filled: list[str] = []

        if data.get('case_id'):
            self.case_id.setText(data['case_id'])
            filled.append(f"Case ID: {data['case_id']}")

        if data.get('region'):
            idx = self.region.findText(data['region'])
            if idx >= 0:
                self.region.blockSignals(True)
                self.region.setCurrentIndex(idx)
                self.region.blockSignals(False)
                self.update_case_types()
                filled.append(f"Region: {data['region']}")

        if data.get('tipo'):
            idx = self.tipo.findText(data['tipo'])
            if idx >= 0:
                self.tipo.setCurrentIndex(idx)
                filled.append(f"Type: {data['tipo']}")

        if data.get('doctor'):
            self.doctor.setText(data['doctor'])
            filled.append(f"Doctor: {data['doctor']}")

        self.start_time.setTime(QTime.currentTime())

        self.result_label.setText(
            "\n".join(filled) + "\nSet times and click Calculate."
        )
        self.result_label.setStyleSheet(
            "color: #4CAF50; font-size: 12px; font-weight: bold; text-align: center;"
        )

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

        # Refresh estimate panel so done/remaining counts update automatically
        if hasattr(self, 'estimate_counts_widget') and self.estimate_counts_widget.isVisible():
            try:
                self.calculate_for_hours()
            except Exception:
                pass

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

    def load_case_for_edit(self, db_id):
        """Load an OT case by database id into the OT form for editing (public API)."""
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
