from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QDateEdit, QTableWidget, QTableWidgetItem
)
from PySide6.QtCore import QDate
from PySide6.QtGui import QColor
from db.database import get_connection
from datetime import datetime, timedelta

class ProductionTab(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        main_layout = QVBoxLayout()

        # Title
        title = QLabel("Production & Percentages")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #4aa3ff;")
        main_layout.addWidget(title)

        # Stats Layout
        stats_layout = QHBoxLayout()

        self.stats_avg = QLabel("Average: -")
        self.stats_total = QLabel("Total Cases: -")
        self.stats_ok = QLabel("OK: -")
        self.stats_low = QLabel("LOW: -")

        for stat in [self.stats_avg, self.stats_total, self.stats_ok, self.stats_low]:
            stat.setStyleSheet("padding: 10px; border: 1px solid #3c3c3c; border-radius: 5px; background-color: #2b2b2b;")
            stats_layout.addWidget(stat)

        main_layout.addLayout(stats_layout)

        # Date Filter
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter from:"))
        self.date_filter = QDateEdit()
        self.date_filter.setDate(QDate.currentDate().addDays(-7))
        filter_layout.addWidget(self.date_filter)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_data)
        filter_layout.addWidget(refresh_btn)
        filter_layout.addStretch()

        main_layout.addLayout(filter_layout)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["Case", "Region", "Type", "Real (min)", "Std (min)", "Efficiency %", "Case Value %"])
        main_layout.addWidget(self.table)

        self.setLayout(main_layout)

    def load_data(self):
        conn = get_connection()
        cursor = conn.cursor()

        date_from = self.date_filter.date().toString("yyyy-MM-dd")

        cursor.execute("""
            SELECT case_id, region, tipo_caso, tiempo_real, std_time, efficiency, estado, case_value
            FROM cases
            WHERE fecha >= ?
            ORDER BY fecha DESC, hora_inicio DESC
        """, (date_from,))

        rows = cursor.fetchall()
        conn.close()

        self.table.setRowCount(len(rows))

        total_cases = len(rows)
        ok_count = sum(1 for row in rows if row[6] == "OK")
        low_count = total_cases - ok_count
        total_value = sum(row[7] for row in rows)
        avg_efficiency = sum(row[5] for row in rows) / total_cases if total_cases > 0 else 0

        self.stats_avg.setText(f"Avg Efficiency: {avg_efficiency:.1f}%")
        self.stats_total.setText(f"Total Cases: {total_cases}")
        self.stats_ok.setText(f"Total Value: {total_value:.2f}%")
        self.stats_low.setText(f"🟢 {ok_count} | 🔴 {low_count}")

        for idx, row in enumerate(rows):
            self.table.setItem(idx, 0, QTableWidgetItem(str(row[0])))
            self.table.setItem(idx, 1, QTableWidgetItem(str(row[1])))
            self.table.setItem(idx, 2, QTableWidgetItem(str(row[2])))
            self.table.setItem(idx, 3, QTableWidgetItem(f"{row[3]:.1f}"))
            self.table.setItem(idx, 4, QTableWidgetItem(f"{row[4]:.1f}"))
            
            efficiency_item = QTableWidgetItem(f"{row[5]:.1f}%")
            if row[6] == "OK":
                efficiency_item.setBackground(QColor(76, 175, 80))  # Green
                efficiency_item.setForeground(QColor(255, 255, 255))
            else:
                efficiency_item.setBackground(QColor(244, 67, 54))  # Red
                efficiency_item.setForeground(QColor(255, 255, 255))
            self.table.setItem(idx, 5, efficiency_item)
            
            self.table.setItem(idx, 6, QTableWidgetItem(f"{row[7]:.3f}%"))

        self.table.resizeColumnsToContents()
