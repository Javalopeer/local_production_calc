from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit,
    QPushButton, QDateEdit, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QApplication
)
from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QColor, QFont, QBrush
from . import font_scale
from db.database import get_connection
from datetime import datetime, timedelta
from collections import Counter
from .utils import (
    load_units_eq_data,
    get_units_per_case as _ue_lookup,
    calculate_equivalent_units,
    DAILY_BASE_MINUTES,
)
from .theme_table_utils import (
    apply_table_theme, CLR_FG_LIGHT, CLR_FG_DARK,
    get_light_theme_colors, light_row_bg, light_header_bg, light_header_fg, mix_hex,
)


class ProductionTab(QWidget):
    case_updated = Signal()  # Signal emitted when a case is edited/deleted
    
    def __init__(self):
        super().__init__()
        self.all_cases = []
        self.case_db_ids = {}  # Map table rows to database IDs
        self.current_mode = "reg"  # "reg" for regular cases, "ot" for OT cases
        self.current_page = 1
        self.days_per_page = 2  # Show 2 complete day blocks per page
        self.total_pages = 1
        self.filtered_cases = []  # Store filtered cases for pagination
        # Theme state — main emits themeChanged(is_light) and update_theme_labels
        # writes this. Defaults to False so dark colours are used at boot
        # (the app always starts in dark mode regardless of OS palette).
        self._light_mode_active = False
        self.load_units_eq()
        self.init_ui()
        self.load_regions_and_types()
        self.load_data()
    
    def load_units_eq(self):
        """Load units equivalency for production calculation"""
        self.units_eq = load_units_eq_data()

    def get_units_per_case(self, region, case_type):
        """Return UE value for a specific region+case_type."""
        return _ue_lookup(self.units_eq, region, case_type)

    def calculate_units_eq(self, region, case_value, case_type=None):
        """Return UE for one case supporting both UE models."""
        try:
            return calculate_equivalent_units(
                self.units_eq,
                region,
                case_type,
                case_value,
                count=1,
            )
        except Exception:
            return 0.0

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(8, 10, 8, 8)  # Reduced top margin
        main_layout.setSpacing(10)

        # Title - centered
        title = QLabel("Production & Percentages")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #4aa3ff;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title)

        # Reg/OT buttons row - centered, side by side
        buttons_row = QHBoxLayout()
        buttons_row.addStretch()
        
        # Reg button
        self.btn_reg = QPushButton("Regular")
        self.btn_reg.setFixedSize(85, 35)
        self.btn_reg.setStyleSheet("""
            QPushButton {
                background-color: #4aafff;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
        """)
        self.btn_reg.clicked.connect(self.switch_to_reg)
        buttons_row.addWidget(self.btn_reg)
        
        buttons_row.addSpacing(8)
        
        # OT button
        self.btn_ot = QPushButton("Overtime")
        self.btn_ot.setFixedSize(85, 35)
        self.btn_ot.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c;
                color: white;
                border: 1px solid #5a5a5a;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }
        """)
        self.btn_ot.clicked.connect(self.switch_to_ot)
        buttons_row.addWidget(self.btn_ot)
        
        buttons_row.addStretch()
        main_layout.addLayout(buttons_row)

        # Row 1: Stats - centered
        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        stats_row.addStretch()
        
        self.stats_avg = QLabel("Avg Eff: -")
        self.stats_total = QLabel("Cases: -")
        self.stats_ok = QLabel("Value: -")
        self.stats_low = QLabel("OK: - | LOW: -")

        # Saved dark-mode style for stats so we can restore it on theme change
        stat_dark_style = "padding: 6px 12px; border: 1px solid #3c3c3c; border-radius: 4px; background-color: #2b2b2b; font-size: 11px;"
        for stat in [self.stats_avg, self.stats_total, self.stats_ok, self.stats_low]:
            stat.setStyleSheet(stat_dark_style)
            stat._saved_style = stat_dark_style
            stat.setFixedHeight(28)
            stats_row.addWidget(stat)
        
        stats_row.addStretch()
        main_layout.addLayout(stats_row)

        # Row 2: Date filters - centered
        date_row = QHBoxLayout()
        date_row.setSpacing(12)
        date_row.addStretch()
        
        date_row.addWidget(QLabel("From:"))
        self.date_from = QDateEdit()
        self.date_from.setDate(QDate.currentDate())
        self.date_from.setCalendarPopup(True)
        self.date_from.setFixedWidth(100)
        self.date_from.dateChanged.connect(self.on_filter_changed)
        date_row.addWidget(self.date_from)
        
        date_row.addWidget(QLabel("To:"))
        self.date_to = QDateEdit()
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        self.date_to.setFixedWidth(100)
        self.date_to.dateChanged.connect(self.on_filter_changed)
        date_row.addWidget(self.date_to)
        
        date_row.addStretch()
        main_layout.addLayout(date_row)

        # Row 3: Other filters - centered
        filters_row = QHBoxLayout()
        filters_row.setSpacing(15)
        filters_row.addStretch()
        
        filters_row.addWidget(QLabel("Region:"))
        self.filter_region = QComboBox()
        self.filter_region.setFixedWidth(100)
        self.filter_region.currentTextChanged.connect(self.on_filter_changed)
        filters_row.addWidget(self.filter_region)
        
        filters_row.addWidget(QLabel("Type:"))
        self.filter_type = QComboBox()
        self.filter_type.setFixedWidth(100)
        self.filter_type.currentTextChanged.connect(self.on_filter_changed)
        filters_row.addWidget(self.filter_type)
        
        filters_row.addWidget(QLabel("Doctor:"))
        self.filter_doctor = QLineEdit()
        self.filter_doctor.setPlaceholderText("Search...")
        self.filter_doctor.setFixedWidth(100)
        self.filter_doctor.textChanged.connect(self.on_filter_changed)
        filters_row.addWidget(self.filter_doctor)
        
        filters_row.addStretch()
        main_layout.addLayout(filters_row)

        # Table
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "Case ID", "Doctor", "Region", "Type", "Start", "End", 
            "Time", "Eff %", "Value %", "UE"
        ])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(True)
        self.table.setGridStyle(Qt.PenStyle.SolidLine)
        
        # Style for grid lines (default dark-mode appearance)
        default_table_style = """
            QTableWidget {
                gridline-color: #5a5a5a;
            }
            QHeaderView::section {
                background-color: #3c3c3c;
                border: 1px solid #5a5a5a;
                padding: 4px;
            }
        """
        self.table.setStyleSheet(default_table_style)
        # store default style so we can restore it when switching back to dark
        self.table._saved_style = default_table_style
        
        # Set column widths - Doctor bigger, Value same as Type
        header = self.table.horizontalHeader()
        self.table.setColumnWidth(0, 115)  # Case ID
        self.table.setColumnWidth(1, 100)  # Doctor
        self.table.setColumnWidth(2, 100)  # Region
        self.table.setColumnWidth(3, 70)   # Type
        self.table.setColumnWidth(4, 55)   # Start
        self.table.setColumnWidth(5, 55)   # End
        self.table.setColumnWidth(6, 40)   # Time
        self.table.setColumnWidth(7, 55)   # Eff
        self.table.setColumnWidth(8, 60)   # Value
        self.table.setColumnWidth(9, 50)   # Units Eq
        header.setStretchLastSection(False)

        # Set max width - table shows horizontal scroll if window narrower
        table_width = 115 + 100 + 100 + 70 + 55 + 55 + 40 + 55 + 60 + 50 + 15  # columns + padding
        self.table.setMaximumWidth(table_width)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setMinimumHeight(200)  # Minimum height

        # Use a container to center the table while allowing it to grow
        table_container = QHBoxLayout()
        table_container.addStretch()
        table_container.addWidget(self.table)
        table_container.addStretch()
        main_layout.addLayout(table_container, 1)  # Stretch factor 1 to fill space
        
        # Edit/Delete buttons
        action_buttons_layout = QHBoxLayout()
        action_buttons_layout.addStretch()
        
        self.edit_btn = QPushButton("Edit")
        self.edit_btn.setMaximumWidth(100)
        self.edit_btn.setMinimumHeight(26)
        self.edit_btn.clicked.connect(self.edit_selected_case)
        
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setMaximumWidth(100)
        self.delete_btn.setMinimumHeight(26)
        self.delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #F44336;
            }
            QPushButton:hover {
                background-color: #D32F2F;
            }
        """)
        self.delete_btn.clicked.connect(self.delete_selected_case)
        
        action_buttons_layout.addWidget(self.edit_btn)
        action_buttons_layout.addWidget(self.delete_btn)
        action_buttons_layout.addStretch()
        main_layout.addLayout(action_buttons_layout)
        
        # Pagination controls
        pagination_layout = QHBoxLayout()
        pagination_layout.addStretch()
        
        self.btn_prev = QPushButton("◀ Prev")
        self.btn_prev.setFixedSize(70, 26)
        self.btn_prev.clicked.connect(self.prev_page)
        pagination_layout.addWidget(self.btn_prev)
        
        self.page_label = QLabel("Page 1 of 1")
        self.page_label.setStyleSheet("padding: 0 15px; font-size: 11px;")
        pagination_layout.addWidget(self.page_label)
        
        self.btn_next = QPushButton("Next ▶")
        self.btn_next.setFixedSize(70, 26)
        self.btn_next.clicked.connect(self.next_page)
        pagination_layout.addWidget(self.btn_next)
        
        pagination_layout.addStretch()
        main_layout.addLayout(pagination_layout)
        
        # Add bottom spacing to match top
        main_layout.addSpacing(10)

        self.setLayout(main_layout)

    def resizeEvent(self, event):
        """Hide Eff % column when width < 725px and adjust table width"""
        super().resizeEvent(event)
        width = event.size().width()

        # Column widths: 115+100+100+70+55+55+40+55+60+50+15 = 715 (full)
        # Without Eff: 115+100+100+70+55+55+40+60+50+15 = 660

        # Column 7 is "Eff %"
        if width < 725:
            self.table.setColumnHidden(7, True)
            self.table.setFixedWidth(660)  # Without Eff column
        else:
            self.table.setColumnHidden(7, False)
            self.table.setFixedWidth(715)  # Full width

    def load_regions_and_types(self):
        """Load unique regions and types for filters based on current mode"""
        conn = get_connection()
        cursor = conn.cursor()
        
        table_name = "cases" if self.current_mode == "reg" else "ot_cases"
        
        cursor.execute(f"SELECT DISTINCT region FROM {table_name} ORDER BY region")
        regions = [row[0] for row in cursor.fetchall()]
        
        cursor.execute(f"SELECT DISTINCT tipo_caso FROM {table_name} ORDER BY tipo_caso")
        types = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        
        self.filter_region.clear()
        self.filter_region.addItem("All")
        self.filter_region.addItems(regions)
        
        self.filter_type.clear()
        self.filter_type.addItem("All")
        self.filter_type.addItems(types)

    def switch_to_reg(self):
        """Switch to Regular production cases"""
        self.current_mode = "reg"
        self.btn_reg.setStyleSheet("""
            QPushButton {
                background-color: #4aa3ff;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
        """)
        self.btn_ot.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c;
                color: white;
                border: 1px solid #5a5a5a;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }
        """)
        self.load_data()

    def switch_to_ot(self):
        """Switch to OT cases"""
        self.current_mode = "ot"
        self.btn_ot.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
        """)
        self.btn_reg.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c;
                color: white;
                border: 1px solid #5a5a5a;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }
        """)
        self.load_data()

    def load_data(self):
        try:
            conn = get_connection()
            cursor = conn.cursor()

            if self.current_mode == "reg":
                cursor.execute("""
                    SELECT id, case_id, doctor, region, tipo_caso, fecha, hora_inicio, hora_fin,
                           tiempo_real, efficiency, estado, case_value, count_production, comments
                    FROM cases
                    ORDER BY id DESC
                """)
            else:  # OT mode
                cursor.execute("""
                    SELECT id, case_id, doctor, region, tipo_caso, fecha, hora_inicio, hora_fin,
                           tiempo_real, efficiency, estado, case_value, count_production, comments
                    FROM ot_cases
                    ORDER BY id DESC
                """)

            self.all_cases = cursor.fetchall()
            conn.close()
        except Exception as exc:
            # DB momentarily locked — keep last successful snapshot, do not wipe the table
            print(f"[ProductionTab] load_data failed: {exc}")
            return

        self.load_regions_and_types()
        self.filter_data()

    def filter_data(self):
        date_from = self.date_from.date().toString("yyyy-MM-dd")
        date_to = self.date_to.date().toString("yyyy-MM-dd")
        region_filter = self.filter_region.currentText()
        type_filter = self.filter_type.currentText()
        doctor_filter = self.filter_doctor.text().lower()
        
        # Filter cases - indices shifted by 1 due to id field at index 0
        filtered = []
        for row in self.all_cases:
            fecha = row[5]  # fecha is now at index 5
            if fecha < date_from or fecha > date_to:
                continue
            if region_filter != "All" and row[3] != region_filter:  # region at index 3
                continue
            if type_filter != "All" and row[4] != type_filter:  # tipo at index 4
                continue
            if doctor_filter and doctor_filter not in (row[2] or "").lower():  # doctor at index 2
                continue
            filtered.append(row)
        
        # Store filtered cases for pagination
        self.filtered_cases = filtered

        # Group ALL filtered cases by date first, then paginate by date blocks
        all_grouped = {}
        for row in filtered:
            fecha = row[5]
            if fecha not in all_grouped:
                all_grouped[fecha] = []
            all_grouped[fecha].append(row)

        self._all_dates_sorted = sorted(all_grouped.keys(), reverse=True)
        total_dates = len(self._all_dates_sorted)
        self.total_pages = max(1, (total_dates + self.days_per_page - 1) // self.days_per_page)

        if self.current_page > self.total_pages:
            self.current_page = self.total_pages
        if self.current_page < 1:
            self.current_page = 1

        self.page_label.setText(f"Page {self.current_page} of {self.total_pages}")
        self.btn_prev.setEnabled(self.current_page > 1)
        self.btn_next.setEnabled(self.current_page < self.total_pages)

        # Get dates for current page
        date_start = (self.current_page - 1) * self.days_per_page
        date_end = date_start + self.days_per_page
        page_dates = self._all_dates_sorted[date_start:date_end]

        # Build grouped dict for only the current page's dates
        grouped = {d: all_grouped[d] for d in page_dates}
        
        # Calculate stats from ALL filtered items (not just current page)
        # Only include cases where count_production != 0
        prod_filtered = [r for r in filtered if (r[12] if (len(r) > 12 and r[12] is not None) else 1) != 0]
        total_cases = len(prod_filtered)
        ok_count = sum(1 for row in prod_filtered if row[10] == "OK")  # estado at index 10
        low_count = total_cases - ok_count
        total_value = sum(row[11] for row in prod_filtered)  # case_value at index 11
        avg_efficiency = sum(row[9] for row in prod_filtered) / total_cases if total_cases > 0 else 0  # efficiency at index 9

        self.stats_avg.setText(f"Avg Eff: {avg_efficiency:,.1f}%")
        self.stats_total.setText(f"Cases: {total_cases:,}")
        self.stats_ok.setText(f"Value: {total_value:,.2f}%")
        self.stats_low.setText(f"OK: {ok_count:,} | LOW: {low_count:,}")
        
        # Theme detection — read the value pushed by update_theme_labels
        # (which is wired to main's themeChanged signal). The previous
        # palette-based check was unreliable because QApplication.setStyleSheet
        # does NOT change the palette; on machines where the OS theme is
        # light, palette.lightness() returned light even when the app was
        # in dark mode, so foreground colours collapsed to dark-on-dark.
        current_is_light = bool(getattr(self, "_light_mode_active", False))
        light_colors = get_light_theme_colors()

        sorted_dates = sorted(grouped.keys(), reverse=True)

        # Pre-fetch downtime for all page dates in one query
        _dt_map = {}
        if sorted_dates:
            conn_dt = get_connection()
            try:
                cur_dt = conn_dt.cursor()
                placeholders = ",".join("?" for _ in sorted_dates)
                cur_dt.execute(
                    f"SELECT fecha, SUM(duracion) FROM downtimes "
                    f"WHERE fecha IN ({placeholders}) AND (status = 'approved' OR status IS NULL) "
                    f"GROUP BY fecha",
                    sorted_dates,
                )
                _dt_map = {r[0]: r[1] for r in cur_dt.fetchall()}
            finally:
                conn_dt.close()

        # Count rows needed (date header row + type-breakdown row + cases)
        total_rows = 0
        for f, cases in grouped.items():
            total_rows += 2 + len(cases)

        # Reset any previous row spans/content before drawing current page.
        self.table.clearSpans()
        self.table.clearContents()
        self.table.setRowCount(total_rows)

        # Clear the row to db_id mapping
        self.case_db_ids = {}
        row_idx = 0

        for fecha in sorted_dates:
            # Calculate daily totals - only include cases that count to production
            prod_cases = [c for c in grouped[fecha] if (c[12] if (len(c) > 12 and c[12] is not None) else 1) != 0]
            daily_value = sum(case[11] for case in prod_cases)
            daily_cases = len(prod_cases)
            daily_units_eq = sum(self.calculate_units_eq(case[3], case[11], case[4]) for case in prod_cases)
            daily_time_sum = sum((case[8] or 0) for case in prod_cases)

            # Add downtime credit (production % only — UE no longer includes downtime)
            dt_mins = _dt_map.get(fecha, 0) or 0
            dt_value = (dt_mins / DAILY_BASE_MINUTES) * 100 if dt_mins > 0 else 0

            total_value_day = daily_value + dt_value

            # Theme colors for header rows
            if current_is_light:
                date_bg = QColor(light_header_bg(light_colors))
                date_fg = QColor(light_header_fg(light_colors))
            else:
                date_bg = QColor(75, 75, 85)
                date_fg = QColor(220, 220, 220)
            header_font = QFont()
            header_font.setBold(True)

            # ── Row 1: Date, cases, value, units, time ──
            if dt_mins > 0:
                line1 = (
                    f"    {fecha}     {daily_cases} cases     "
                    f"Value: {total_value_day:.2f}% (Cases: {daily_value:.2f}% + DT: {dt_value:.2f}%)     "
                    f"Units: {daily_units_eq:.2f}     Time: {daily_time_sum:.0f}m    "
                )
            else:
                line1 = (
                    f"    {fecha}     {daily_cases} cases     "
                    f"Value: {daily_value:.2f}%     Units: {daily_units_eq:.2f}     Time: {daily_time_sum:.0f}m    "
                )

            date_item = QTableWidgetItem(line1)
            date_item.setBackground(date_bg)
            date_item.setForeground(date_fg)
            date_item.setFont(header_font)
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row_idx, 0, date_item)
            self.table.setRowHeight(row_idx, 32)
            for col in range(1, 10):
                ei = QTableWidgetItem("")
                ei.setBackground(date_bg)
                ei.setForeground(date_fg)
                self.table.setItem(row_idx, col, ei)
            self.table.setSpan(row_idx, 0, 1, 10)
            row_idx += 1

            # ── Type-breakdown sub-row ─────────────────────────────────
            type_counts = Counter(case[4] or "Unknown" for case in prod_cases)
            breakdown_parts = [f"{t}: {c}" for t, c in sorted(type_counts.items())]
            breakdown_text = "    " + "   │   ".join(breakdown_parts) + "    "
            breakdown_item = QTableWidgetItem(breakdown_text)
            if current_is_light:
                sub_bg = QColor(mix_hex(light_colors["surface_bg"], light_colors["selection_bg"], 0.70))
                sub_fg = QColor(light_colors["text_muted"])
            else:
                sub_bg = QColor(55, 55, 68)
                sub_fg = QColor(180, 195, 210)
            breakdown_item.setBackground(sub_bg)
            breakdown_item.setForeground(sub_fg)
            sub_font = QFont()
            sub_font.setPointSize(font_scale.scale_pt(8))
            breakdown_item.setFont(sub_font)
            breakdown_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row_idx, 0, breakdown_item)
            self.table.setRowHeight(row_idx, 22)
            for col in range(1, 10):
                ei = QTableWidgetItem("")
                ei.setBackground(sub_bg)
                self.table.setItem(row_idx, col, ei)
            self.table.setSpan(row_idx, 0, 1, 10)
            row_idx += 1

            # Case rows for this date - zebra striping within each date group
            for case_idx, case in enumerate(grouped[fecha]):
                # Store mapping from table row to database id
                self.case_db_ids[row_idx] = case[0]  # id at index 0
                
                # Check if case counts for production (count_production at index 12)
                # Default to 1 if None or not present
                counts_for_production = case[12] if (len(case) > 12 and case[12] is not None) else 1

                if current_is_light:
                    bg_color = light_row_bg(case_idx, light_colors)
                else:
                    bg_color = QColor(43, 43, 43) if (case_idx % 2 == 0) else QColor(55, 55, 55)

                bg_brush = QBrush(bg_color)

                # Case ID - Bold (case_id at index 1)
                # Determine text color for row based on theme; dim grey for non-counting cases
                if counts_for_production == 0:
                    text_color = QColor("#A15C00") if current_is_light else QColor("#F0883E")
                else:
                    text_color = CLR_FG_DARK if current_is_light else CLR_FG_LIGHT

                comment = (case[13] if len(case) > 13 else "") or ""
                case_id_text = f"{case[1]} \U0001F4AC" if comment.strip() else str(case[1])
                if counts_for_production == 0:
                    case_id_text = f"{case_id_text} (NC)"
                case_id_item = QTableWidgetItem(case_id_text)
                case_id_item.setBackground(bg_brush)
                case_id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                bold_font = QFont()
                bold_font.setBold(True)
                if counts_for_production == 0:
                    bold_font.setItalic(True)
                case_id_item.setFont(bold_font)
                case_id_item.setForeground(QBrush(text_color))
                if comment.strip():
                    case_id_item.setToolTip(comment.strip())
                self.table.setItem(row_idx, 0, case_id_item)
                
                # Doctor - Bold (doctor at index 2)
                doctor_item = QTableWidgetItem(str(case[2] or "-"))
                doctor_item.setBackground(bg_brush)
                doctor_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                doctor_item.setFont(bold_font)
                doctor_item.setForeground(QBrush(text_color))
                self.table.setItem(row_idx, 1, doctor_item)
                
                # Other columns - centered (indices shifted)
                # Get std_time for comparison (need to load from standards)
                tiempo_real = case[8]  # Time at index 8
                
                other_items = [
                    str(case[3]),           # Region (index 3)
                    str(case[4]),           # Type (index 4)
                    str(case[6]),           # Start (index 6)
                    str(case[7]),           # End (index 7)
                ]
                
                for col, text in enumerate(other_items, start=2):
                    item = QTableWidgetItem(text)
                    item.setBackground(bg_brush)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setForeground(QBrush(text_color))
                    self.table.setItem(row_idx, col, item)
                
                # Time column - show actual minutes; color by estado
                time_item = QTableWidgetItem(f"{tiempo_real:.0f}")
                if case[10] == "OK":  # estado at index 10
                    time_item.setBackground(QBrush(QColor(76, 175, 80)))  # Green
                else:
                    time_item.setBackground(QBrush(QColor(244, 67, 54)))  # Red
                # time badge text should be white for contrast
                time_item.setForeground(QBrush(CLR_FG_LIGHT))
                time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row_idx, 6, time_item)
                
                # Efficiency with color - centered (efficiency at index 9, estado at index 10)
                # Efficiency: use numeric thresholds like OT tab (>=100 green, >=95 amber, else red)
                try:
                    eff_val = float(case[9])
                except Exception:
                    eff_val = None

                efficiency_item = QTableWidgetItem(f"{case[9]:.0f}%")
                efficiency_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if eff_val is not None:
                    if eff_val >= 100:
                        efficiency_item.setBackground(QBrush(QColor(76, 175, 80)))
                    elif eff_val >= 95:
                        efficiency_item.setBackground(QBrush(QColor(255, 193, 7)))
                    else:
                        efficiency_item.setBackground(QBrush(QColor(244, 67, 54)))
                    eff_text_color = CLR_FG_DARK if current_is_light else CLR_FG_LIGHT
                    efficiency_item.setForeground(QBrush(eff_text_color))
                else:
                    # fallback to estado-based coloring
                    if case[10] == "OK":
                        efficiency_item.setBackground(QBrush(QColor(76, 175, 80)))
                    else:
                        efficiency_item.setBackground(QBrush(QColor(244, 67, 54)))
                    efficiency_item.setForeground(QBrush(CLR_FG_LIGHT))
                self.table.setItem(row_idx, 7, efficiency_item)
                
                # Case Value - no color, same background as other columns
                value_item = QTableWidgetItem(f"{case[11]:.1f}%")
                value_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                value_item.setBackground(QBrush(bg_color))
                value_item.setForeground(QBrush(text_color))
                self.table.setItem(row_idx, 8, value_item)
                
                # Units Equivalent - calculated from region and case_value
                units_eq = self.calculate_units_eq(case[3], case[11], case[4])  # region, case_value, tipo_caso
                units_eq_item = QTableWidgetItem(f"{units_eq:.2f}")
                units_eq_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                units_eq_item.setBackground(QBrush(bg_color))
                units_eq_item.setForeground(QBrush(text_color))
                self.table.setItem(row_idx, 9, units_eq_item)
                
                row_idx += 1

        # Tooltip pass: show full content on hover for truncated cells.
        for r in range(self.table.rowCount()):
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                if not item:
                    continue
                text = item.text() or ""
                if text and not item.toolTip():
                    item.setToolTip(text)

    def edit_selected_case(self):
        """Emit signal to edit selected case - handled by main window"""
        selected_row = self.table.currentRow()
        if selected_row not in self.case_db_ids:
            return  # Date header row or invalid
        
        db_id = self.case_db_ids[selected_row]
        # Store the ID and mode for RegisterTab/OT tab to pick up
        self.editing_case_id = db_id
        self.editing_mode = self.current_mode  # "reg" or "ot"
        self.case_updated.emit()

    def delete_selected_case(self):
        """Delete selected case from database"""
        selected_row = self.table.currentRow()
        if selected_row not in self.case_db_ids:
            return  # Date header row or invalid
        
        db_id = self.case_db_ids[selected_row]
        case_id_text = self.table.item(selected_row, 0).text()
        
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete case '{case_id_text}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            conn = get_connection()
            cursor = conn.cursor()
            table_name = "cases" if self.current_mode == "reg" else "ot_cases"
            cursor.execute(f"DELETE FROM {table_name} WHERE id = ?", (db_id,))
            conn.commit()
            conn.close()
            
            self.load_data()
            self.case_updated.emit()

    def prev_page(self):
        """Go to previous page"""
        if self.current_page > 1:
            self.current_page -= 1
            self.filter_data()
    
    def next_page(self):
        """Go to next page"""
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.filter_data()
    
    def reset_to_first_page(self):
        """Reset to first page when filters change"""
        self.current_page = 1
    
    def on_filter_changed(self):
        """Called when any filter changes - reset to first page and filter"""
        self.current_page = 1
        self.filter_data()

    def update_font_sizes(self, _new_size: int = 0):
        """Re-render the table so QFont calls inside filter_data pick up the
        new global scale."""
        try:
            self.filter_data()
        except Exception:
            pass

    def update_theme_labels(self, is_light: bool):
        """Adjust widgets when theme changes.

        - In light mode: use user-configured light palette for table, buttons and stats.
        - In dark mode: restore the previous dark styles.
        """
        # Remember the active theme so filter_data() picks the right
        # foreground/background palette every time it re-renders rows.
        self._light_mode_active = bool(is_light)
        colors = get_light_theme_colors()
        # Foreground color for table items: dark text on light theme, white on dark
        fg_color = QColor(colors["text_primary"]) if is_light else CLR_FG_LIGHT

        # Title color: use dark primary text in light mode, original blue in dark
        try:
            for lbl in self.findChildren(QLabel):
                if lbl.text().strip() == "Production & Percentages":
                    if is_light:
                        lbl.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {colors['text_primary']};")
                    else:
                        lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #4aa3ff;")
                    break
        except Exception:
            pass

        # Light-mode stylesheet to match Downtime visuals
        light_bg_css = (
            f' QTableWidget {{ background-color: {colors["surface_bg"]}; gridline-color: {colors["border"]}; border: 1px solid {colors["border"]}; }} '
            f' QHeaderView::section {{ background-color: {light_header_bg(colors)}; color: {light_header_fg(colors)}; border: 1px solid {colors["border"]}; padding: 6px; }} '
        )

        apply_table_theme(
            self,
            is_light,
            light_append_css=light_bg_css,
            adaptive_fg_by_bg=True,
            adaptive_default_fg=fg_color,
        )

        # Re-render rows so each cell picks up the new theme's text colour
        # (apply_table_theme alone updates existing items but our render
        # also paints status-driven badges; safer to repopulate).
        try:
            self.filter_data()
        except Exception:
            pass

        # Adjust Regular / OT button colors to match light theme preferences
        try:
            if is_light:
                if self.current_mode == 'reg':
                    self.btn_reg.setStyleSheet("""
                        QPushButton { background-color: """ + colors["accent"] + """; color: white; border: none; border-radius: 4px; font-weight: bold; }
                    """)
                    self.btn_ot.setStyleSheet(
                        f"QPushButton {{ background-color: {colors['button_bg']}; color: {colors['text_primary']}; "
                        f"border: 1px solid {colors['border']}; border-radius: 4px; font-weight: bold; }}"
                    )
                else:
                    self.btn_ot.setStyleSheet("""
                        QPushButton { background-color: #FF9800; color: white; border: none; border-radius: 4px; font-weight: bold; }
                    """)
                    self.btn_reg.setStyleSheet(
                        f"QPushButton {{ background-color: {colors['button_bg']}; color: {colors['text_primary']}; "
                        f"border: 1px solid {colors['border']}; border-radius: 4px; font-weight: bold; }}"
                    )

                stat_light_style = (
                    f'padding: 6px 12px; border: 1px solid {colors["border"]}; '
                    f'border-radius: 4px; background-color: {colors["surface_bg"]}; color: {colors["text_primary"]}; font-size: 11px;'
                )
                for stat in [self.stats_avg, self.stats_total, self.stats_ok, self.stats_low]:
                    try:
                        stat.setStyleSheet(stat_light_style)
                    except Exception:
                        pass
            else:
                # Dark-mode: restore previously saved styles for stats and buttons
                for stat in [self.stats_avg, self.stats_total, self.stats_ok, self.stats_low]:
                    try:
                        base = getattr(stat, '_saved_style', '')
                        if base:
                            stat.setStyleSheet(base)
                    except Exception:
                        pass

                # Restore regular/ot button styles according to mode
                if self.current_mode == 'reg':
                    self.btn_reg.setStyleSheet("""
                        QPushButton { background-color: #4aa3ff; color: white; border: none; border-radius: 4px; font-weight: bold; }
                    """)
                    self.btn_ot.setStyleSheet("""
                        QPushButton { background-color: #3c3c3c; color: white; border: 1px solid #5a5a5a; border-radius: 4px; font-weight: bold; }
                        QPushButton:hover { background-color: #4a4a4a; }
                    """)
                else:
                    self.btn_ot.setStyleSheet("""
                        QPushButton { background-color: #FF9800; color: white; border: none; border-radius: 4px; font-weight: bold; }
                    """)
                    self.btn_reg.setStyleSheet("""
                        QPushButton { background-color: #3c3c3c; color: white; border: 1px solid #5a5a5a; border-radius: 4px; font-weight: bold; }
                        QPushButton:hover { background-color: #4a4a4a; }
                    """)
        except Exception:
            pass


