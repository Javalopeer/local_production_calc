import json
import os
import sys

# Add parent directory to path for direct execution
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import (
    QWidget, QFormLayout, QComboBox, QLineEdit,
    QPushButton, QLabel, QTimeEdit, QVBoxLayout, QHBoxLayout, QGroupBox, QProgressBar,
    QDateEdit, QTextEdit, QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QFrame, QSizePolicy, QApplication,
)
from PySide6.QtCore import QTime, QDate, Qt, Signal, QPropertyAnimation, QEasingCurve, QTimer
from db.database import get_connection
from .utils import (
    get_resource_path,
    calculate_case_value as _calc_cv,
    load_units_eq_data,
    get_units_per_case as _ue_lookup,
    calculate_equivalent_units,
    DAILY_BASE_MINUTES,
)
from datetime import datetime
from .downtime_manager import DowntimeManager
from .toggle_switch import ToggleSwitch
from .widgets import TimeEditWithShortcut, DateEditWithShortcut, card
from .clipboard_import_ui import (
    get_clipboard_case_data,
    has_detected_case_fields,
    show_import_confirmation,
    build_import_summary,
    apply_imported_case_data,
    get_import_not_detected_message,
    get_import_success_message,
    get_import_reminder_message,
)
from .theme_table_utils import (
    apply_table_theme, CLR_FG_LIGHT, CLR_FG_DARK,
    get_light_theme_colors, light_row_bg, light_header_bg, light_header_fg, mix_hex,
)


