from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QTableWidget, QTableWidgetItem,
    QDateEdit, QComboBox, QFileDialog, QMessageBox, QCheckBox
)
from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QFont, QBrush
from db.database import get_connection
import csv

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.chart import BarChart, PieChart, Reference
    from openpyxl.utils.dataframe import dataframe_to_rows
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False


class HistoryTab(QWidget):
    def __init__(self):
        super().__init__()
        self.all_cases = []
        self.filtered_cases = []
        self.current_page = 1
        self.items_per_page = 50
        self.total_pages = 1
        self.init_ui()
        self.load_all_cases()

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(8, 10, 8, 8)
        main_layout.setSpacing(10)

        # Title
        title = QLabel("Case History")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #4aa3ff;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title)

        # First filter row - Search, Status, Date
        filter_row1 = QHBoxLayout()
        filter_row1.addStretch()
        
        filter_row1.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Case ID...")
        self.search_input.setFixedWidth(100)
        self.search_input.textChanged.connect(self.on_filter_changed)
        filter_row1.addWidget(self.search_input)

        filter_row1.addWidget(QLabel("Status:"))
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All", "OK", "LOW"])
        self.status_filter.setFixedWidth(70)
        self.status_filter.currentTextChanged.connect(self.on_filter_changed)
        filter_row1.addWidget(self.status_filter)

        filter_row1.addWidget(QLabel("From:"))
        self.date_from = QDateEdit()
        self.date_from.setDate(QDate.currentDate().addMonths(-1))
        self.date_from.setFixedWidth(110)
        self.date_from.dateChanged.connect(self.on_filter_changed)
        filter_row1.addWidget(self.date_from)
        
        filter_row1.addWidget(QLabel("To:"))
        self.date_to = QDateEdit()
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setFixedWidth(110)
        self.date_to.dateChanged.connect(self.on_filter_changed)
        filter_row1.addWidget(self.date_to)
        
        # Specific date filter - in a separate container for responsive layout
        self.specific_date_label = QLabel("|")
        self.specific_date_label.setStyleSheet("margin-left: 10px; margin-right: 5px; color: #888;")
        
        self.specific_date_check = QCheckBox("Specific:")
        self.specific_date_check.stateChanged.connect(self.on_specific_date_toggled)
        
        self.specific_date = QDateEdit()
        self.specific_date.setDate(QDate.currentDate())
        self.specific_date.setFixedWidth(110)
        self.specific_date.setEnabled(False)
        self.specific_date.dateChanged.connect(self.on_filter_changed)
        
        # Add to filter_row1 initially (will be moved in resizeEvent if needed)
        filter_row1.addWidget(self.specific_date_label)
        filter_row1.addWidget(self.specific_date_check)
        filter_row1.addWidget(self.specific_date)

        filter_row1.addStretch()
        main_layout.addLayout(filter_row1)
        
        # Specific date row (hidden by default, shown in small screens)
        self.specific_row = QHBoxLayout()
        self.specific_row.addStretch()
        self.specific_row.addStretch()
        
        # Create a widget to hold the specific row
        self.specific_row_widget = QWidget()
        self.specific_row_widget.setLayout(self.specific_row)
        self.specific_row_widget.setVisible(False)
        main_layout.addWidget(self.specific_row_widget)
        
        # Track current layout mode
        self.specific_in_row1 = True
        
        # Second filter row - Region, Type, Doctor
        filter_row2 = QHBoxLayout()
        filter_row2.addStretch()
        
        filter_row2.addWidget(QLabel("Region:"))
        self.filter_region = QComboBox()
        self.filter_region.setFixedWidth(100)
        self.filter_region.currentTextChanged.connect(self.on_filter_changed)
        filter_row2.addWidget(self.filter_region)
        
        filter_row2.addWidget(QLabel("Type:"))
        self.filter_type = QComboBox()
        self.filter_type.setFixedWidth(100)
        self.filter_type.currentTextChanged.connect(self.on_filter_changed)
        filter_row2.addWidget(self.filter_type)
        
        filter_row2.addWidget(QLabel("Doctor:"))
        self.filter_doctor = QLineEdit()
        self.filter_doctor.setPlaceholderText("Search...")
        self.filter_doctor.setFixedWidth(100)
        self.filter_doctor.textChanged.connect(self.on_filter_changed)
        filter_row2.addWidget(self.filter_doctor)

        export_btn = QPushButton("Export CSV")
        export_btn.setFixedWidth(100)
        export_btn.clicked.connect(self.export_csv)
        filter_row2.addWidget(export_btn)

        filter_row2.addStretch()
        main_layout.addLayout(filter_row2)

        # Table
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "Case ID", "Doctor", "Region", "Type", "Date", 
            "Time", "Std", "Eff %", "Value %"
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
        
        # Set column widths
        self.table.setColumnWidth(0, 90)   # Case ID
        self.table.setColumnWidth(1, 100)  # Doctor
        self.table.setColumnWidth(2, 80)   # Region
        self.table.setColumnWidth(3, 70)   # Type
        self.table.setColumnWidth(4, 90)   # Date
        self.table.setColumnWidth(5, 50)   # Time
        self.table.setColumnWidth(6, 50)   # Std
        self.table.setColumnWidth(7, 60)   # Eff
        self.table.setColumnWidth(8, 70)   # Value
        
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        
        # Set fixed width for table
        table_width = 90 + 100 + 80 + 70 + 90 + 50 + 50 + 60 + 70 + 20  # columns + padding
        self.table.setFixedWidth(table_width)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setMinimumHeight(200)
        
        # Use container to center table
        table_container = QHBoxLayout()
        table_container.addStretch()
        table_container.addWidget(self.table)
        table_container.addStretch()
        main_layout.addLayout(table_container, 1)

        # Pagination
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

        self.setLayout(main_layout)

    def resizeEvent(self, event):
        """Hide Eff % column when width < 695px and move specific filter to new row at < 825px"""
        super().resizeEvent(event)
        width = event.size().width()
        
        # Column widths: 90+100+80+70+90+50+50+60+70+20 = 680 (full)
        # Without Eff: 90+100+80+70+90+50+50+70+20 = 620
        
        # Column 7 is "Eff %"
        if width < 695:
            self.table.setColumnHidden(7, True)
            self.table.setFixedWidth(620)  # Without Eff column
        else:
            self.table.setColumnHidden(7, False)
            self.table.setFixedWidth(680)  # Full width
        
        # Move specific filter to its own row at < 825px
        if width < 825:
            # Move specific date filter to its own row (without separator)
            if self.specific_in_row1:
                self.specific_date_label.setParent(None)
                self.specific_date_check.setParent(None)
                self.specific_date.setParent(None)
                
                # Insert between stretches in specific_row (no separator)
                self.specific_row.insertWidget(1, self.specific_date_check)
                self.specific_row.insertWidget(2, self.specific_date)
                
                self.specific_date_label.setVisible(False)
                self.specific_row_widget.setVisible(True)
                self.specific_in_row1 = False
        else:
            # Move specific date filter back to row 1
            if not self.specific_in_row1:
                self.specific_date_check.setParent(None)
                self.specific_date.setParent(None)
                
                # Find the filter_row1 layout and insert before the last stretch
                filter_row1 = self.layout().itemAt(1).layout()  # Title is at 0, filter_row1 at 1
                # Insert at positions before the last stretch
                count = filter_row1.count()
                filter_row1.insertWidget(count - 1, self.specific_date_label)
                filter_row1.insertWidget(count, self.specific_date_check)
                filter_row1.insertWidget(count + 1, self.specific_date)
                
                self.specific_date_label.setVisible(True)
                self.specific_row_widget.setVisible(False)
                self.specific_in_row1 = True

    def load_regions_and_types(self):
        """Load unique regions and types for filters"""
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT DISTINCT region FROM cases ORDER BY region")
        regions = [row[0] for row in cursor.fetchall()]
        
        cursor.execute("SELECT DISTINCT tipo_caso FROM cases ORDER BY tipo_caso")
        types = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        
        self.filter_region.clear()
        self.filter_region.addItem("All")
        self.filter_region.addItems(regions)
        
        self.filter_type.clear()
        self.filter_type.addItem("All")
        self.filter_type.addItems(types)

    def load_all_cases(self):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, case_id, doctor, region, tipo_caso,
                   fecha, tiempo_real, std_time, efficiency, estado, case_value
            FROM cases
            ORDER BY id DESC
        """)
        self.all_cases = cursor.fetchall()
        conn.close()
        self.load_regions_and_types()
        self.filter_cases()

    def on_filter_changed(self):
        """Reset to page 1 when filter changes"""
        self.current_page = 1
        self.filter_cases()
    
    def on_specific_date_toggled(self, state):
        """Enable/disable specific date picker and From/To fields"""
        is_specific = state == 2  # Qt.Checked
        self.specific_date.setEnabled(is_specific)
        self.date_from.setEnabled(not is_specific)
        self.date_to.setEnabled(not is_specific)
        self.on_filter_changed()

    def prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.filter_cases()

    def next_page(self):
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.filter_cases()

    def filter_cases(self):
        search_text = self.search_input.text().lower()
        status_filter = self.status_filter.currentText()
        
        # Check if specific date is enabled
        use_specific_date = self.specific_date_check.isChecked()
        if use_specific_date:
            specific = self.specific_date.date().toString("yyyy-MM-dd")
            date_from = specific
            date_to = specific
        else:
            date_from = self.date_from.date().toString("yyyy-MM-dd")
            date_to = self.date_to.date().toString("yyyy-MM-dd")
        
        region_filter = self.filter_region.currentText()
        type_filter = self.filter_type.currentText()
        doctor_filter = self.filter_doctor.text().lower()

        filtered = []
        for case in self.all_cases:
            # case: id, case_id, doctor, region, tipo_caso, fecha, tiempo_real, std_time, efficiency, estado, case_value
            if search_text and search_text not in str(case[1]).lower():
                continue
            if status_filter != "All" and status_filter != case[9]:
                continue
            if case[5] < date_from or case[5] > date_to:
                continue
            if region_filter != "All" and case[3] != region_filter:
                continue
            if type_filter != "All" and case[4] != type_filter:
                continue
            if doctor_filter and doctor_filter not in (case[2] or "").lower():
                continue
            filtered.append(case)

        self.filtered_cases = filtered
        
        # Calculate pagination
        total_items = len(filtered)
        self.total_pages = max(1, (total_items + self.items_per_page - 1) // self.items_per_page)
        
        if self.current_page > self.total_pages:
            self.current_page = self.total_pages
        if self.current_page < 1:
            self.current_page = 1
        
        self.page_label.setText(f"Page {self.current_page} of {self.total_pages}")
        self.btn_prev.setEnabled(self.current_page > 1)
        self.btn_next.setEnabled(self.current_page < self.total_pages)
        
        # Get items for current page
        start_idx = (self.current_page - 1) * self.items_per_page
        end_idx = start_idx + self.items_per_page
        page_items = filtered[start_idx:end_idx]

        self.table.setRowCount(len(page_items))

        for idx, case in enumerate(page_items):
            # Zebra striping
            bg_color = QColor(43, 43, 43) if (idx % 2 == 0) else QColor(55, 55, 55)
            bg_brush = QBrush(bg_color)
            
            # Case ID - Bold
            case_id_item = QTableWidgetItem(str(case[1]))
            case_id_item.setBackground(bg_brush)
            case_id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            bold_font = QFont()
            bold_font.setBold(True)
            case_id_item.setFont(bold_font)
            self.table.setItem(idx, 0, case_id_item)
            
            # Doctor - Bold
            doctor_item = QTableWidgetItem(str(case[2] or "-"))
            doctor_item.setBackground(bg_brush)
            doctor_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            doctor_item.setFont(bold_font)
            self.table.setItem(idx, 1, doctor_item)
            
            # Region
            region_item = QTableWidgetItem(str(case[3]))
            region_item.setBackground(bg_brush)
            region_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(idx, 2, region_item)
            
            # Type
            type_item = QTableWidgetItem(str(case[4]))
            type_item.setBackground(bg_brush)
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(idx, 3, type_item)
            
            # Date
            date_item = QTableWidgetItem(str(case[5]))
            date_item.setBackground(bg_brush)
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(idx, 4, date_item)
            
            # Time - green if OK, show 0 if exceeded
            tiempo_real = case[6]
            estado = case[9]
            if estado == "OK":
                time_item = QTableWidgetItem(f"{tiempo_real:.0f}")
                time_item.setBackground(QBrush(QColor(76, 175, 80)))
                time_item.setForeground(QBrush(QColor(255, 255, 255)))
            else:
                time_item = QTableWidgetItem("0")
                time_item.setBackground(QBrush(QColor(76, 175, 80)))
                time_item.setForeground(QBrush(QColor(255, 255, 255)))
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(idx, 5, time_item)
            
            # Std
            std_item = QTableWidgetItem(f"{case[7]:.1f}")
            std_item.setBackground(bg_brush)
            std_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(idx, 6, std_item)
            
            # Efficiency with color
            efficiency_item = QTableWidgetItem(f"{case[8]:.0f}%")
            efficiency_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if estado == "OK":
                efficiency_item.setBackground(QBrush(QColor(76, 175, 80)))
                efficiency_item.setForeground(QBrush(QColor(255, 255, 255)))
            else:
                efficiency_item.setBackground(QBrush(QColor(244, 67, 54)))
                efficiency_item.setForeground(QBrush(QColor(255, 255, 255)))
            self.table.setItem(idx, 7, efficiency_item)
            
            # Case Value
            value_item = QTableWidgetItem(f"{case[10]:.2f}%")
            value_item.setBackground(bg_brush)
            value_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(idx, 8, value_item)

    def export_csv(self):
        """Export to Excel with charts or CSV as fallback"""
        if OPENPYXL_AVAILABLE:
            self.export_excel()
        else:
            self.export_csv_simple()
    
    def export_excel(self):
        """Export to Excel with formatting and charts"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Report", "", "Excel Files (*.xlsx)"
        )
        if not file_path:
            return
        
        if not file_path.endswith('.xlsx'):
            file_path += '.xlsx'
        
        try:
            wb = Workbook()
            
            # ===== SHEET 1: DATA =====
            ws_data = wb.active
            ws_data.title = "Cases Data"
            
            # Header styles
            header_font = Font(bold=True, color="FFFFFF", size=11)
            header_fill = PatternFill(start_color="4A90D9", end_color="4A90D9", fill_type="solid")
            header_alignment = Alignment(horizontal="center", vertical="center")
            thin_border = Border(
                left=Side(style='thin'),
                right=Side(style='thin'),
                top=Side(style='thin'),
                bottom=Side(style='thin')
            )
            
            # Headers
            headers = ["Case ID", "Doctor", "Region", "Type", "Date", 
                      "Time (min)", "Std (min)", "Efficiency %", "Status", "Case Value %"]
            for col, header in enumerate(headers, 1):
                cell = ws_data.cell(row=1, column=col, value=header)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_alignment
                cell.border = thin_border
            
            # Data rows with conditional formatting
            ok_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
            low_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
            center_align = Alignment(horizontal="center")
            
            for row_idx, case in enumerate(self.filtered_cases, 2):
                # case: id, case_id, doctor, region, tipo_caso, fecha, tiempo_real, std_time, efficiency, estado, case_value
                ws_data.cell(row=row_idx, column=1, value=case[1]).alignment = center_align
                ws_data.cell(row=row_idx, column=2, value=case[2] or "-").alignment = center_align
                ws_data.cell(row=row_idx, column=3, value=case[3]).alignment = center_align
                ws_data.cell(row=row_idx, column=4, value=case[4]).alignment = center_align
                ws_data.cell(row=row_idx, column=5, value=case[5]).alignment = center_align
                ws_data.cell(row=row_idx, column=6, value=round(case[6], 1)).alignment = center_align
                ws_data.cell(row=row_idx, column=7, value=round(case[7], 1)).alignment = center_align
                
                eff_cell = ws_data.cell(row=row_idx, column=8, value=round(case[8], 1))
                eff_cell.alignment = center_align
                
                status_cell = ws_data.cell(row=row_idx, column=9, value=case[9])
                status_cell.alignment = center_align
                
                ws_data.cell(row=row_idx, column=10, value=round(case[10], 2)).alignment = center_align
                
                # Color row based on status
                row_fill = ok_fill if case[9] == "OK" else low_fill
                for col in range(1, 11):
                    ws_data.cell(row=row_idx, column=col).fill = row_fill
                    ws_data.cell(row=row_idx, column=col).border = thin_border
            
            # Auto-adjust column widths
            column_widths = [12, 15, 12, 10, 12, 12, 12, 14, 10, 14]
            for col, width in enumerate(column_widths, 1):
                ws_data.column_dimensions[chr(64 + col)].width = width
            
            # ===== SHEET 2: SUMMARY & CHARTS =====
            ws_charts = wb.create_sheet("Summary & Charts")
            
            # Calculate summary statistics
            total_cases = len(self.filtered_cases)
            ok_cases = sum(1 for c in self.filtered_cases if c[9] == "OK")
            low_cases = total_cases - ok_cases
            avg_efficiency = sum(c[8] for c in self.filtered_cases) / total_cases if total_cases > 0 else 0
            total_value = sum(c[10] for c in self.filtered_cases)
            
            # Summary section
            ws_charts['A1'] = "PRODUCTION SUMMARY REPORT"
            ws_charts['A1'].font = Font(bold=True, size=16, color="4A90D9")
            ws_charts.merge_cells('A1:D1')
            
            summary_data = [
                ("Total Cases:", total_cases),
                ("OK Cases:", ok_cases),
                ("LOW Cases:", low_cases),
                ("OK Rate:", f"{(ok_cases/total_cases*100):.1f}%" if total_cases > 0 else "0%"),
                ("Average Efficiency:", f"{avg_efficiency:.1f}%"),
                ("Total Value:", f"{total_value:.2f}%"),
            ]
            
            for row, (label, value) in enumerate(summary_data, 3):
                ws_charts.cell(row=row, column=1, value=label).font = Font(bold=True)
                ws_charts.cell(row=row, column=2, value=value)
            
            # Production by Region
            region_stats = {}
            for case in self.filtered_cases:
                region = case[3]
                if region not in region_stats:
                    region_stats[region] = {"count": 0, "value": 0, "efficiency": []}
                region_stats[region]["count"] += 1
                region_stats[region]["value"] += case[10]
                region_stats[region]["efficiency"].append(case[8])
            
            # Region table for chart
            ws_charts['A12'] = "Production by Region"
            ws_charts['A12'].font = Font(bold=True, size=12)
            ws_charts['A13'] = "Region"
            ws_charts['B13'] = "Cases"
            ws_charts['C13'] = "Total Value %"
            ws_charts['A13'].font = Font(bold=True)
            ws_charts['B13'].font = Font(bold=True)
            ws_charts['C13'].font = Font(bold=True)
            
            row_num = 14
            for region, stats in sorted(region_stats.items()):
                ws_charts.cell(row=row_num, column=1, value=region)
                ws_charts.cell(row=row_num, column=2, value=stats["count"])
                ws_charts.cell(row=row_num, column=3, value=round(stats["value"], 2))
                row_num += 1
            
            # Bar Chart - Cases by Region
            if len(region_stats) > 0:
                chart1 = BarChart()
                chart1.type = "col"
                chart1.style = 10
                chart1.title = "Cases by Region"
                chart1.y_axis.title = "Cases"
                chart1.x_axis.title = "Region"
                
                data = Reference(ws_charts, min_col=2, min_row=13, max_row=13 + len(region_stats), max_col=2)
                cats = Reference(ws_charts, min_col=1, min_row=14, max_row=13 + len(region_stats))
                chart1.add_data(data, titles_from_data=True)
                chart1.set_categories(cats)
                chart1.shape = 4
                chart1.width = 12
                chart1.height = 8
                ws_charts.add_chart(chart1, "E12")
            
            # Status Pie Chart data
            ws_charts['A' + str(row_num + 2)] = "Status Distribution"
            ws_charts['A' + str(row_num + 2)].font = Font(bold=True, size=12)
            ws_charts['A' + str(row_num + 3)] = "Status"
            ws_charts['B' + str(row_num + 3)] = "Count"
            ws_charts['A' + str(row_num + 3)].font = Font(bold=True)
            ws_charts['B' + str(row_num + 3)].font = Font(bold=True)
            ws_charts['A' + str(row_num + 4)] = "OK"
            ws_charts['B' + str(row_num + 4)] = ok_cases
            ws_charts['A' + str(row_num + 5)] = "LOW"
            ws_charts['B' + str(row_num + 5)] = low_cases
            
            # Pie Chart - Status Distribution
            if total_cases > 0:
                pie = PieChart()
                pie.title = "Status Distribution"
                labels = Reference(ws_charts, min_col=1, min_row=row_num + 4, max_row=row_num + 5)
                data = Reference(ws_charts, min_col=2, min_row=row_num + 3, max_row=row_num + 5)
                pie.add_data(data, titles_from_data=True)
                pie.set_categories(labels)
                pie.width = 10
                pie.height = 8
                ws_charts.add_chart(pie, "E" + str(row_num + 2))
            
            # Save file
            wb.save(file_path)
            QMessageBox.information(self, "Export Successful", 
                f"Report exported to:\n{file_path}\n\nIncludes:\n• Formatted data table\n• Summary statistics\n• Charts by region and status")
            
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Error exporting file:\n{str(e)}")
    
    def export_csv_simple(self):
        """Simple CSV export as fallback"""
        file_path, _ = QFileDialog.getSaveFileName(self, "Export History", "", "CSV Files (*.csv)")
        if file_path:
            try:
                with open(file_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        "Case ID", "Doctor", "Region", "Type",
                        "Date", "Time (min)", "Std (min)", "Efficiency (%)", "Status", "Case Value (%)"
                    ])
                    for case in self.filtered_cases:
                        writer.writerow([
                            case[1], case[2], case[3], case[4],
                            case[5], f"{case[6]:.1f}", f"{case[7]:.1f}", 
                            f"{case[8]:.1f}", case[9], f"{case[10]:.3f}"
                        ])
                QMessageBox.information(self, "Export Successful", f"CSV exported to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Error: {str(e)}")
