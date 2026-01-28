import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget
)
from db.database import init_db
import qtawesome as qta


from tabs.tab_register import RegisterTab
from tabs.tab_production import ProductionTab
from tabs.tab_history import HistoryTab

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Production Performance Calculator")
        self.setWindowIcon(qta.icon('fa5s.calculator', color='#2d89ef'))

        tabs = QTabWidget()
        
        self.register_tab = RegisterTab()
        self.production_tab = ProductionTab()
        self.history_tab = HistoryTab()
        
        # Connect register tab to production tab for dynamic updates
        self.register_tab.case_saved.connect(self.production_tab.load_data)
        self.register_tab.case_saved.connect(self.history_tab.load_all_cases)
        
        tabs.addTab(self.register_tab, qta.icon('fa5s.edit', color='#4aa3ff'), "Register")
        tabs.addTab(self.production_tab, qta.icon('fa5s.chart-bar', color='#4aa3ff'), "Production")
        tabs.addTab(self.history_tab, qta.icon('fa5s.history', color='#4aa3ff'), "History")

        self.setCentralWidget(tabs)
        self.adjustSize()
        self.setFixedSize(self.size())

if __name__ == "__main__":
    init_db()
    app = QApplication(sys.argv)
    
    app.setStyleSheet("""
    QWidget {
        background-color: #1e1e1e;
        color: #e6e6e6;
        font-family: Segoe UI;
        font-size: 12px;
    }

    QLabel {
        color: #e6e6e6;
    }

    QLineEdit, QComboBox, QDateEdit, QTimeEdit {
        background-color: #2b2b2b;
        border: 1px solid #3c3c3c;
        border-radius: 6px;
        padding: 6px;
        color: #e6e6e6;
    }

    QTimeEdit::up-button, QTimeEdit::down-button,
    QDateEdit::up-button, QDateEdit::down-button {
        width: 0px;
        border: none;
    }

    QTimeEdit, QDateEdit {
        padding-right: 6px;
    }

    QComboBox {
        background-color: #2b2b2b;
        border: 1px solid #3c3c3c;
        border-radius: 6px;
        padding: 6px;
    }

    QComboBox QAbstractItemView {
        background-color: #2b2b2b;
        color: #e6e6e6;
        selection-background-color: #2d89ef;
        border: 1px solid #3c3c3c;
        outline: none;
    }

    QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus {
        border: 1px solid #4aa3ff;
    }

    QPushButton {
        background-color: #2d89ef;
        border: none;
        border-radius: 6px;
        padding: 8px 14px;
        color: white;
        font-weight: bold;
    }

    QPushButton:hover {
        background-color: #1e6fd9;
    }

    QPushButton:pressed {
        background-color: #165ab8;
    }

    QPushButton:disabled {
        background-color: #555;
    }

    QTabWidget::pane {
        border: 1px solid #3c3c3c;
        margin-top: 5px;
    }

    QTabBar::tab {
        background: #2b2b2b;
        padding: 8px 16px;
        border-radius: 6px;
        margin-left: 10px;
        margin-top: 8px;
        margin-bottom: 4px;
        border: 1px solid #3c3c3c;
        color: #999;
        font-weight: 500;
    }

    QTabBar::tab:hover {
        background: #333;
        color: #e6e6e6;
    }

    QTabBar::tab:selected {
        background: #2d89ef;
        color: white;
        border: 1px solid #2d89ef;
    }

    QGroupBox {
        border: 1px solid #3c3c3c;
        border-radius: 8px;
        margin-top: 10px;
        padding: 10px;
        color: #e6e6e6;
    }

    QGroupBox:title {
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 6px;
        color: #4aa3ff;
        font-weight: bold;
    }

    QProgressBar {
        border: 1px solid #3c3c3c;
        border-radius: 8px;
        text-align: center;
        height: 24px;
        background-color: #2b2b2b;
    }

    QProgressBar::chunk {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #2d89ef, stop:0.5 #4CAF50, stop:1 #2d89ef);
        border-radius: 6px;
    }

    QTableWidget {
        background-color: #2b2b2b;
        alternate-background-color: #333333;
        gridline-color: #3c3c3c;
        selection-background-color: #2d89ef;
    }

    QTableWidget::item {
        padding: 6px;
        border-bottom: 1px solid #3c3c3c;
    }

    QTableWidget::item:alternate {
        background-color: #333333;
    }

    QHeaderView::section {
        background-color: #2d89ef;
        color: white;
        padding: 6px;
        border: none;
        font-weight: bold;
    }
    """)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

