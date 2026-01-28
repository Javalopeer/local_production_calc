from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QTableWidget, QTableWidgetItem,
    QDateEdit, QComboBox, QFileDialog
)
from PySide6.QtCore import QDate
from db.database import get_connection
import csv

class HistoryTab(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.load_all_cases()

    def init_ui(self):
        main_layout = QVBoxLayout()

        # Title
        title = QLabel("Case History")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        main_layout.addWidget(title)

        # Search and Filter Layout
        filter_layout = QHBoxLayout()

        filter_layout.addWidget(QLabel("Search Case:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Case ID...")
        self.search_input.textChanged.connect(self.filter_cases)
        filter_layout.addWidget(self.search_input)

        filter_layout.addWidget(QLabel("Status:"))
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All", "OK", "LOW"])
        self.status_filter.currentTextChanged.connect(self.filter_cases)
        filter_layout.addWidget(self.status_filter)

        filter_layout.addWidget(QLabel("From:"))
        self.date_from = QDateEdit()
        self.date_from.setDate(QDate.currentDate().addMonths(-1))
        self.date_from.dateChanged.connect(self.filter_cases)
        filter_layout.addWidget(self.date_from)

        export_btn = QPushButton("Export CSV")
        export_btn.clicked.connect(self.export_csv)
        filter_layout.addWidget(export_btn)

        main_layout.addLayout(filter_layout)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels([
            "ID", "Case", "Region", "Case Type",
            "Date", "Time (min)", "Std (min)", "Efficiency %", "Status", "Case Value %"
        ])
        main_layout.addWidget(self.table)

        self.setLayout(main_layout)
        self.all_cases = []

    def load_all_cases(self):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, case_id, region, tipo_caso,
                   fecha, tiempo_real, std_time, efficiency, estado, case_value
            FROM cases
            ORDER BY fecha DESC, hora_inicio DESC
        """)
        self.all_cases = cursor.fetchall()
        conn.close()
        self.filter_cases()

    def filter_cases(self):
        search_text = self.search_input.text().lower()
        status_filter = self.status_filter.currentText()
        date_from = self.date_from.date().toString("yyyy-MM-dd")

        filtered = [
            case for case in self.all_cases
            if (search_text in str(case[1]).lower() or not search_text)
            and (status_filter == "All" or status_filter == case[8])
            and case[4] >= date_from
        ]

        self.table.setRowCount(len(filtered))

        for idx, case in enumerate(filtered):
            self.table.setItem(idx, 0, QTableWidgetItem(str(case[0])))
            self.table.setItem(idx, 1, QTableWidgetItem(str(case[1])))
            self.table.setItem(idx, 2, QTableWidgetItem(str(case[2])))
            self.table.setItem(idx, 3, QTableWidgetItem(str(case[3])))
            self.table.setItem(idx, 4, QTableWidgetItem(str(case[4])))
            self.table.setItem(idx, 5, QTableWidgetItem(f"{case[5]:.1f}"))
            self.table.setItem(idx, 6, QTableWidgetItem(f"{case[6]:.1f}"))
            
            efficiency_item = QTableWidgetItem(f"{case[7]:.1f}%")
            if case[8] == "OK":
                efficiency_item.setBackground(__import__('PySide6.QtGui', fromlist=['QColor']).QColor(144, 238, 144))
            else:
                efficiency_item.setBackground(__import__('PySide6.QtGui', fromlist=['QColor']).QColor(255, 127, 127))
            self.table.setItem(idx, 7, efficiency_item)
            
            self.table.setItem(idx, 8, QTableWidgetItem(case[8]))
            self.table.setItem(idx, 9, QTableWidgetItem(f"{case[9]:.3f}%"))

        self.table.resizeColumnsToContents()

    def export_csv(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Export History", "", "CSV Files (*.csv)")
        if file_path:
            try:
                with open(file_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        "ID", "Case", "Region", "Case Type",
                        "Date", "Time (min)", "Std (min)", "Efficiency (%)", "Status", "Case Value (%)"
                    ])
                    for case in self.all_cases:
                        writer.writerow(case)
                print(f"✅ File exported: {file_path}")
            except Exception as e:
                print(f"❌ Export error: {e}")
