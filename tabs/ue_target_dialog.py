# -*- coding: utf-8 -*-
"""Dialog to manage the UE daily target by effective date.

Each row defines a period: starting on `start_date`, the daily UE target is
`value`. The newest start_date that is <= a given date wins. Users can add
rows for any frequency (weekly, monthly, quarterly, ad hoc) — the schema
doesn't care, it just resolves by date.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QDateEdit, QDoubleSpinBox,
)

from sync.daily_performance import (
    UE_TARGET, list_ue_target_periods, set_ue_target_periods,
)


class UETargetDialog(QDialog):
    """Manage UE target periods (start_date, value)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Daily UE Target")
        self.setMinimumSize(460, 380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        info = QLabel(
            "Set the daily UE target by effective date. Add a row whenever the "
            "target changes — the most recent start date on or before any given "
            f"day wins. If empty, the default ({UE_TARGET:.2f}) is used."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(info)

        # Editor row for adding new periods
        editor = QHBoxLayout()
        editor.addWidget(QLabel("Effective from:"))
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.currentDate())
        editor.addWidget(self.date_edit)

        editor.addSpacing(8)
        editor.addWidget(QLabel("Target UE:"))
        self.value_edit = QDoubleSpinBox()
        self.value_edit.setRange(0.1, 999.0)
        self.value_edit.setDecimals(2)
        self.value_edit.setSingleStep(0.5)
        self.value_edit.setValue(UE_TARGET)
        editor.addWidget(self.value_edit)

        add_btn = QPushButton("Add / Update")
        add_btn.clicked.connect(self._on_add)
        editor.addWidget(add_btn)
        editor.addStretch()
        layout.addLayout(editor)

        # Periods table
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Effective from", "UE target"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table)

        # Action buttons
        btn_row = QHBoxLayout()
        del_btn = QPushButton("Delete selected")
        del_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        save_btn = QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        self._load()

    # ── data plumbing ──────────────────────────────────────────────────────
    def _load(self):
        self.table.setRowCount(0)
        for start_date, value in list_ue_target_periods():
            self._append_row(start_date, value)

    def _append_row(self, start_date: str, value: float):
        row = self.table.rowCount()
        self.table.insertRow(row)
        date_item = QTableWidgetItem(start_date)
        date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        val_item = QTableWidgetItem(f"{value:.2f}")
        val_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 0, date_item)
        self.table.setItem(row, 1, val_item)

    def _periods_from_table(self) -> list[tuple[str, float]]:
        out: list[tuple[str, float]] = []
        for r in range(self.table.rowCount()):
            d = self.table.item(r, 0).text()
            v = float(self.table.item(r, 1).text())
            out.append((d, v))
        return out

    # ── handlers ───────────────────────────────────────────────────────────
    def _on_add(self):
        new_date = self.date_edit.date().toString("yyyy-MM-dd")
        new_value = self.value_edit.value()
        # Replace existing row for the same date, else append
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).text() == new_date:
                self.table.item(r, 1).setText(f"{new_value:.2f}")
                return
        self._append_row(new_date, new_value)
        self.table.sortItems(0, Qt.SortOrder.AscendingOrder)

    def _on_delete(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def _on_save(self):
        try:
            periods = self._periods_from_table()
            set_ue_target_periods(periods)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self.accept()
