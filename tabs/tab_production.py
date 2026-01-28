from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit,
    QPushButton, QDateEdit, QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QFont, QBrush
from db.database import get_connection
from datetime import datetime, timedelta

class ProductionTab(QWidget):
    def __init__(self):
        super().__init__()
        self.all_cases = []
        self.init_ui()
        self.load_regions_and_types()
        self.load_data()

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(14)

        # Title - centered
        title = QLabel("Production & Percentages")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #4aa3ff;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title)

        # Row 1: Stats - centered
        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        stats_row.addStretch()
        
        self.stats_avg = QLabel("Avg Eff: -")
        self.stats_total = QLabel("Cases: -")
        self.stats_ok = QLabel("Value: -")
        self.stats_low = QLabel("🟢 - | 🔴 -")

        for stat in [self.stats_avg, self.stats_total, self.stats_ok, self.stats_low]:
            stat.setStyleSheet("padding: 6px 14px; border: 1px solid #3c3c3c; border-radius: 5px; background-color: #2b2b2b; font-size: 11px;")
            stats_row.addWidget(stat)
        
        stats_row.addStretch()
        main_layout.addLayout(stats_row)

        # Row 2: Date filters - centered
        date_row = QHBoxLayout()
        date_row.setSpacing(15)
        date_row.addStretch()
        
        date_row.addWidget(QLabel("From:"))
        self.date_from = QDateEdit()
        self.date_from.setDate(QDate.currentDate())
        self.date_from.setCalendarPopup(True)
        self.date_from.setFixedWidth(100)
        self.date_from.dateChanged.connect(self.filter_data)
        date_row.addWidget(self.date_from)
        
        date_row.addWidget(QLabel("To:"))
        self.date_to = QDateEdit()
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        self.date_to.setFixedWidth(100)
        self.date_to.dateChanged.connect(self.filter_data)
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
        self.filter_region.currentTextChanged.connect(self.filter_data)
        filters_row.addWidget(self.filter_region)
        
        filters_row.addWidget(QLabel("Type:"))
        self.filter_type = QComboBox()
        self.filter_type.setFixedWidth(100)
        self.filter_type.currentTextChanged.connect(self.filter_data)
        filters_row.addWidget(self.filter_type)
        
        filters_row.addWidget(QLabel("Doctor:"))
        self.filter_doctor = QLineEdit()
        self.filter_doctor.setPlaceholderText("Search...")
        self.filter_doctor.setFixedWidth(100)
        self.filter_doctor.textChanged.connect(self.filter_data)
        filters_row.addWidget(self.filter_doctor)
        
        filters_row.addStretch()
        main_layout.addLayout(filters_row)

        # Table
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "Case ID", "Doctor", "Region", "Type", "Start", "End", 
            "Time", "Eff %", "Value %"
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
        self.table.setColumnWidth(0, 95)   # Case ID
        self.table.setColumnWidth(1, 130)  # Doctor
        self.table.setColumnWidth(2, 130)  # Region
        self.table.setColumnWidth(3, 90)   # Type
        self.table.setColumnWidth(4, 50)   # Start
        self.table.setColumnWidth(5, 50)   # End
        self.table.setColumnWidth(6, 45)   # Time
        self.table.setColumnWidth(7, 55)   # Eff
        self.table.setColumnWidth(8, 70)   # Value
        header.setStretchLastSection(False)
        
        # Set fixed width for table - reduced to eliminate empty space
        table_width = 95 + 130 + 130 + 90 + 50 + 50 + 45 + 55 + 70 + 2  # columns only
        self.table.setFixedWidth(table_width)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        main_layout.addWidget(self.table, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.setLayout(main_layout)

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

    def load_data(self):
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT case_id, doctor, region, tipo_caso, fecha, hora_inicio, hora_fin, 
                   tiempo_real, efficiency, estado, case_value
            FROM cases
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
        
        # Filter cases
        filtered = []
        for row in self.all_cases:
            fecha = row[4]
            if fecha < date_from or fecha > date_to:
                continue
            if region_filter != "All" and row[2] != region_filter:
                continue
            if type_filter != "All" and row[3] != type_filter:
                continue
            if doctor_filter and doctor_filter not in (row[1] or "").lower():
                continue
            filtered.append(row)
        
        # Group by date
        grouped = {}
        for row in filtered:
            fecha = row[4]
            if fecha not in grouped:
                grouped[fecha] = []
            grouped[fecha].append(row)
        
        # Calculate stats
        total_cases = len(filtered)
        ok_count = sum(1 for row in filtered if row[9] == "OK")
        low_count = total_cases - ok_count
        total_value = sum(row[10] for row in filtered)
        avg_efficiency = sum(row[8] for row in filtered) / total_cases if total_cases > 0 else 0

        self.stats_avg.setText(f"Avg Eff: {avg_efficiency:.1f}%")
        self.stats_total.setText(f"Cases: {total_cases}")
        self.stats_ok.setText(f"Value: {total_value:.2f}%")
        self.stats_low.setText(f"🟢 {ok_count} | 🔴 {low_count}")
        
        # Count rows needed (dates + cases)
        total_rows = sum(1 + len(cases) for cases in grouped.values())
        self.table.setRowCount(total_rows)
        
        row_idx = 0
        sorted_dates = sorted(grouped.keys(), reverse=True)
        
        for fecha in sorted_dates:
            # Calculate daily total value
            daily_value = sum(case[10] for case in grouped[fecha])
            daily_cases = len(grouped[fecha])
            
            # Date header row with daily total - spaced out text, no icon
            date_item = QTableWidgetItem(f"    {fecha}          {daily_cases} cases          Value: {daily_value:.2f}%    ")
            date_item.setBackground(QColor(75, 75, 85))  # Lighter color
            date_item.setForeground(QColor(220, 220, 220))
            font = QFont()
            font.setBold(True)
            date_item.setFont(font)
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            
            self.table.setItem(row_idx, 0, date_item)
            self.table.setRowHeight(row_idx, 32)  # Taller row for date header
            # Fill rest of date row with same background
            for col in range(1, 9):
                empty_item = QTableWidgetItem("")
                empty_item.setBackground(QColor(75, 75, 85))
                self.table.setItem(row_idx, col, empty_item)
            
            self.table.setSpan(row_idx, 0, 1, 9)  # Span across all columns
            row_idx += 1
            
            # Case rows for this date - zebra striping within each date group
            for case_idx, case in enumerate(grouped[fecha]):
                # Alternate row colors based on case index within the date group
                bg_color = QColor(43, 43, 43) if (case_idx % 2 == 0) else QColor(55, 55, 55)
                
                # Case ID - Bold
                case_id_item = QTableWidgetItem(str(case[0]))
                case_id_item.setBackground(bg_color)
                case_id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                bold_font = QFont()
                bold_font.setBold(True)
                case_id_item.setFont(bold_font)
                self.table.setItem(row_idx, 0, case_id_item)
                
                # Doctor - Bold
                doctor_item = QTableWidgetItem(str(case[1] or "-"))
                doctor_item.setBackground(bg_color)
                doctor_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                doctor_item.setFont(bold_font)
                self.table.setItem(row_idx, 1, doctor_item)
                
                # Other columns - centered
                other_items = [
                    str(case[2]),           # Region
                    str(case[3]),           # Type
                    str(case[5]),           # Start
                    str(case[6]),           # End
                    f"{case[7]:.0f}",       # Time
                ]
                
                for col, text in enumerate(other_items, start=2):
                    item = QTableWidgetItem(text)
                    item.setBackground(bg_color)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(row_idx, col, item)
                
                # Efficiency with color - centered
                efficiency_item = QTableWidgetItem(f"{case[8]:.0f}%")
                efficiency_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if case[9] == "OK":
                    efficiency_item.setBackground(QColor(76, 175, 80))
                    efficiency_item.setForeground(QColor(255, 255, 255))
                else:
                    efficiency_item.setBackground(QColor(244, 67, 54))
                    efficiency_item.setForeground(QColor(255, 255, 255))
                self.table.setItem(row_idx, 7, efficiency_item)
                
                # Case Value - colored based on OK/LOW status (same as efficiency)
                value_item = QTableWidgetItem(f"{case[10]:.1f}%")
                value_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if case[9] == "OK":
                    value_item.setBackground(QColor(76, 175, 80))
                    value_item.setForeground(QColor(255, 255, 255))
                else:
                    value_item.setBackground(QColor(244, 67, 54))
                    value_item.setForeground(QColor(255, 255, 255))
                self.table.setItem(row_idx, 8, value_item)
                
                row_idx += 1


