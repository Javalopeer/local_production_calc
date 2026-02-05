from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit,
    QPushButton, QDateEdit, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox
)
from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QColor, QFont, QBrush
from db.database import get_connection
from datetime import datetime, timedelta
import json
import os
import sys


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


class ProductionTab(QWidget):
    case_updated = Signal()  # Signal emitted when a case is edited/deleted
    
    def __init__(self):
        super().__init__()
        self.all_cases = []
        self.case_db_ids = {}  # Map table rows to database IDs
        self.current_mode = "reg"  # "reg" for regular cases, "ot" for OT cases
        self.current_page = 1
        self.items_per_page = 50  # Number of cases per page
        self.total_pages = 1
        self.filtered_cases = []  # Store filtered cases for pagination
        self.load_units_eq()
        self.init_ui()
        self.load_regions_and_types()
        self.load_data()
    
    def load_units_eq(self):
        """Load units equivalency for production calculation"""
        units_path = get_resource_path(os.path.join("data", "units_eq.json"))
        with open(units_path, "r") as f:
            self.units_eq = json.load(f)
    
    def calculate_units_eq(self, region, case_value):
        """Calculate equivalent units for a case based on region and value"""
        if region not in self.units_eq or not case_value:
            return 0.0
        units_at_100 = self.units_eq[region].get("100", 0)
        return (case_value / 100) * units_at_100

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
        self.stats_low = QLabel("🟢OK: - | 🔴LOW: -")

        for stat in [self.stats_avg, self.stats_total, self.stats_ok, self.stats_low]:
            stat.setStyleSheet("padding: 6px 12px; border: 1px solid #3c3c3c; border-radius: 4px; background-color: #2b2b2b; font-size: 11px;")
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

        # Add spacing between filters and table
        main_layout.addSpacing(20)

        # Table
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "Case ID", "Doctor", "Region", "Type", "Start", "End", 
            "Time", "Eff %", "Value %", "Und Eq"
        ])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(True)
        self.table.setGridStyle(Qt.PenStyle.SolidLine)
        
        # Style for grid lines
        self.table.setStyleSheet("""
            QTableWidget {
                gridline-color: #5a5a5a;
            }
            QHeaderView::section {
                background-color: #3c3c3c;
                border: 1px solid #5a5a5a;
                padding: 4px;
            }
        """)
        
        # Set column widths - Doctor bigger, Value same as Type
        header = self.table.horizontalHeader()
        self.table.setColumnWidth(0, 85)   # Case ID
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
        
        # Set fixed width for table - reduced to eliminate empty space
        table_width = 95 + 100 + 100 + 70 + 55 + 55 + 40 + 50 + 60 + 50 + 10  # columns + 5px
        self.table.setFixedWidth(table_width)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setMaximumHeight(325)  # 12 rows (~25px each) + header (~25px)
        
        main_layout.addWidget(self.table, alignment=Qt.AlignmentFlag.AlignHCenter)
        
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
        conn = get_connection()
        cursor = conn.cursor()

        if self.current_mode == "reg":
            cursor.execute("""
                SELECT id, case_id, doctor, region, tipo_caso, fecha, hora_inicio, hora_fin, 
                       tiempo_real, efficiency, estado, case_value, count_production
                FROM cases
                ORDER BY fecha DESC, hora_inicio DESC
            """)
        else:  # OT mode
            cursor.execute("""
                SELECT id, case_id, doctor, region, tipo_caso, fecha, hora_inicio, hora_fin, 
                       tiempo_real, efficiency, estado, case_value, count_production
                FROM ot_cases
                ORDER BY fecha DESC, hora_inicio DESC
            """)

        self.all_cases = cursor.fetchall()
        conn.close()
        
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
        
        # Calculate pagination
        total_items = len(filtered)
        self.total_pages = max(1, (total_items + self.items_per_page - 1) // self.items_per_page)
        
        # Ensure current page is valid
        if self.current_page > self.total_pages:
            self.current_page = self.total_pages
        if self.current_page < 1:
            self.current_page = 1
        
        # Update pagination label
        self.page_label.setText(f"Page {self.current_page} of {self.total_pages}")
        
        # Enable/disable pagination buttons
        self.btn_prev.setEnabled(self.current_page > 1)
        self.btn_next.setEnabled(self.current_page < self.total_pages)
        
        # Get items for current page
        start_idx = (self.current_page - 1) * self.items_per_page
        end_idx = start_idx + self.items_per_page
        page_items = filtered[start_idx:end_idx]
        
        # Group by date (only items in current page)
        grouped = {}
        for row in page_items:
            fecha = row[5]  # fecha at index 5
            if fecha not in grouped:
                grouped[fecha] = []
            grouped[fecha].append(row)
        
        # Calculate stats from ALL filtered items (not just current page)
        total_cases = len(filtered)
        ok_count = sum(1 for row in filtered if row[10] == "OK")  # estado at index 10
        low_count = total_cases - ok_count
        total_value = sum(row[11] for row in filtered)  # case_value at index 11
        avg_efficiency = sum(row[9] for row in filtered) / total_cases if total_cases > 0 else 0  # efficiency at index 9

        self.stats_avg.setText(f"Avg Eff: {avg_efficiency:.1f}%")
        self.stats_total.setText(f"Cases: {total_cases}")
        self.stats_ok.setText(f"Value: {total_value:.2f}%")
        self.stats_low.setText(f"🟢OK: {ok_count} | 🔴LOW: {low_count}")
        
        # Count rows needed (dates + cases)
        total_rows = sum(1 + len(cases) for cases in grouped.values())
        self.table.setRowCount(total_rows)
        
        # Clear the row to db_id mapping
        self.case_db_ids = {}
        
        row_idx = 0
        sorted_dates = sorted(grouped.keys(), reverse=True)
        
        for fecha in sorted_dates:
            # Calculate daily total value - case_value at index 11
            daily_value = sum(case[11] for case in grouped[fecha])
            daily_cases = len(grouped[fecha])
            # Calculate daily units equivalent
            daily_units_eq = sum(self.calculate_units_eq(case[3], case[11]) for case in grouped[fecha])
            
            # Date header row with daily total - spaced out text, no icon
            date_item = QTableWidgetItem(f"    {fecha}     {daily_cases} cases     Value: {daily_value:.2f}%     Units: {daily_units_eq:.2f}    ")
            date_item.setBackground(QColor(75, 75, 85))  # Lighter color
            date_item.setForeground(QColor(220, 220, 220))
            font = QFont()
            font.setBold(True)
            date_item.setFont(font)
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            
            self.table.setItem(row_idx, 0, date_item)
            self.table.setRowHeight(row_idx, 32)  # Taller row for date header
            # Fill rest of date row with same background
            for col in range(1, 10):
                empty_item = QTableWidgetItem("")
                empty_item.setBackground(QColor(75, 75, 85))
                self.table.setItem(row_idx, col, empty_item)
            
            self.table.setSpan(row_idx, 0, 1, 10)  # Span across all columns
            row_idx += 1
            
            # Case rows for this date - zebra striping within each date group
            for case_idx, case in enumerate(grouped[fecha]):
                # Store mapping from table row to database id
                self.case_db_ids[row_idx] = case[0]  # id at index 0
                
                # Check if case counts for production (count_production at index 12)
                # Default to 1 if None or not present
                counts_for_production = case[12] if (len(case) > 12 and case[12] is not None) else 1
                
                # Yellow background for cases that don't count (count_production == 0)
                if counts_for_production == 0:
                    bg_color = QColor(180, 150, 50)  # Yellow/gold for non-counting cases
                else:
                    bg_color = QColor(43, 43, 43) if (case_idx % 2 == 0) else QColor(55, 55, 55)
                
                bg_brush = QBrush(bg_color)
                
                # Case ID - Bold (case_id at index 1)
                case_id_item = QTableWidgetItem(str(case[1]))
                case_id_item.setBackground(bg_brush)
                case_id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                bold_font = QFont()
                bold_font.setBold(True)
                case_id_item.setFont(bold_font)
                self.table.setItem(row_idx, 0, case_id_item)
                
                # Doctor - Bold (doctor at index 2)
                doctor_item = QTableWidgetItem(str(case[2] or "-"))
                doctor_item.setBackground(bg_brush)
                doctor_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                doctor_item.setFont(bold_font)
                self.table.setItem(row_idx, 1, doctor_item)
                
                # Other columns - centered (indices shifted)
                other_items = [
                    str(case[3]),           # Region (index 3)
                    str(case[4]),           # Type (index 4)
                    str(case[6]),           # Start (index 6)
                    str(case[7]),           # End (index 7)
                    f"{case[8]:.0f}",       # Time (index 8)
                ]
                
                for col, text in enumerate(other_items, start=2):
                    item = QTableWidgetItem(text)
                    item.setBackground(bg_brush)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(row_idx, col, item)
                
                # Efficiency with color - centered (efficiency at index 9, estado at index 10)
                efficiency_item = QTableWidgetItem(f"{case[9]:.0f}%")
                efficiency_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if case[10] == "OK":
                    efficiency_item.setBackground(QBrush(QColor(76, 175, 80)))
                    efficiency_item.setForeground(QBrush(QColor(255, 255, 255)))
                else:
                    efficiency_item.setBackground(QBrush(QColor(244, 67, 54)))
                    efficiency_item.setForeground(QBrush(QColor(255, 255, 255)))
                self.table.setItem(row_idx, 7, efficiency_item)
                
                # Case Value - no color, same background as other columns
                value_item = QTableWidgetItem(f"{case[11]:.1f}%")
                value_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                value_item.setBackground(QBrush(bg_color))
                self.table.setItem(row_idx, 8, value_item)
                
                # Units Equivalent - calculated from region and case_value
                units_eq = self.calculate_units_eq(case[3], case[11])  # region at index 3, case_value at index 11
                units_eq_item = QTableWidgetItem(f"{units_eq:.2f}")
                units_eq_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                units_eq_item.setBackground(QBrush(bg_color))
                self.table.setItem(row_idx, 9, units_eq_item)
                
                row_idx += 1

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


