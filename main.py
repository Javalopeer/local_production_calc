import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QScrollArea, QCheckBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from db.database import init_db
import qtawesome as qta

# ============== VERSION ==============
APP_VERSION = "1.0.0"
DB_SCHEMA_VERSION = 1
# =====================================

from tabs.tab_register import RegisterTab
from tabs.tab_production import ProductionTab
from tabs.tab_history import HistoryTab
from tabs.tab_overtime import OvertimeTab
from tabs.tab_standards import StandardsTab

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Production Performance Calculator v{APP_VERSION}")
        self.setWindowIcon(qta.icon('fa5s.calculator', color='#2d89ef'))

        self.tabs = QTabWidget()
        
        self.register_tab = RegisterTab()
        self.production_tab = ProductionTab()
        self.history_tab = HistoryTab()
        self.overtime_tab = OvertimeTab()
        self.standards_tab = StandardsTab()

        
        # Connect register tab to production tab for dynamic updates
        self.register_tab.case_saved.connect(self.production_tab.load_data)
        self.register_tab.case_saved.connect(self.history_tab.load_all_cases)
        
        # Connect production tab edit/delete to register tab
        self.production_tab.case_updated.connect(self.on_production_case_updated)
        
        # Connect OT tab to refresh when cases change
        self.overtime_tab.ot_saved.connect(self.history_tab.load_all_cases)
        
        # Connect standards tab to refresh Register and OT when standards change
        self.standards_tab.standards_updated.connect(self.on_standards_updated)
        
        self.tabs.addTab(self.register_tab, qta.icon('fa5s.edit', color='#4aa3ff'), "Register")
        self.tabs.addTab(self.overtime_tab, qta.icon('fa5s.clock', color='#FF9800'), "OT")
        self.tabs.addTab(self.production_tab, qta.icon('fa5s.chart-bar', color='#4aa3ff'), "Production")
        self.tabs.addTab(self.history_tab, qta.icon('fa5s.history', color='#4aa3ff'), "History")
        self.tabs.addTab(self.standards_tab, qta.icon('fa5s.cog', color='#9E9E9E'), "Standards")

        self.setCentralWidget(self.tabs)
        
        # Get screen height for maximum window height
        screen = QGuiApplication.primaryScreen()
        screen_height = screen.availableGeometry().height()
        
        # Set size constraints - resizable with min/max
        self.setMinimumSize(640, 550)  # Minimum width 640px
        self.setMaximumSize(900, screen_height)  # Maximum height = monitor height
        self.resize(900, 700)  # Default size 900x700
        # Theme toggle checkbox in status bar
        try:
            light_chk = QCheckBox("Light")
            light_chk.setToolTip("Toggle light mode")
            light_chk.toggled.connect(lambda checked: QApplication.instance().setStyleSheet(LIGHT_STYLE if checked else DARK_STYLE))
            self.statusBar().addPermanentWidget(light_chk)
        except Exception:
            pass

    def on_standards_updated(self):
        """Reload standards in Register and OT tabs when standards are modified"""
        self.register_tab.load_standards()
        self.register_tab.update_case_types()
        self.overtime_tab.load_standards()
        self.overtime_tab.update_case_types()

    def on_production_case_updated(self):
        """Handle case update/delete from production tab"""
        # Check if production_tab has an editing_case_id (edit action)
        if hasattr(self.production_tab, 'editing_case_id') and self.production_tab.editing_case_id:
            # Load case into register tab for editing
            self.register_tab.load_case_for_edit(self.production_tab.editing_case_id)
            self.production_tab.editing_case_id = None
            # Switch to Register tab
            self.tabs.setCurrentIndex(0)
        else:
            # Just refresh register tab (delete action)
            self.register_tab.load_daily_production()
        
        # Refresh history tab
        self.history_tab.load_all_cases()

if __name__ == "__main__":
    init_db()
    app = QApplication(sys.argv)

    DARK_STYLE = """
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
        gridline-color: #3c3c3c;
        selection-background-color: #2d89ef;
    }

    QTableWidget::item {
        padding: 6px;
    }

    QHeaderView::section {
        background-color: #2d89ef;
        color: white;
        padding: 6px;
        border: none;
        font-weight: bold;
    }
    """

    LIGHT_STYLE = """
    QWidget {
        background-color: #F7ECE1; /* main background */
        color: #242038; /* primary text */
        font-family: Segoe UI;
        font-size: 12px;
    }

    QLabel {
        color: #242038;
    }

    QLineEdit, QComboBox, QDateEdit, QTimeEdit {
        background-color: #ffffff;
        border: 1px solid #CAC4CE;
        border-radius: 6px;
        padding: 6px;
        color: #242038;
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
        background-color: #ffffff;
        border: 1px solid #CAC4CE;
        border-radius: 6px;
        padding: 6px;
    }

    QComboBox QAbstractItemView {
        background-color: #ffffff;
        color: #242038;
        selection-background-color: #8D86C9;
        border: 1px solid #CAC4CE;
        outline: none;
    }

    QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus {
        border: 1px solid #725AC1;
    }

    QPushButton {
        background-color: #725AC1; /* primary action */
        border: none;
        border-radius: 6px;
        padding: 8px 14px;
        color: white;
        font-weight: bold;
    }

    QPushButton:hover {
        background-color: #8D86C9; /* hover */
    }

    QPushButton:pressed {
        background-color: #5e489f;
    }

    QPushButton:disabled {
        background-color: #CAC4CE;
    }

    QTabWidget::pane {
        border: 1px solid #CAC4CE;
        margin-top: 5px;
    }

    QTabBar::tab {
        background: #F7ECE1;
        padding: 8px 16px;
        border-radius: 6px;
        margin-left: 10px;
        margin-top: 8px;
        margin-bottom: 4px;
        border: 1px solid #CAC4CE;
        color: #242038;
        font-weight: 500;
    }

    QTabBar::tab:hover {
        background: #fff7f0;
        color: #242038;
    }

    QTabBar::tab:selected {
        background: #725AC1;
        color: white;
        border: 1px solid #725AC1;
    }

    QGroupBox {
        border: 1px solid #CAC4CE;
        border-radius: 8px;
        margin-top: 10px;
        padding: 10px;
        color: #242038;
    }

    QGroupBox:title {
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 6px;
        color: #725AC1;
        font-weight: bold;
    }

    QProgressBar {
        border: 1px solid #CAC4CE;
        border-radius: 8px;
        text-align: center;
        height: 24px;
        background-color: #ffffff;
    }

    QProgressBar::chunk {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #8D86C9, stop:0.5 #725AC1, stop:1 #8D86C9);
        border-radius: 6px;
    }

    QTableWidget {
        gridline-color: #CAC4CE;
        selection-background-color: #8D86C9;
    }

    QTableWidget::item {
        padding: 6px;
    }

    QHeaderView::section {
        background-color: #8D86C9;
        color: white;
        padding: 6px;
        border: none;
        font-weight: bold;
    }
    """

    app.setStyleSheet(DARK_STYLE)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