class RegisterTab(QWidget):
    case_saved = Signal()       # regular case saved/updated
    ot_saved   = Signal()       # overtime case saved/updated
    downtime_changed = Signal() # any downtime mutation (add/edit/delete/status)

    def __init__(self):
        super().__init__()
        self._mode        = "regular"   # "regular" | "overtime"
        self._editing_id  = None        # db id being edited (None = new case)
        self._import_toast = None
        self._import_toast_timer = None
        # Theme state — main emits themeChanged(is_light) and update_theme_labels
        # writes this. False until first signal arrives (app boots dark).
        self._light_mode_active = False
        self._mode_state = {
            "regular": {},
            "overtime": {},
        }

        self.load_standards()
        self.load_units_eq()

        self.case_id = QLineEdit()
        self.case_id.setPlaceholderText("Enter Case ID")
        self.case_id.textChanged.connect(self.on_case_id_changed)
        self.region = QComboBox()
        self.tipo = QComboBox()
        self.doctor = QLineEdit()
        self.doctor.setPlaceholderText("Optional")

        self.start_time = TimeEditWithShortcut()
        self.start_time.setMinimumWidth(120)
        self.start_time.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.end_time = TimeEditWithShortcut()
        self.end_time.setMinimumWidth(120)
        self.end_time.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.end_time.timeChanged.connect(self.validate_end_time)

        self.case_date = DateEditWithShortcut()
        self.case_date.setDate(QDate.currentDate())
        self.case_date.dateChanged.connect(self.on_date_changed)
        self.case_date.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Calculation Result â€" two KPI boxes side by side
        self._result_eff_value = QLabel("-")
        self._result_eff_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._result_eff_value.setStyleSheet(
            "font-size: 22px; font-weight: 700; color: #388BFD;"
        )
        self._result_eff_value.setMinimumHeight(30)
        _result_eff_label = QLabel("Efficiency")
        _result_eff_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _result_eff_label.setStyleSheet("font-size: 10px; color: #8B949E; font-weight: 600; letter-spacing: 0.5px;")

        self._result_val_value = QLabel("-")
        self._result_val_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._result_val_value.setStyleSheet(
            "font-size: 22px; font-weight: 700; color: #3FB950;"
        )
        self._result_val_value.setMinimumHeight(30)
        _result_val_label = QLabel("Case Value")
        _result_val_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _result_val_label.setStyleSheet("font-size: 10px; color: #8B949E; font-weight: 600; letter-spacing: 0.5px;")

        _kpi_left = QVBoxLayout()
        _kpi_left.setSpacing(2)
        _kpi_left.addWidget(self._result_eff_value)
        _kpi_left.addWidget(_result_eff_label)

        _kpi_right = QVBoxLayout()
        _kpi_right.setSpacing(2)
        _kpi_right.addWidget(self._result_val_value)
        _kpi_right.addWidget(_result_val_label)

        _kpi_divider = QFrame()
        _kpi_divider.setFrameShape(QFrame.Shape.VLine)
        _kpi_divider.setStyleSheet("color: #30363D;")

        _kpi_row = QHBoxLayout()
        _kpi_row.setSpacing(12)
        _kpi_row.addLayout(_kpi_left)
        _kpi_row.addWidget(_kpi_divider)
        _kpi_row.addLayout(_kpi_right)

        # Small status label for errors/messages (shown below KPI row)
        self.result_label = QLabel()
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("font-size: 11px; color: #8B949E;")
        self.result_label.setMinimumHeight(20)
        self.result_label.setVisible(False)

        result_kpi_layout = QVBoxLayout()
        result_kpi_layout.setContentsMargins(12, 10, 12, 10)
        result_kpi_layout.setSpacing(10)
        result_kpi_layout.addLayout(_kpi_row)
        result_kpi_layout.addWidget(self.result_label)

        self.daily_production_label = QLabel("Daily Production: 0.00%")
        self.equivalent_units_label = QLabel("Equivalent Units: 0.00")
        self._apply_kpi_label_styles(is_light=False)

        self.region.addItems(self.standards.keys())
        self.region.currentTextChanged.connect(self.update_case_types)
        
        self.update_case_types()

        self.start_time.setTime(QTime.currentTime())
        self.end_time.setTime(QTime(0, 0))  # Empty/default value

        calc_btn = QPushButton("Calculate")
        calc_btn.setMinimumHeight(30)
        calc_btn.clicked.connect(self.calculate)

        self._save_btn = QPushButton("Save Case")
        self._save_btn.setMinimumHeight(36)
        self._save_btn.clicked.connect(self.save_case)
        # keep local alias for the buttons layout below
        save_btn = self._save_btn

        # Form layout
        form = QFormLayout()
        form.setSpacing(10)
        form.setContentsMargins(11, 11, 11, 11)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.addRow("Case ID:", self.case_id)
        form.addRow("Region:", self.region)
        form.addRow("Type:", self.tipo)
        form.addRow("Doctor:", self.doctor)
        form.addRow("Date:", self.case_date)
        form.addRow("Start:", self.start_time)
        form.addRow("End:", self.end_time)

        # Ensure case-info inputs consume available field width
        for _w in (self.case_id, self.region, self.tipo, self.doctor):
            _w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        # Count to production toggle
        self.count_toggle = ToggleSwitch(checked=True)
        toggle_layout = QHBoxLayout()
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_label = QLabel("Count to production?")
        toggle_label.setStyleSheet("font-size: 11px;")
        toggle_layout.addWidget(toggle_label)
        toggle_layout.addWidget(self.count_toggle)
        toggle_layout.addStretch()
        toggle_widget = QWidget()
        toggle_widget.setLayout(toggle_layout)
        form.addRow("", toggle_widget)

        # Import button
        import_web_btn = QPushButton("Import")
        import_web_btn.setMinimumHeight(30)
        import_web_btn.setToolTip(
            "Copy all text on the case page (Ctrl+A, Ctrl+C),\n"
            "then click here or press Ctrl+Shift+I to auto-fill the fields."
        )
        import_web_btn.clicked.connect(self._on_import_case)

        # Buttons layout — row 1: secondary actions, row 2: primary save (full width)
        _secondary_row = QHBoxLayout()
        _secondary_row.setSpacing(8)
        _secondary_row.addWidget(import_web_btn)
        _secondary_row.addWidget(calc_btn)

        buttons_layout = QVBoxLayout()
        buttons_layout.setSpacing(6)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.addLayout(_secondary_row)
        buttons_layout.addWidget(save_btn)

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
        left_layout.addWidget(card("Calculation Result", result_kpi_layout))
        left_layout.addStretch()
        
        # â"€â"€ Right panel â€" page 0: Regular mode (Comments + Downtime + Progress) â"€â"€
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setSpacing(12)
        right_layout.setContentsMargins(10, 10, 10, 10)

        self.comments_input = QTextEdit()
        self.comments_input.setPlaceholderText("Optional comments...")
        self.comments_input.setMaximumHeight(45)
        self.comments_input.setStyleSheet("font-size: 11px; padding: 3px;")
        comments_card = card("Comments (Optional)", self.comments_input)
        comments_card.setMaximumHeight(100)
        right_layout.addWidget(comments_card)

        def _on_downtime_changed():
            self.load_daily_production()
            # Notify other tabs (Dashboard, History) so they re-query.
            self.downtime_changed.emit()
        self.downtime_manager = DowntimeManager(on_update_callback=_on_downtime_changed)
        self.downtime_manager.setMinimumHeight(260)
        self.downtime_manager.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.downtime_card = card("Downtime", self.downtime_manager)
        self.downtime_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_layout.addWidget(self.downtime_card, 1)

        # Regular cases mini-table (for selected date)
        self.reg_day_table = QTableWidget()
        self.reg_day_table.setColumnCount(7)
        self.reg_day_table.setHorizontalHeaderLabels(
            ["Case ID", "Doctor", "Type", "Time", "Eff %", "Value %", "UE"]
        )
        self.reg_day_table.verticalHeader().setVisible(False)
        self.reg_day_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.reg_day_table.setAlternatingRowColors(False)
        self.reg_day_table.setShowGrid(True)
        self.reg_day_table.setStyleSheet("""
            QTableWidget { gridline-color: #21262D; border: none; }
            QHeaderView::section {
                background-color: #161B22;
                color: #8B949E;
                border: none;
                border-bottom: 1px solid #30363D;
                padding: 5px 6px;
                font-weight: 700;
                font-size: 10px;
            }
        """)
        # Make the table fill the card width like the Downtime table does:
        # Doctor stretches to consume any leftover horizontal space; the rest
        # stay at fixed widths so they don't clip the headers.
        _hdr = self.reg_day_table.horizontalHeader()
        _hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        _hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        _hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        _hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        _hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        _hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        _hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        _hdr.setStretchLastSection(False)
        self.reg_day_table.setColumnWidth(0, 92)   # Case ID
        self.reg_day_table.setColumnWidth(1, 132)  # Doctor (stretches; this is the min)
        self.reg_day_table.setColumnWidth(2, 86)   # Type
        self.reg_day_table.setColumnWidth(3, 56)   # Time
        self.reg_day_table.setColumnWidth(4, 60)   # Eff %
        self.reg_day_table.setColumnWidth(5, 70)   # Value %
        self.reg_day_table.setColumnWidth(6, 56)   # UE
        self.reg_day_table.setMinimumHeight(150)
        self.reg_day_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._reg_table_card = card("Today's Cases", self.reg_day_table)
        self._reg_table_card.setMinimumHeight(190)
        right_layout.addWidget(self._reg_table_card)

        right_layout.addWidget(self.progress_group)
        right_layout.addStretch()

        # â"€â"€ Right panel â€" page 1: OT mode (OT summary + OT cases table) â"€â"€â"€â"€â"€â"€
        ot_view_widget = QWidget()
        ot_view_layout = QVBoxLayout(ot_view_widget)
        ot_view_layout.setSpacing(12)
        ot_view_layout.setContentsMargins(10, 10, 10, 10)

        # OT comments card (same as Regular, but independent)
        self.ot_comments_input = QTextEdit()
        self.ot_comments_input.setPlaceholderText("Optional comments...")
        self.ot_comments_input.setMaximumHeight(45)
        self.ot_comments_input.setStyleSheet("font-size: 11px; padding: 3px;")
        ot_comments_card = card("Comments (Optional)", self.ot_comments_input)
        ot_comments_card.setMaximumHeight(100)
        ot_view_layout.addWidget(ot_comments_card)

        # OT day summary card
        self.ot_day_prod_label = QLabel("OT Production: 0.00%")
        self.ot_day_prod_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #FF9800;")
        self.ot_day_prod_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ot_day_ue_label = QLabel("OT Equiv. Units: 0.00")
        self.ot_day_ue_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #CE93D8;")
        self.ot_day_ue_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ot_day_progress = QProgressBar()
        self.ot_day_progress.setMinimum(0)
        self.ot_day_progress.setMaximum(100)
        self.ot_day_progress.setValue(0)
        self.ot_day_progress.setFormat("%v%")
        self.ot_day_progress.setMinimumHeight(24)
        self.ot_day_progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #3c3c3c; border-radius: 8px;
                text-align: center; background-color: #2b2b2b; color: #fff;
            }
            QProgressBar::chunk { background-color: #FF9800; border-radius: 6px; }
        """)
        _ot_sum_layout = QVBoxLayout()
        _ot_sum_layout.addWidget(self.ot_day_prod_label)
        _ot_sum_layout.addWidget(self.ot_day_ue_label)
        _ot_sum_layout.addWidget(self.ot_day_progress)
        self._ot_summary_card = card("OT Daily Summary", _ot_sum_layout)
        self._ot_summary_card.setMaximumHeight(130)
        ot_view_layout.addWidget(self._ot_summary_card)

        # OT cases mini-table
        self._ot_reg_case_ids: list = []
        self.ot_reg_table = QTableWidget()
        self.ot_reg_table.setColumnCount(7)
        self.ot_reg_table.setHorizontalHeaderLabels(["Case ID", "Doctor", "Type", "Time", "Eff %", "Value %", "UE"])
        self.ot_reg_table.verticalHeader().setVisible(False)
        self.ot_reg_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.ot_reg_table.setAlternatingRowColors(False)
        self.ot_reg_table.setShowGrid(True)
        self.ot_reg_table.setStyleSheet("""
            QTableWidget { gridline-color: #444; }
            QHeaderView::section {
                background-color: #333; border: 1px solid #555; padding: 4px;
            }
        """)
        # Match the regular table: Doctor stretches, others fixed.
        _ot_hdr = self.ot_reg_table.horizontalHeader()
        _ot_hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        _ot_hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        _ot_hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        _ot_hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        _ot_hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        _ot_hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        _ot_hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        _ot_hdr.setStretchLastSection(False)
        self.ot_reg_table.setColumnWidth(0, 92)
        self.ot_reg_table.setColumnWidth(1, 132)
        self.ot_reg_table.setColumnWidth(2, 86)
        self.ot_reg_table.setColumnWidth(3, 56)
        self.ot_reg_table.setColumnWidth(4, 60)
        self.ot_reg_table.setColumnWidth(5, 70)
        self.ot_reg_table.setColumnWidth(6, 56)
        self.ot_reg_table.setMinimumHeight(150)
        self.ot_reg_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        _ot_table_card = card("Today's OT Cases", self.ot_reg_table)
        _ot_table_card.setMinimumHeight(190)
        ot_view_layout.addWidget(_ot_table_card)
        self._ot_view_layout = ot_view_layout

        ot_view_layout.addStretch()

        # â"€â"€ Stacked right panel â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
        self._right_stack = QStackedWidget()
        self._right_stack.addWidget(right_widget)    # index 0 â€" regular
        self._right_stack.addWidget(ot_view_widget)  # index 1 â€" OT
        self._right_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

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
        self.content_layout.addWidget(self._right_stack)
        
        # Scroll area for content
        scroll = QScrollArea()
        scroll.setWidget(self.content_widget)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        
        # â"€â"€ Mode toggle bar â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
        from PySide6.QtGui import QColor as _QColor
        mode_bar_widget = QWidget()
        mode_bar_widget.setMaximumHeight(40)
        mode_bar_layout = QHBoxLayout(mode_bar_widget)
        mode_bar_layout.setContentsMargins(8, 4, 8, 4)
        mode_bar_layout.setSpacing(10)

        self._mode_label_regular = QLabel("Regular")
        self._mode_label_regular.setStyleSheet(
            "font-size: 12px; font-weight: 700; color: #388BFD;"
        )

        self._mode_toggle = ToggleSwitch(
            checked=False,
            color_on=_QColor(240, 136, 62),   # orange = OT
            color_off=_QColor(56, 139, 253),   # blue   = Regular
        )
        self._mode_toggle.toggled.connect(self._on_mode_toggled)

        self._mode_label_ot = QLabel("OT")
        self._mode_label_ot.setStyleSheet(
            "font-size: 12px; font-weight: 700; color: #6E7681;"
        )

        mode_bar_layout.addStretch()
        mode_bar_layout.addWidget(self._mode_label_regular)
        mode_bar_layout.addWidget(self._mode_toggle)
        mode_bar_layout.addWidget(self._mode_label_ot)
        mode_bar_layout.addStretch()

        # â"€â"€ Edit banner â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
        self._edit_banner = QFrame()
        self._edit_banner.setFrameShape(QFrame.Shape.NoFrame)
        self._edit_banner.setFixedHeight(42)
        self._edit_banner.setVisible(False)
        self._edit_banner.setStyleSheet(
            "QFrame { background-color: #0D1117; border: 1px solid #388BFD; border-radius: 8px; }"
        )

        self._edit_accent = QFrame(self._edit_banner)
        self._edit_accent.setFixedWidth(4)
        self._edit_accent.setStyleSheet("background-color: #388BFD; border-radius: 2px;")

        _badge = QLabel("✎  EDIT MODE")
        _badge.setStyleSheet(
            "color: #388BFD; font-weight: 900; font-size: 10px; letter-spacing: 1px;"
            " background: transparent; padding: 0 6px;"
        )

        _sep = QFrame()
        _sep.setFrameShape(QFrame.Shape.VLine)
        _sep.setStyleSheet("color: #30363D;")
        _sep.setFixedWidth(1)

        self._edit_banner_label = QLabel("Editing case — save to update")
        self._edit_banner_label.setStyleSheet(
            "color: #CDD9E5; font-size: 12px; font-weight: 600; background: transparent;"
        )

        _banner_cancel_btn = QPushButton("✕  Cancel")
        _banner_cancel_btn.setFixedSize(80, 26)
        _banner_cancel_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #444C56;"
            " border-radius: 5px; color: #8B949E; font-size: 11px; font-weight: 600; }"
            " QPushButton:hover { border-color: #F85149; color: #F85149; }"
        )
        _banner_cancel_btn.clicked.connect(self._cancel_edit)

        self._edit_banner.setMaximumWidth(560)

        _banner_layout = QHBoxLayout(self._edit_banner)
        _banner_layout.setContentsMargins(0, 4, 14, 4)
        _banner_layout.setSpacing(0)
        _banner_layout.addWidget(self._edit_accent)
        _banner_layout.addSpacing(10)
        _banner_layout.addWidget(_badge)
        _banner_layout.addWidget(_sep)
        _banner_layout.addSpacing(10)
        _banner_layout.addWidget(self._edit_banner_label, 1)
        _banner_layout.addSpacing(8)
        _banner_layout.addWidget(_banner_cancel_btn)

        self._banner_pulse_state = False
        self._banner_pulse_timer = QTimer(self)
        self._banner_pulse_timer.setInterval(550)
        self._banner_pulse_timer.timeout.connect(self._pulse_edit_banner)

        # Apply initial mode styling
        self._update_mode_ui()

        # Main layout
        self.final_layout = QVBoxLayout()
        self.final_layout.setContentsMargins(5, 5, 5, 5)
        self.final_layout.setSpacing(4)
        self.final_layout.addWidget(mode_bar_widget)
        self.final_layout.addWidget(self._edit_banner, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.final_layout.addWidget(scroll, 1)
        self.setLayout(self.final_layout)
        
        # Store current layout mode
        self.is_vertical = False
        # Keep Register in single-column mode unless there is ample width.
        # Current app max width is 900, so this avoids cramped two-column rendering.
        self._stack_threshold = 980
        self._apply_responsive_layout(self.width())
        
        self.load_daily_production()
        self._load_regular_day_cases()
        self._sync_regular_progress_visibility()
        self._capture_mode_state("regular")

    def _apply_kpi_label_styles(self, is_light: bool):
        """Restyle the two KPI labels (Daily Production / Equivalent Units)
        with theme-aware foreground colors so light mode keeps decent contrast."""
        if is_light:
            prod_color = "#0550AE"   # darker blue for light bg
            ue_color = "#6E40C9"     # darker purple for light bg
        else:
            prod_color = "#388BFD"
            ue_color = "#A371F7"
        if hasattr(self, "daily_production_label"):
            self.daily_production_label.setStyleSheet(
                f"font-size: 14px; font-weight: 700; color: {prod_color};"
            )
        if hasattr(self, "equivalent_units_label"):
            self.equivalent_units_label.setStyleSheet(
                f"font-size: 14px; font-weight: 700; color: {ue_color};"
            )

    def update_font_sizes(self, _new_size: int = 0):
        """Re-render tables so the QFont calls inside load_daily_production
        and _load_ot_day_cases pick up the new global scale."""
        try:
            self.load_daily_production()
        except Exception:
            pass
        try:
            self._load_ot_day_cases()
        except Exception:
            pass

    def update_theme_labels(self, is_light: bool):
        """Apply light/dark table styles while preserving per-cell badge colors."""
        from PySide6.QtGui import QColor
        # Remember the active theme so other render paths (notably the OT
        # table + OT progress bar in `_load_ot_day_cases`) pick the right
        # palette regardless of any QApplication stylesheet quirk.
        self._light_mode_active = bool(is_light)
        self._apply_kpi_label_styles(is_light)
        colors = get_light_theme_colors()
        fg_color = QColor(colors["text_primary"]) if is_light else CLR_FG_LIGHT
        light_css = (
            f' QTableWidget {{ background-color: {colors["surface_bg"]}; gridline-color: {colors["border"]}; border: 1px solid {colors["border"]}; }} '
            f' QHeaderView::section {{ background-color: {light_header_bg(colors)}; color: {light_header_fg(colors)}; border: 1px solid {colors["border"]}; padding: 5px 6px; font-weight: 700; font-size: 10px; }} '
        )
        apply_table_theme(
            self,
            is_light,
            light_append_css=light_css,
            adaptive_fg_by_bg=True,
            adaptive_default_fg=fg_color,
        )
        # Repaint current mode rows with correct foreground/background after theme change.
        if self._mode == "overtime":
            self._load_ot_day_cases()
        else:
            self._load_regular_day_cases()
        # Propagate theme change to the embedded Downtime table
        if hasattr(self, "downtime_manager") and self.downtime_manager is not None:
            try:
                self.downtime_manager.update_theme_labels(is_light)
            except Exception:
                pass

    def _is_light_mode(self) -> bool:
        """Return the last theme state pushed via update_theme_labels.

        Other tabs route theme changes through `themeChanged` → an
        instance flag flipped in `update_theme_labels`. This is the only
        source of truth that survives custom light palettes (the previous
        substring-based check on `app.styleSheet()` broke whenever the
        user customized the light palette, so OT-mode widgets ended up
        styled as dark while the rest of the UI was light).
        """
        return bool(getattr(self, "_light_mode_active", False))

    def _lookup_std_time(self, region: str | None, tipo: str | None):
        """Return the standard time (minutes) for region+type, or None."""
        if not region or not tipo:
            return None
        try:
            return self.standards[region]["Aligners"][tipo]
        except (KeyError, TypeError):
            return None

    @staticmethod
    def _paint_efficiency_cell(item, eff_value):
        """Color a cell green/yellow/red based on efficiency thresholds."""
        from PySide6.QtGui import QBrush, QColor
        try:
            ev = float(eff_value)
        except (TypeError, ValueError):
            return
        if ev >= 100:
            item.setBackground(QBrush(QColor(76, 175, 80)))
        elif ev >= 95:
            item.setBackground(QBrush(QColor(255, 193, 7)))
        else:
            item.setBackground(QBrush(QColor(244, 67, 54)))

    @staticmethod
    def _paint_time_cell(item, tiempo_real, std_time):
        """Color a Time cell green when within the standard, red when over.

        Same green/red used by the Eff% cell so a row reads consistently:
        if Time is red, Eff is going to be red too.
        """
        from PySide6.QtGui import QBrush, QColor
        try:
            real = float(tiempo_real)
            std = float(std_time)
        except (TypeError, ValueError):
            return
        if std <= 0:
            return
        # 5 % grace before flipping to red so a borderline case isn't punished
        if real <= std * 1.05:
            item.setBackground(QBrush(QColor(76, 175, 80)))
        else:
            item.setBackground(QBrush(QColor(244, 67, 54)))
    
    def resizeEvent(self, event):
        """Handle resize to switch between horizontal and vertical layout"""
        super().resizeEvent(event)
        self._apply_responsive_layout(event.size().width())
        self._reposition_import_toast()

    def _apply_responsive_layout(self, width: int):
        """Apply horizontal/vertical arrangement based on available width."""
        threshold = getattr(self, "_stack_threshold", 980)

        if width < threshold and not self.is_vertical:
            self.is_vertical = True
            self.content_layout.setDirection(QVBoxLayout.Direction.TopToBottom)
            # Set fixed width so widgets center properly and are wider
            responsive_width = min(width - 40, 600)  # Use most of available width
            self.left_widget.setFixedWidth(responsive_width)
            self._right_stack.setFixedWidth(responsive_width)
            self._sync_regular_progress_visibility()
        elif width >= threshold and self.is_vertical:
            self.is_vertical = False
            self.content_layout.setDirection(QHBoxLayout.Direction.LeftToRight)
            # Remove fixed width in horizontal mode
            self.left_widget.setMinimumWidth(0)
            self.left_widget.setMaximumWidth(16777215)
            self._right_stack.setMinimumWidth(0)
            self._right_stack.setMaximumWidth(16777215)
            self._sync_regular_progress_visibility()
        elif self.is_vertical:
            # Update width when resizing in vertical mode
            responsive_width = min(width - 40, 600)
            self.left_widget.setFixedWidth(responsive_width)
            self._right_stack.setFixedWidth(responsive_width)

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

    def _capture_mode_state(self, mode: str):
        """Capture form values for one mode so Regular and OT drafts stay independent."""
        self._mode_state[mode] = {
            "case_id": self.case_id.text(),
            "region": self.region.currentText(),
            "tipo": self.tipo.currentText(),
            "doctor": self.doctor.text(),
            "date": self.case_date.date().toString("yyyy-MM-dd"),
            "start": self.start_time.time().toString("HH:mm"),
            "end": self.end_time.time().toString("HH:mm"),
            "count": self.count_toggle.isChecked(),
            "comments": self._comments_widget_for_mode(mode).toPlainText(),
        }

    def _comments_widget_for_mode(self, mode: str) -> QTextEdit:
        if mode == "overtime" and hasattr(self, "ot_comments_input"):
            return self.ot_comments_input
        return self.comments_input

    def _restore_mode_state(self, mode: str):
        """Restore previously captured values for a mode, or clear if empty/new."""
        state = self._mode_state.get(mode) or {}
        self.case_id.setText(state.get("case_id", ""))
        region_value = state.get("region", "")
        if region_value:
            idx = self.region.findText(region_value)
            if idx >= 0:
                self.region.setCurrentIndex(idx)
        else:
            if self.region.count() > 0:
                self.region.setCurrentIndex(0)
        self.update_case_types()
        tipo_value = state.get("tipo", "")
        if tipo_value:
            idx = self.tipo.findText(tipo_value)
            if idx >= 0:
                self.tipo.setCurrentIndex(idx)
        else:
            if self.tipo.count() > 0:
                self.tipo.setCurrentIndex(0)
        self.doctor.setText(state.get("doctor", ""))
        date_value = state.get("date", "")
        if date_value:
            self.case_date.setDate(QDate.fromString(date_value, "yyyy-MM-dd"))
        else:
            self.case_date.setDate(QDate.currentDate())
        start_value = state.get("start")
        end_value = state.get("end")
        self.start_time.setTime(QTime.fromString(start_value, "HH:mm") if start_value else QTime.currentTime())
        self.end_time.setTime(QTime.fromString(end_value, "HH:mm") if end_value else QTime(0, 0))
        self.count_toggle.setChecked(bool(state.get("count", True)))
        self._comments_widget_for_mode(mode).setText(state.get("comments", ""))
        self._reset_result_kpi()

    def _sync_regular_progress_visibility(self):
        """
        Keep progress cards in the correct container for the active mode.

        Regular: uses `progress_group`.
        OT: uses `_ot_summary_card`.
        In vertical mode, active card becomes sticky at the bottom (outside the scroll area).
        """
        if not hasattr(self, "final_layout") or not hasattr(self, "right_layout"):
            return
        if not hasattr(self, "_ot_summary_card") or not hasattr(self, "_ot_view_layout"):
            return

        is_ot = self._mode == "overtime"

        # Detach from any previous parent/layout position first.
        self.right_layout.removeWidget(self.progress_group)
        self.final_layout.removeWidget(self.progress_group)
        self._ot_view_layout.removeWidget(self._ot_summary_card)
        self.final_layout.removeWidget(self._ot_summary_card)

        if is_ot:
            # Active OT summary is always sticky at bottom (outside scroll), in both layouts.
            self.progress_group.setVisible(False)
            self._ot_summary_card.setVisible(True)
            self.final_layout.addWidget(self._ot_summary_card, 0)
            return

        # Active Regular summary is always sticky at bottom (outside scroll), in both layouts.
        self._ot_summary_card.setVisible(False)
        self.progress_group.setVisible(True)
        self.final_layout.addWidget(self.progress_group, 0)

    def load_standards(self):
        from .utils import load_standards_data
        self.standards = load_standards_data()

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
            WHERE fecha = ? AND (status = 'approved' OR status IS NULL)
        """, (date,))
        
        result = cursor.fetchone()
        conn.close()
        
        total_downtime = result[0] if result[0] else 0.0
        return total_downtime

    # â"€â"€ Result KPI helpers â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

    def _show_result(self, efficiency: float, case_value: float, color: str):
        """Update the two KPI boxes with calculated values."""
        self._result_eff_value.setText(f"{efficiency:.1f}%")
        self._result_eff_value.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {color};")
        self._result_val_value.setText(f"{case_value:.3f}%")
        self.result_label.setVisible(False)

    def _set_result_status(self, msg: str, color: str = "#8B949E"):
        """Show a status/error message below the KPI row."""
        self.result_label.setText(msg)
        self.result_label.setStyleSheet(f"font-size: 11px; color: {color};")
        self.result_label.setVisible(True)

    def _reset_result_kpi(self):
        """Reset KPI boxes to blank state."""
        self._result_eff_value.setText("-")
        self._result_eff_value.setStyleSheet("font-size: 22px; font-weight: 700; color: #388BFD;")
        self._result_val_value.setText("-")
        self._result_val_value.setStyleSheet("font-size: 22px; font-weight: 700; color: #3FB950;")
        self.result_label.setVisible(False)

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
            self._set_result_status("Invalid time", "#F85149")
            return

        efficiency = (std_time / real_minutes) * 100

        # Determine status and color
        if efficiency >= 100:
            color = "#3FB950"
        elif efficiency >= 95:
            color = "#D29922"
        else:
            color = "#F85149"

        self._show_result(efficiency, case_value, color)

    def on_date_changed(self):
        """Called when the date picker changes - reload production and downtime for that date"""
        selected_date = self.case_date.date().toString("yyyy-MM-dd")
        self.downtime_manager.set_date(selected_date)
        self.load_daily_production()
        self._load_regular_day_cases()
        if self._mode == "overtime":
            self._load_ot_day_cases()

    def load_daily_production(self):
        # Use selected date from picker instead of today
        selected_date = self.case_date.date().toString("yyyy-MM-dd")
        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Get total case values for selected date (only count_production = 1)
            cursor.execute("""
                SELECT SUM(case_value)
                FROM cases
                WHERE fecha = ? AND (count_production = 1 OR count_production IS NULL)
            """, (selected_date,))

            result = cursor.fetchone()
            total_cases = result[0] if result[0] else 0.0

            # Get cases by region+type for equivalent units calculation
            cursor.execute("""
                SELECT region, tipo_caso, COUNT(*), SUM(case_value)
                FROM cases
                WHERE fecha = ? AND (count_production = 1 OR count_production IS NULL)
                GROUP BY region, tipo_caso
            """, (selected_date,))

            region_cases = cursor.fetchall()
            conn.close()
        except Exception as exc:
            # DB locked or unavailable — keep prior labels rather than blanking the UI
            print(f"[RegisterTab] load_daily_production query failed: {exc}")
            return

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
        downtime_value = (total_downtime / DAILY_BASE_MINUTES) * 100 if total_downtime > 0 else 0
        
        # Total production = cases + downtime (both count as production)
        total_production = total_cases + downtime_value
        
        # Resolve effective targets for this date (UE target may vary by date)
        try:
            from sync.daily_performance import (
                PRODUCTION_TARGET_PCT, get_ue_target_for_date,
            )
            prod_target = PRODUCTION_TARGET_PCT
            ue_target = get_ue_target_for_date(selected_date)
        except Exception:
            prod_target = 95.0
            ue_target = 14.0

        display_label = f"Daily Production: {total_production:.2f}%"
        if total_downtime > 0:
            display_label += f" (Cases: {total_cases:.2f}% + Downtime: {downtime_value:.2f}%)"
        display_label += f"  •  Target: {prod_target:.0f}%"

        self.daily_production_label.setText(display_label)

        self.equivalent_units_label.setText(
            f"Equivalent Units: {total_equivalent_units:.2f}  •  Target: {ue_target:.2f}"
        )
        
        # Update progress bar with animation - NO CAP, allow any value
        self.progress_bar.setMaximum(max(100, int(total_production) + 10))
        
        # Animate the progress bar
        self.animate_progress_bar(int(total_production))
        
        # Color based on performance threshold
        if total_production < 95:
            bar_color = "#F85149"   # red
        elif total_production < 100:
            bar_color = "#D29922"   # amber
        else:
            bar_color = "#3FB950"   # green

        # Adapt track + text colors to active theme so the bar doesn't show
        # a dark slab on a light background.
        try:
            from PySide6.QtGui import QPalette
            pal = QApplication.instance().palette()
            is_light = pal.color(QPalette.ColorRole.Window).lightness() > 128
        except Exception:
            is_light = False
        track_bg = "#E1E4E8" if is_light else "#21262D"
        text_fg = "#1F2328" if is_light else "#E6EDF3"

        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {track_bg};
                border: none;
                border-radius: 6px;
                text-align: center;
                min-height: 24px;
                color: {text_fg};
                font-weight: 700;
                font-size: 11px;
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
        """Load a regular case from database into form for editing."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT case_id, region, tipo_caso, doctor, fecha, hora_inicio, hora_fin, count_production, comments
            FROM cases WHERE id = ?
        """, (db_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return

        self.switch_to_regular_mode()
        self._editing_id = db_id

        self.case_id.setText(row[0])
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

        count_prod = row[7] if row[7] is not None else 1
        self.count_toggle.setChecked(bool(count_prod))
        self.comments_input.setText(row[8] if row[8] else "")

        self._edit_banner_label.setText(f"Case  {row[0]}")
        self._show_edit_banner(is_ot=False)
        self._reset_result_kpi()

    def load_ot_case_for_edit(self, db_id: int):
        """Load an OT case from ot_cases into the form for editing."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT case_id, region, tipo_caso, doctor, fecha, hora_inicio, hora_fin, count_production, comments
            FROM ot_cases WHERE id = ?
        """, (db_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return

        self.switch_to_ot_mode()
        self._editing_id = db_id

        self.case_id.setText(row[0])
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

        count_prod = row[7] if row[7] is not None else 1
        self.count_toggle.setChecked(bool(count_prod))
        if hasattr(self, "ot_comments_input"):
            self.ot_comments_input.setText(row[8] if row[8] else "")

        self._edit_banner_label.setText(f"Case  {row[0]}")
        self._show_edit_banner(is_ot=True)
        self._reset_result_kpi()

    def _update_mode_ui(self):
        """Sync toggle label colors, save button, and right panel to self._mode."""
        is_ot = self._mode == "overtime"

        # Update label emphasis
        if hasattr(self, '_mode_label_regular'):
            self._mode_label_regular.setStyleSheet(
                "font-size: 12px; font-weight: 700; color: #8B949E;"
                if is_ot else
                "font-size: 12px; font-weight: 700; color: #388BFD;"
            )
        if hasattr(self, '_mode_label_ot'):
            self._mode_label_ot.setStyleSheet(
                "font-size: 12px; font-weight: 700; color: #F0883E;"
                if is_ot else
                "font-size: 12px; font-weight: 700; color: #6E7681;"
            )

        # Sync toggle position without re-firing the signal
        if hasattr(self, '_mode_toggle') and self._mode_toggle.isChecked() != is_ot:
            self._mode_toggle.blockSignals(True)
            self._mode_toggle.setChecked(is_ot)
            self._mode_toggle.blockSignals(False)

        # Save button
        if is_ot:
            self._save_btn.setText("Save Case")
            self._save_btn.setStyleSheet("""
                QPushButton { background-color: #F0883E; border: 1px solid #F0883E;
                              color: white; border-radius: 6px; font-weight: 700;
                              font-size: 13px; padding: 4px 12px; }
                QPushButton:hover { background-color: #D97834; }
            """)
        else:
            self._save_btn.setText("Save Case")
            self._save_btn.setStyleSheet("""
                QPushButton { background-color: #238636; border: 1px solid #2EA043;
                              color: white; border-radius: 6px; font-weight: 700;
                              font-size: 13px; padding: 4px 12px; }
                QPushButton:hover { background-color: #2EA043; }
            """)

        # Right panel stack
        if hasattr(self, '_right_stack'):
            self._right_stack.setCurrentIndex(1 if is_ot else 0)
        self._sync_regular_progress_visibility()

    def _on_mode_toggled(self, checked: bool):
        """Called when the user flips the mode toggle."""
        if checked:
            self.switch_to_ot_mode()
        else:
            self.switch_to_regular_mode()

    def switch_to_ot_mode(self):
        """Switch the form to overtime mode and load OT cases."""
        if self._mode == "regular":
            self._capture_mode_state("regular")
        self._mode = "overtime"
        self._editing_id = None
        self._edit_banner.setVisible(False)
        self._update_mode_ui()
        self._restore_mode_state("overtime")
        self._load_ot_day_cases()

    def switch_to_regular_mode(self):
        """Switch the form to regular mode."""
        if self._mode == "overtime":
            self._capture_mode_state("overtime")
        self._mode = "regular"
        self._editing_id = None
        self._edit_banner.setVisible(False)
        self._update_mode_ui()
        self._restore_mode_state("regular")
        self._load_regular_day_cases()

    def _load_regular_day_cases(self):
        """Populate the embedded regular table with selected-date regular cases."""
        from PySide6.QtGui import QColor, QBrush, QFont
        is_light = self._is_light_mode()
        colors = get_light_theme_colors()
        selected_date = self.case_date.date().toString("yyyy-MM-dd")
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT case_id, doctor, tipo_caso, tiempo_real, efficiency, case_value, region, count_production
            FROM cases WHERE fecha = ? ORDER BY id DESC
        """, (selected_date,))
        rows = cursor.fetchall()
        conn.close()

        self.reg_day_table.setRowCount(len(rows))
        for i, (case_id, doctor, tipo, tiempo, eff, cv, region, count_prod) in enumerate(rows):
            counts = count_prod if count_prod is not None else 1
            if counts == 0:
                bg = QColor("#E9D8A6") if is_light else QColor(180, 150, 50)
            else:
                bg = light_row_bg(i, colors) if is_light else (QColor(43, 43, 43) if i % 2 == 0 else QColor(50, 50, 50))
            bg_brush = QBrush(bg)
            fg_brush = QBrush(CLR_FG_DARK if is_light else CLR_FG_LIGHT)
            bold = QFont()
            bold.setBold(True)
            ue_val = calculate_equivalent_units(self.units_eq, region or "", tipo or "", cv or 0.0, count=1)

            # Look up the expected std_time for this case so we can colour the
            # Time cell the same way Eff% gets coloured (green = within
            # standard, red = exceeded).
            std_time = self._lookup_std_time(region, tipo)

            vals = [
                str(case_id or ""),
                str(doctor or ""),
                str(tipo or ""),
                f"{tiempo:.0f}" if tiempo else "-",
                f"{eff:.0f}" if eff else "-",
                f"{cv:.2f}" if cv else "-",
                f"{ue_val:.2f}",
            ]
            for col, text in enumerate(vals):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setBackground(bg_brush)
                item.setForeground(fg_brush)
                item.setToolTip(text)
                if col == 0:
                    item.setFont(bold)
                if col == 3 and tiempo and std_time:
                    self._paint_time_cell(item, tiempo, std_time)
                if col == 4 and eff:
                    self._paint_efficiency_cell(item, eff)
                self.reg_day_table.setItem(i, col, item)

    def _load_ot_day_cases(self):
        """Populate the embedded OT table with today's (or selected date's) OT cases."""
        from PySide6.QtGui import QColor, QBrush, QFont
        is_light = self._is_light_mode()
        colors = get_light_theme_colors()
        selected_date = self.case_date.date().toString("yyyy-MM-dd")
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, case_id, doctor, tipo_caso, tiempo_real, efficiency, case_value, region, count_production
            FROM ot_cases WHERE fecha = ? ORDER BY id DESC
        """, (selected_date,))
        rows = cursor.fetchall()

        # Also compute summary stats
        cursor.execute("""
            SELECT SUM(case_value), region, tipo_caso, COUNT(*), SUM(case_value)
            FROM ot_cases
            WHERE fecha = ? AND (count_production = 1 OR count_production IS NULL)
            GROUP BY region, tipo_caso
        """, (selected_date,))
        region_rows = cursor.fetchall()
        conn.close()

        # Update summary labels
        total_ot_pct = sum((r[6] or 0.0) for r in rows if r[8] in (1, None)) or 0.0
        total_ue = 0.0
        for _, region, case_type, count, sum_cv in region_rows:
            if count and sum_cv:
                total_ue += calculate_equivalent_units(self.units_eq, region, case_type, sum_cv, count=count)

        self.ot_day_prod_label.setText(f"OT Production: {total_ot_pct:.2f}%")
        self.ot_day_ue_label.setText(f"OT Equiv. Units: {total_ue:.2f}")
        self.ot_day_progress.setMaximum(max(100, int(total_ot_pct) + 10))
        self.ot_day_progress.setValue(int(total_ot_pct))
        if total_ot_pct < 10:
            bar_color = "#444C56"
        elif total_ot_pct < 25:
            bar_color = "#F0883E"
        else:
            bar_color = "#3FB950"
        self.ot_day_progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {"#F3F4F6" if is_light else "#21262D"};
                border: 1px solid {colors["border"] if is_light else "#21262D"};
                border-radius: 6px;
                text-align: center;
                min-height: 24px;
                color: {colors["text_primary"] if is_light else "#E6EDF3"};
                font-weight: 700;
                font-size: 11px;
            }}
            QProgressBar::chunk {{ background-color: {bar_color}; border-radius: 6px; }}
        """)
        if is_light:
            self.ot_reg_table.setStyleSheet(f"""
                QTableWidget {{ gridline-color: {colors["border"]}; border: 1px solid {colors["border"]}; background-color: {colors["surface_bg"]}; }}
                QHeaderView::section {{
                    background-color: {light_header_bg(colors)};
                    color: {light_header_fg(colors)};
                    border: 1px solid {colors["border"]};
                    padding: 5px 6px;
                    font-weight: 700;
                    font-size: 10px;
                }}
            """)
        else:
            self.ot_reg_table.setStyleSheet("""
                QTableWidget { gridline-color: #21262D; border: none; }
                QHeaderView::section {
                    background-color: #161B22;
                    color: #8B949E;
                    border: none;
                    border-bottom: 1px solid #30363D;
                    padding: 5px 6px;
                    font-weight: 700;
                    font-size: 10px;
                }
            """)

        # Populate table
        self._ot_reg_case_ids = []
        self.ot_reg_table.setRowCount(len(rows))
        for i, (db_id, case_id, doctor, tipo, tiempo, eff, cv, region, count_prod) in enumerate(rows):
            self._ot_reg_case_ids.append(db_id)
            counts = count_prod if count_prod is not None else 1
            if counts == 0:
                bg = QColor("#E9D8A6") if is_light else QColor(180, 150, 50)
            else:
                bg = light_row_bg(i, colors) if is_light else (QColor(43, 43, 43) if i % 2 == 0 else QColor(50, 50, 50))
            bg_brush = QBrush(bg)
            fg_brush = QBrush(CLR_FG_DARK if is_light else CLR_FG_LIGHT)
            bold = QFont(); bold.setBold(True)

            ue_val = calculate_equivalent_units(self.units_eq, region or "", tipo or "", cv or 0.0, count=1)
            std_time = self._lookup_std_time(region, tipo)

            vals = [str(case_id or ""), str(doctor or ""), str(tipo or ""), f"{tiempo:.0f}" if tiempo else "-",
                    f"{eff:.0f}" if eff else "-", f"{cv:.2f}" if cv else "-", f"{ue_val:.2f}"]
            for col, text in enumerate(vals):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setBackground(bg_brush)
                item.setForeground(fg_brush)
                item.setToolTip(text)
                if col == 0:
                    item.setFont(bold)
                if col == 3 and tiempo and std_time:
                    self._paint_time_cell(item, tiempo, std_time)
                if col == 4 and eff:
                    self._paint_efficiency_cell(item, eff)
                self.ot_reg_table.setItem(i, col, item)

    def _delete_selected_ot_case(self):
        """Delete the OT case selected in the embedded OT table."""
        row = self.ot_reg_table.currentRow()
        if row < 0 or row >= len(self._ot_reg_case_ids):
            return
        db_id = self._ot_reg_case_ids[row]
        case_id_text = self.ot_reg_table.item(row, 0).text() if self.ot_reg_table.item(row, 0) else str(db_id)
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete OT case '{case_id_text}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM ot_cases WHERE id = ?", (db_id,))
            conn.commit()
            conn.close()
            self._load_ot_day_cases()
            self.ot_saved.emit()

    def _show_edit_banner(self, is_ot: bool):
        """Apply mode-specific color and start pulse animation."""
        color = "#F0883E" if is_ot else "#388BFD"
        self._edit_accent.setStyleSheet(f"background-color: {color}; border-radius: 2px;")
        badge_text = "\u270e  EDIT MODE  \u2022  OT" if is_ot else "\u270e  EDIT MODE"
        # Find the badge label (first QLabel child of banner)
        for w in self._edit_banner.findChildren(QLabel):
            if "EDIT MODE" in (w.text() or ""):
                w.setText(badge_text)
                w.setStyleSheet(
                    f"color: {color}; font-weight: 900; font-size: 10px;"
                    " letter-spacing: 1px; background: transparent; padding: 0 6px;"
                )
                break
        self._edit_banner.setStyleSheet(
            f"QFrame {{ background-color: #0D1117; border: 1px solid {color}; border-radius: 8px; }}"
        )
        self._banner_pulse_state = False
        self._banner_color = color
        self._edit_banner.setVisible(True)
        self._banner_pulse_timer.start()

    def _pulse_edit_banner(self):
        """Pulse: alternate between full-opacity and ~half-opacity border at 550ms."""
        from PySide6.QtGui import QColor
        color = getattr(self, "_banner_color", "#388BFD")
        c = QColor(color)
        if self._banner_pulse_state:
            border_css = f"rgba({c.red()},{c.green()},{c.blue()},0.45)"
        else:
            border_css = f"rgba({c.red()},{c.green()},{c.blue()},1.0)"
        self._edit_banner.setStyleSheet(
            f"QFrame {{ background-color: #0D1117; border: 1px solid {border_css}; border-radius: 8px; }}"
        )
        self._banner_pulse_state = not self._banner_pulse_state

    def _cancel_edit(self):
        """Cancel edit — clear editing state and reset the form."""
        self._editing_id = None
        self._banner_pulse_timer.stop()
        self._edit_banner.setVisible(False)
        self.case_id.clear()
        self.doctor.clear()
        self._comments_widget_for_mode(self._mode).clear()
        self.count_toggle.setChecked(True)
        self.end_time.blockSignals(True)
        self.end_time.setTime(QTime(0, 0))
        self.end_time.blockSignals(False)
        self._reset_result_kpi()
        self._capture_mode_state(self._mode)
        self.case_id.setFocus()

    # â"€â"€ Web Import â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

    def _on_import_case(self):
        """
        Read the clipboard, show a confirmation dialog with the detected data,
        and fill the fields only if the user confirms.
        """
        data = get_clipboard_case_data(self.standards)

        module_name = "ot" if self._mode == "overtime" else "regular"

        # Nothing found - show error directly, no dialog
        if not has_detected_case_fields(data):
            self._set_result_status(
                get_import_not_detected_message(module_name),
                "#D29922"
            )
            return

        if not show_import_confirmation(self, data):
            return

        # Extra confirmation popup. Fires when EITHER:
        #   * we're in OT mode (regardless of clock time), OR
        #   * the current time is outside regular hours 05:40 - 15:14
        #     (regardless of mode — likely OT slipped into Regular by mistake).
        # Tailored message based on mode + time so the user knows why they're
        # being warned.
        now = QTime.currentTime()
        in_regular_hours = (
            self._REGULAR_START <= now <= self._REGULAR_END
        )
        if self._mode == "overtime" or not in_regular_hours:
            if not self._confirm_ot_import_time(now, in_regular_hours):
                return

        imported_case_id, imported_region, imported_type = apply_imported_case_data(
            data,
            case_id_widget=self.case_id,
            region_widget=self.region,
            type_widget=self.tipo,
            doctor_widget=self.doctor,
            refresh_case_types_fn=self.update_case_types,
        )

        # Update date to today in case the app has been open since a previous day
        self.case_date.setDate(QDate.currentDate())
        self.start_time.setTime(QTime.currentTime())

        summary = build_import_summary(imported_case_id, imported_region, imported_type)
        success_color = "#F0883E" if self._mode == "overtime" else "#3FB950"
        self._set_result_status(get_import_success_message(summary, module_name), success_color)
        self._capture_mode_state(self._mode)

        self._show_import_toast(
            get_import_reminder_message(),
            duration_ms=4200,
        )

    # Regular working schedule used to flag suspicious imports.
    _REGULAR_START = QTime(5, 40)
    _REGULAR_END   = QTime(15, 14)

    def _confirm_ot_import_time(self, now: QTime, in_regular_hours: bool) -> bool:
        """Confirmation popup for risky imports.

        Returns True if the user confirmed, False to abort. Picks one of
        three messages so the user understands which rule fired:
          1. OT mode + within regular hours  → loudest warning
          2. OT mode + outside regular hours → normal OT confirm
          3. Regular mode + outside regular hours → "should this be OT?"
        """
        is_ot = self._mode == "overtime"
        now_str = now.toString("HH:mm")

        if is_ot and in_regular_hours:
            title = "Importar como OT en horario regular"
            text = (
                f"Hora actual: {now_str}\n\n"
                "Este caso se importará como OT pero la hora actual está\n"
                "dentro del horario regular (05:40 a 15:14).\n\n"
                "¿Seguro desea proseguir?"
            )
        elif is_ot:
            title = "Confirmar importación OT"
            text = (
                f"Hora actual: {now_str}\n\n"
                "El caso se importará como OT (fuera de horario regular).\n\n"
                "¿Seguro desea proseguir?"
            )
        else:
            # Regular mode but outside the regular schedule — likely OT
            title = "Importar como Regular fuera de horario"
            text = (
                f"Hora actual: {now_str}\n\n"
                "Este caso se importará como Regular pero la hora actual\n"
                "está fuera del horario regular (05:40 a 15:14).\n\n"
                "¿Seguro desea proseguir?"
            )

        reply = QMessageBox.question(
            self, title, text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _on_load_db(self):
        """Open a file dialog, pick an old cases.db, merge it into the current DB."""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select old cases.db",
            "",
            "SQLite Database (*.db);;All Files (*)",
        )
        if not path:
            return

        try:
            from db.database import _merge_from
            counts = _merge_from(path)
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", f"Could not import:\n{exc}")
            return

        total = sum(counts.values())
        if total == 0:
            QMessageBox.information(
                self, "Nothing new",
                "No new records found — all rows already exist in the current database.",
            )
        else:
            QMessageBox.information(
                self, "Import complete",
                f"Imported from:\n{path}\n\n"
                f"  • Regular cases:  {counts['cases']}\n"
                f"  • OT cases:       {counts['ot_cases']}\n"
                f"  • Downtimes:      {counts['downtimes']}\n\n"
                f"Total new records: {total}",
            )
        if total > 0:
            self.load_daily_production()
            self._load_regular_day_cases()
            self.case_saved.emit()

    def save_case(self):
        # Auto-set end time to now if the user never changed it from the default 00:00
        if self.end_time.time() == QTime(0, 0):
            self.end_time.blockSignals(True)
            self.end_time.setTime(QTime.currentTime())
            self.end_time.blockSignals(False)

        region = self.region.currentText()
        tipo = self.tipo.currentText()
        case_id = self.case_id.text()
        doctor = self.doctor.text().strip()
        case_date = self.case_date.date().toString("yyyy-MM-dd")

        start = self.start_time.time()
        end = self.end_time.time()

        tiempo_real = start.secsTo(end) / 60
        if tiempo_real <= 0:
            self._set_result_status("Invalid time", "#F85149")
            return

        # Subtract only breaks the user confirmed they took today
        from tabs.breaks_dialog import calculate_break_overlap
        break_mins = calculate_break_overlap(start.toString("HH:mm"), end.toString("HH:mm"), fecha=case_date)
        tiempo_real -= break_mins
        if tiempo_real <= 0:
            self._set_result_status("Case falls entirely within break time", "#F85149")
            return

        if not case_id.strip():
            self._set_result_status("Enter Case ID", "#D29922")
            return

        std_time = self.standards[region]["Aligners"][tipo]
        efficiency = (std_time / tiempo_real) * 100
        estado = "OK" if efficiency >= 100 else "LOW"
        case_value = self.calculate_case_value(std_time)

        conn = get_connection()
        cursor = conn.cursor()

        # Get toggle and comments values
        count_production = 1 if self.count_toggle.isChecked() else 0
        comments = self._comments_widget_for_mode(self._mode).toPlainText().strip()

        # Determine target table based on current mode
        sql_table = "ot_cases" if self._mode == "overtime" else "cases"
        is_ot = self._mode == "overtime"

        # Check if we're editing an existing case
        if self._editing_id:
            cursor.execute(f"""
                UPDATE {sql_table} SET
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
                self._editing_id
            ))
            self._editing_id = None
            self._banner_pulse_timer.stop()
            self._edit_banner.setVisible(False)
            action = "Updated"
        else:
            cursor.execute(f"""
                INSERT INTO {sql_table} (
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
            action = "Saved"

        conn.commit()
        conn.close()

        # Show success in KPI boxes and clear status
        result_color = "#F0883E" if is_ot else "#3FB950"
        self._show_result(efficiency, case_value, result_color)
        summary = f"{case_id} | {region} | {tipo}"
        self._set_result_status(f"{action}: {summary}", result_color)
        self.load_daily_production()

        # Full form reset — leaves a clean slate until the next Import / manual entry.
        self.case_id.clear()
        self.doctor.clear()
        self._comments_widget_for_mode(self._mode).clear()
        self.count_toggle.setChecked(True)  # Reset toggle to ON

        # Reset region / type combos to their first item
        for combo in (self.region, self.tipo):
            combo.blockSignals(True)
            if combo.count() > 0:
                combo.setCurrentIndex(0)
            combo.blockSignals(False)
        # Rebuild the type list to match the freshly-selected region
        self.update_case_types()

        # Date back to today, start time back to current time
        self.case_date.blockSignals(True)
        self.case_date.setDate(QDate.currentDate())
        self.case_date.blockSignals(False)
        self.start_time.blockSignals(True)
        self.start_time.setTime(QTime.currentTime())
        self.start_time.blockSignals(False)

        # Clear end time - set to midnight (00:00)
        self.end_time.blockSignals(True)
        self.end_time.setTime(QTime(0, 0))
        self.end_time.blockSignals(False)

        # Emit signal to notify other tabs
        if is_ot:
            self.ot_saved.emit()
            self._load_ot_day_cases()  # refresh embedded OT view
        else:
            self.case_saved.emit()
            self._load_regular_day_cases()

        self._capture_mode_state(self._mode)

        # Auto-focus Case ID for the next entry
        self.case_id.setFocus()

