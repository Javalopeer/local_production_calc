from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout

class ProductionTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Producción & Porcentajes"))
        self.setLayout(layout)
