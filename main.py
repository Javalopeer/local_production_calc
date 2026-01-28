import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget
)
from db.database import init_db


from tabs.tab_register import RegisterTab
from tabs.tab_production import ProductionTab
from tabs.tab_history import HistoryTab

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Local Production Calculator")
        self.setMinimumSize(675, 490)

        tabs = QTabWidget()
        tabs.addTab(RegisterTab(), "Register")
        tabs.addTab(ProductionTab(), "Production")
        tabs.addTab(HistoryTab(), "History")

        self.setCentralWidget(tabs)

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

    QComboBox {
        background-color: #2b2b2b;
        border: 1px solid #3c3c3c;
        border-radius: 6px;
        padding: 6px;
    }

    QComboBox:drop-down {
        border: none;
        background-color: transparent;
    }

    QComboBox::down-arrow {
        image: none;
    }

    QComboBox::down-arrow:on {
        image: none;
    }

    QComboBox QAbstractItemView {
        background-color: #2b2b2b;
        color: #e6e6e6;
        selection-background-color: #2d89ef;
        border: 1px solid #3c3c3c;
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
    }

    QTabBar::tab {
        background: #2b2b2b;
        padding: 10px 18px;
        border-radius: 6px;
        margin-right: 4px;
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
        background-color: #4CAF50;
        border-radius: 6px;
    }

    QTableWidget {
        background-color: #2b2b2b;
        alternate-background-color: #252525;
        gridline-color: #3c3c3c;
    }

    QTableWidget::item {
        padding: 4px;
    }

    QHeaderView::section {
        background-color: #2d89ef;
        color: white;
        padding: 4px;
        border: none;
    }
    """)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

