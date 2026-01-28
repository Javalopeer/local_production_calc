import json
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QComboBox, QLineEdit,
    QPushButton, QLabel, QTimeEdit, QVBoxLayout
)
from PySide6.QtCore import QTime
from db.database import get_connection
from datetime import datetime


class RegisterTab(QWidget):
    def __init__(self):
        super().__init__()

        self.load_standards()

        self.case_id = QLineEdit()
        self.region = QComboBox()
        self.vaso = QComboBox()
        self.tipo = QComboBox()

        self.start_time = QTimeEdit()
        self.end_time = QTimeEdit()

        self.result_label = QLabel("Porcentaje: -")

        self.region.addItems(self.standards.keys())
        self.vaso.addItems(["Aligners"])
        self.tipo.addItems(["Primary", "Secondary", "CR", "Stage RX", "Bite Sync"])

        self.start_time.setTime(QTime.currentTime())
        self.end_time.setTime(QTime.currentTime())

        calc_btn = QPushButton("Calcular")
        save_btn = QPushButton("Guardar Caso")
        save_btn.clicked.connect(self.save_case)

        calc_btn.clicked.connect(self.calculate)

        form = QFormLayout()
        form.addRow("ID Caso:", self.case_id)
        form.addRow("Región:", self.region)
        form.addRow("Tipo de Vaso:", self.vaso)
        form.addRow("Tipo de Caso:", self.tipo)
        form.addRow("Hora Inicio:", self.start_time)
        form.addRow("Hora Fin:", self.end_time)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(calc_btn)
        layout.addWidget(self.result_label)
        layout.addWidget(save_btn)

        self.setLayout(layout)

    def load_standards(self):
        with open("data/standards.json", "r") as f:
            self.standards = json.load(f)

    def calculate(self):
        region = self.region.currentText()
        vaso = self.vaso.currentText()
        tipo = self.tipo.currentText()

        std = self.standards[region][vaso][tipo]

        start = self.start_time.time()
        end = self.end_time.time()

        real_minutes = start.secsTo(end) / 60
        if real_minutes <= 0:
            self.result_label.setText("Tiempo inválido")
            return

        percent = (std / real_minutes) * 100

        status = "🟢" if percent >= 100 else "🔴"

        self.result_label.setText(
                f"Std: {std} min | Real: {real_minutes:.1f} min | "
                f"Producción: {percent:.1f}% {status}"
            )

    def save_case(self):  # <-- Unindented to be a class method
        region = self.region.currentText()
        vaso = self.vaso.currentText()
        tipo = self.tipo.currentText()
        case_id = self.case_id.text()
        doctor = ""  # opcional luego

        start = self.start_time.time()
        end = self.end_time.time()

        tiempo_real = start.secsTo(end) / 60
        if tiempo_real <= 0:
            return

        std = self.standards[region][vaso][tipo]
        porcentaje = (std / tiempo_real) * 100
        estado = "OK" if porcentaje >= 100 else "LOW"

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO cases (
                case_id, region, tipo_vaso, tipo_caso,
                doctor, fecha, hora_inicio, hora_fin,
                tiempo_real, std, porcentaje, estado
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            case_id,
            region,
            vaso,
            tipo,
            doctor,
            datetime.now().strftime("%Y-%m-%d"),
            start.toString("HH:mm"),
            end.toString("HH:mm"),
            tiempo_real,
            std,
            porcentaje,
            estado
        ))

        conn.commit()
        conn.close()

        self.result_label.setText("✅ Caso guardado correctamente")
