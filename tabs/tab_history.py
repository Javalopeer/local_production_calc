from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout

class HistoryTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Historial de Casos"))
        self.setLayout(layout)
