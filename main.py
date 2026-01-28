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
        self.setMinimumSize(675, 450)

        tabs = QTabWidget()
        tabs.addTab(RegisterTab(), "Register")
        tabs.addTab(ProductionTab(), "Production")
        tabs.addTab(HistoryTab(), "History")

        self.setCentralWidget(tabs)

if __name__ == "__main__":
    init_db()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

